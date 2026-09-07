"""Static factories bind reviewed data contracts to injected future services.

M4 has no worker transport, model calls, approval execution, or publication.
External types fail explicitly until a service handler is supplied. The injected
interface is also used by deterministic compiler acceptance tests.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from types import MappingProxyType
from typing import cast

from langchain_core.runnables import RunnableConfig

from jarvis_contracts.workflow import NodePolicy, WorkflowNode, WorkflowNodeType
from jarvis_contracts.workflow_api import WorkflowResolvedSnapshot
from jarvis_contracts.workflow_nodes import NODE_DEFINITIONS
from jarvis_orchestrator.workflows.state import WorkflowInvariantError, WorkflowStateV1


class MissingWorkflowHandlerError(RuntimeError):
    """The real service belongs to a later milestone and has not been bound."""


@dataclass(frozen=True)
class NodeContext:
    node: WorkflowNode
    policy: NodePolicy
    snapshot: WorkflowResolvedSnapshot
    execution_id: str


NodeHandler = Callable[[WorkflowStateV1, NodeContext, RunnableConfig], Awaitable[WorkflowStateV1]]
NodeCallable = Callable[[WorkflowStateV1, RunnableConfig], Awaitable[WorkflowStateV1]]
NodeFactory = Callable[[NodeContext, NodeHandler | None], NodeCallable]


def invocation_key(state: WorkflowStateV1, node_id: str) -> str:
    return f"visit:{state.get('child_identity', 'main')}:{node_id}"


def child_id(fanout_id: str, visit: int, child: str) -> str:
    return f"{fanout_id}:{visit}:{child}"


def _dispatch(state: WorkflowStateV1) -> WorkflowStateV1:
    tasks = deepcopy(state.get("tasks", {}))
    # Selection is pure graph state transformation. Durable claiming/leases are M5.
    items = tasks.get("items")
    if isinstance(items, dict):
        terminal = {
            key
            for key, item in items.items()
            if isinstance(item, dict) and item.get("status") in {"completed", "failed", "cancelled"}
        }
        completed = {
            key
            for key, item in items.items()
            if isinstance(item, dict) and item.get("status") == "completed"
        }
        ready = []
        for key, item in sorted(items.items()):
            if not isinstance(item, dict):
                raise WorkflowInvariantError("Task entries must be objects")
            dependencies = item.get("dependencies", [])
            if not isinstance(dependencies, list) or not all(
                isinstance(value, str) and value in items for value in dependencies
            ):
                raise WorkflowInvariantError("Task dependencies must name planned task keys")
            if item.get("status", "pending") == "pending" and set(dependencies) <= completed:
                ready.append(key)
        tasks.update(
            terminal_count=len(terminal),
            total_count=len(items),
            current_task=next(iter(ready), None),
        )
    return {"tasks": tasks}


def _internal(state: WorkflowStateV1, context: NodeContext) -> WorkflowStateV1:
    node = context.node
    if node.type is WorkflowNodeType.TASK_DISPATCH:
        return _dispatch(state)
    if node.type is WorkflowNodeType.FANOUT:
        visit = state.get("counters", {}).get(invocation_key(state, node.id), 0) + 1
        children = cast(list[str], node.config["children"])
        return {"expected_children": [child_id(node.id, visit, child) for child in children]}
    if node.type is WorkflowNodeType.JOIN:
        fanout_id = str(node.config["fanout_id"])
        prefix = f"{fanout_id}:{state.get('counters', {}).get(f'visit:main:{fanout_id}', 0)}:"
        expected = [key for key in state.get("expected_children", []) if key.startswith(prefix)]
        completed = set(state.get("completed_children", []))
        results = state.get("child_results", {})
        if not expected or any(key not in completed or key not in results for key in expected):
            raise WorkflowInvariantError(f"Join {node.id} received incomplete child results")
        return {"results": {f"join:{prefix}": {key: results[key] for key in sorted(expected)}}}
    if node.type is WorkflowNodeType.FINALIZE:
        outcome = node.config["outcome"]
        result = state.get("outcome", {})
        status = result.get("status", "failed" if result.get("failure_class") else "completed")
        child_failures: set[str] = set()
        for branch in state.get("child_results", {}).values():
            if not isinstance(branch, dict):
                continue
            for child_result in branch.values():
                if not isinstance(child_result, dict):
                    continue
                child_status = child_result.get("status")
                if child_result.get("failure_class"):
                    child_failures.add("failed")
                elif isinstance(child_status, str) and child_status in {
                    "failed",
                    "blocked",
                    "cancelled",
                }:
                    child_failures.add(child_status)
        for child_status in ("blocked", "failed", "cancelled"):
            if child_status in child_failures:
                status = child_status
        if outcome != "derive":
            status = outcome
        if state.get("cancelled"):
            status = "cancelled"
        if status == "succeeded":
            status = "completed"
        if not isinstance(status, str) or status not in {
            "completed",
            "failed",
            "blocked",
            "cancelled",
        }:
            raise WorkflowInvariantError("Finalize received an unknown classified outcome")
        return {"final": {"status": status}}
    return {}


def _factory(context: NodeContext, handler: NodeHandler | None) -> NodeCallable:
    definition = NODE_DEFINITIONS[context.node.type]

    async def invoke(state: WorkflowStateV1, config: RunnableConfig) -> WorkflowStateV1:
        # Every call gets a private copy; frozen Pydantic models can still contain dicts.
        visit_key = invocation_key(state, context.node.id)
        visit = state.get("counters", {}).get(visit_key, 0) + 1
        call_context = NodeContext(
            node=context.node.model_copy(deep=True),
            policy=context.policy.model_copy(deep=True),
            snapshot=context.snapshot.model_copy(deep=True),
            execution_id=f"{state.get('child_identity', 'main')}:{context.node.id}:{visit}",
        )
        approval = context.policy.approval
        if approval is not None and approval.required_grant_from:
            grant = state.get("approval", {})
            if (
                grant.get("decision") != "approved"
                or grant.get("action_type") != approval.action_type
                or grant.get("granted_by") != approval.required_grant_from
            ):
                raise WorkflowInvariantError("Protected action has no matching approved grant")
        if (
            context.node.type in {WorkflowNodeType.REVIEWER, WorkflowNodeType.GITHUB_PUBLISH}
            and state.get("verification", {}).get("passed") is not True
        ):
            raise WorkflowInvariantError("Required verification has not passed")
        if (
            context.node.type is WorkflowNodeType.GITHUB_PUBLISH
            and state.get("review", {}).get("passed") is not True
        ):
            raise WorkflowInvariantError("Required review has not passed")
        if (
            context.node.type is WorkflowNodeType.FINALIZE
            and context.node.config["outcome"] == "derive"
            and state.get("_needs_verification")
            and not state.get("cancelled")
            and not state.get("outcome", {}).get("failure_class")
            and state.get("outcome", {}).get("status") not in {"failed", "blocked", "cancelled"}
        ):
            raise WorkflowInvariantError("Final success cannot bypass required verification")
        if definition.external:
            if handler is None:
                raise MissingWorkflowHandlerError(
                    f"Node {context.node.id} ({context.node.type.value}) "
                    "has no bound service handler"
                )
            async with asyncio.timeout(context.policy.timeout_seconds):
                update = await handler(deepcopy(state), call_context, config)
            allowed = set(definition.outputs) | {"node", "outcome"}
            if set(update) - allowed:
                raise WorkflowInvariantError(
                    f"Node {context.node.id} wrote channels outside its declared contract"
                )
            if state.get("child_identity") and set(update) - {"results"}:
                raise WorkflowInvariantError("Parallel children may only write reduced results")
        else:
            update = _internal(state, call_context)
        if context.node.type is WorkflowNodeType.WORKER and not state.get("child_identity"):
            update["verification"] = {}
            update["review"] = {}
            update["approval"] = {}
            update["_needs_verification"] = bool(
                context.policy.verification and context.policy.verification.required
            )
        if context.node.type is WorkflowNodeType.VERIFY:
            update["_needs_verification"] = update.get("verification", {}).get("passed") is not True
        if context.node.type is WorkflowNodeType.ARCHITECT:
            tasks = update.get("tasks", {})
            items = tasks.get("items", {})
            if not isinstance(items, dict):
                raise WorkflowInvariantError("Architect task entries must be an object")
            count = tasks.get("total_count", len(items))
            if (
                type(count) is not int
                or not 0 <= count <= cast(int, context.node.config["max_tasks"])
                or len(items) > cast(int, context.node.config["max_tasks"])
                or ("items" in tasks and len(items) != count)
            ):
                raise WorkflowInvariantError("Architect output exceeds its declared task bound")
        results = update.get("results", {})
        # Handlers submit a result for their execution, never overwrite unrelated IDs.
        if definition.external and set(results) - {call_context.execution_id}:
            raise WorkflowInvariantError("Handler results must use the supplied execution identity")
        if call_context.execution_id not in results:
            results = {**results, call_context.execution_id: {"node_id": context.node.id}}
        update["results"] = results
        update["counters"] = {visit_key: visit}
        return update

    return invoke


NODE_FACTORIES: Mapping[WorkflowNodeType, NodeFactory] = MappingProxyType(
    {node_type: _factory for node_type in NODE_DEFINITIONS}
)
