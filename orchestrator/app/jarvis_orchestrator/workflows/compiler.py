"""Deterministic, bounded canonical-spec to LangGraph compiler (M4 only)."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Hashable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, cast

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Checkpointer, Send

from jarvis_contracts.base import sha256_digest
from jarvis_contracts.registry import RetryRegistrySpec
from jarvis_contracts.workflow import (
    COMPILER_VERSION,
    WorkflowEdge,
    WorkflowEdgeKind,
    WorkflowNode,
    WorkflowNodeType,
    WorkflowSpec,
)
from jarvis_contracts.workflow_api import WorkflowResolvedSnapshot, WorkflowValidationReport
from jarvis_contracts.workflow_nodes import NODE_DEFINITIONS
from jarvis_orchestrator.workflows.factories import (
    NODE_FACTORIES,
    NodeContext,
    NodeHandler,
    child_id,
    invocation_key,
)
from jarvis_orchestrator.workflows.predicates import evaluate_predicate, get_path
from jarvis_orchestrator.workflows.state import (
    BranchOutput,
    WorkflowInvariantError,
    WorkflowStateV1,
    merged_state,
)
from jarvis_orchestrator.workflows.validation import (
    effective_policy,
    normalize_workflow,
    validate_workflow,
)

CompiledWorkflow = CompiledStateGraph[WorkflowStateV1, None, WorkflowStateV1, Any]


class WorkflowCompilationError(ValueError):
    def __init__(self, report: WorkflowValidationReport) -> None:
        self.report = report
        super().__init__("Workflow validation failed: " + ", ".join(i.code for i in report.issues))


def compilation_identity(spec: WorkflowSpec, snapshot: WorkflowResolvedSnapshot) -> str:
    return sha256_digest(
        {
            "workflow_content_hash": normalize_workflow(spec).content_hash,
            "spec_version": spec.spec_version,
            "compiler_version": COMPILER_VERSION,
            "snapshot_hash": snapshot.snapshot_hash,
        }
    )


def workflow_run_config(thread_id: str, config: RunnableConfig | None = None) -> RunnableConfig:
    """Bind runs.langgraph_thread_id verbatim; leave LangGraph's namespace intact."""
    if not thread_id or len(thread_id) > 200:
        raise ValueError("A stable run thread ID of at most 200 characters is required")
    result = cast(RunnableConfig, dict(config or {}))
    configurable = dict(result.get("configurable", {}))
    if configurable.get("thread_id", thread_id) != thread_id:
        raise ValueError("Cannot change a run's stable checkpoint thread ID")
    configurable["thread_id"] = thread_id
    result["configurable"] = configurable
    return result


@dataclass
class _CacheEntry:
    graph: CompiledWorkflow
    # Strong references prevent recycled object IDs from reusing stale services.
    checkpointer: Checkpointer
    handlers: tuple[tuple[str, NodeHandler], ...]


class CompileCache:
    """Explicitly owned process-local LRU; close with the service/checkpointer scope."""

    def __init__(self, max_entries: int = 32) -> None:
        if not 1 <= max_entries <= 256:
            raise ValueError("Compile cache capacity must be between 1 and 256")
        self.max_entries = max_entries
        self._entries: OrderedDict[tuple[Any, ...], _CacheEntry] = OrderedDict()
        self.closed = False

    def __len__(self) -> int:
        return len(self._entries)

    def close(self) -> None:
        self._entries.clear()
        self.closed = True

    def _get(self, key: tuple[Any, ...]) -> CompiledWorkflow | None:
        if self.closed:
            raise RuntimeError("Compile cache belongs to a closed service scope")
        entry = self._entries.get(key)
        if entry is None:
            return None
        self._entries.move_to_end(key)
        return entry.graph

    def _put(self, key: tuple[Any, ...], entry: _CacheEntry) -> None:
        self._entries[key] = entry
        self._entries.move_to_end(key)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)


def _failure_class(state: WorkflowStateV1) -> object:
    return state.get("outcome", {}).get("failure_class", state.get("node", {}).get("failure_class"))


def _choose_route(
    spec: WorkflowSpec,
    snapshot: WorkflowResolvedSnapshot,
    node: WorkflowNode,
    edges: list[WorkflowEdge],
    state: WorkflowStateV1,
) -> tuple[str, dict[str, int]]:
    fallback = next((edge for edge in edges if edge.fallback), None)
    counters = state.get("counters", {})
    for edge in edges:
        if edge.fallback:
            continue
        if edge.when is not None and not evaluate_predicate(edge.when, state):
            continue
        failure_class = _failure_class(state)
        if edge.kind is WorkflowEdgeKind.ON_FAILURE and not failure_class:
            continue
        if (
            edge.kind is WorkflowEdgeKind.ON_FAILURE
            and edge.retry_class is not None
            and failure_class != edge.retry_class.value
        ):
            continue
        if edge.kind is WorkflowEdgeKind.RETRY:
            if edge.retry_class is None or failure_class != edge.retry_class.value:
                continue
            policy_id = effective_policy(spec, node).retry_policy_ref
            policy = next(rev.spec for rev in snapshot.revisions if rev.revision_id == policy_id)
            if not isinstance(policy, RetryRegistrySpec):
                raise WorkflowInvariantError("Retry policy snapshot has an incompatible type")
            rule = next(rule for rule in policy.rules if rule.failure_class == edge.retry_class)
            key = f"retry:{node.id}:{edge.retry_class.value}"
            consumed = counters.get(key, 0)
            if consumed >= rule.max_retries:
                if fallback is None:
                    raise WorkflowInvariantError("Exhausted retry has no fallback")
                return fallback.target, {}
            return edge.target, {key: consumed + 1}
        if edge.kind is WorkflowEdgeKind.ITERATE:
            progress = get_path(state, str(edge.progress_path))
            key = f"iterate:{edge.iteration_key}"
            previous = counters.get(f"{key}:progress", -1)
            count = counters.get(key, 0)
            if type(progress) is not int or progress < 0 or progress <= previous:
                raise WorkflowInvariantError(f"Iterator {edge.id} did not make monotonic progress")
            if edge.max_iterations is None or count >= edge.max_iterations:
                raise WorkflowInvariantError(f"Iterator {edge.id} exceeded its hard bound")
            return edge.target, {key: count + 1, f"{key}:progress": progress}
        return edge.target, {}
    if fallback is None:
        raise WorkflowInvariantError(f"Node {node.id} has no matching route")
    return fallback.target, {}


def _branch_regions(spec: WorkflowSpec) -> dict[str, dict[str, set[str]]]:
    adjacency: dict[str, list[str]] = {}
    for edge in spec.edges:
        adjacency.setdefault(edge.source, []).append(edge.target)
    regions: dict[str, dict[str, set[str]]] = {}
    for node in spec.nodes:
        if node.type is not WorkflowNodeType.FANOUT:
            continue
        regions[node.id] = {}
        for child in cast(list[str], node.config["children"]):
            visited: set[str] = set()
            pending = [child]
            while pending:
                current = pending.pop()
                if current == node.config["join_id"] or current in visited:
                    continue
                visited.add(current)
                pending.extend(adjacency.get(current, []))
            regions[node.id][child] = visited
    return regions


def _superstep_limit(spec: WorkflowSpec, snapshot: WorkflowResolvedSnapshot) -> int:
    """Bound graph steps from the same immutable budgets that guard back edges."""
    nodes = {node.id: node for node in spec.nodes}
    limits: dict[str, int] = {}
    revisions = {revision.revision_id: revision.spec for revision in snapshot.revisions}
    for edge in spec.edges:
        if edge.kind is WorkflowEdgeKind.ITERATE:
            limits[f"iterate:{edge.iteration_key}"] = edge.max_iterations or 0
        elif edge.kind is WorkflowEdgeKind.RETRY:
            policy_id = effective_policy(spec, nodes[edge.source]).retry_policy_ref
            policy = revisions.get(policy_id) if policy_id else None
            if isinstance(policy, RetryRegistrySpec):
                rule = next(rule for rule in policy.rules if rule.failure_class == edge.retry_class)
                limits[f"retry:{edge.source}:{edge.retry_class}"] = rule.max_retries
    # Between any two bounded back edges the remaining graph is acyclic. Every
    # back edge consumes one global counter; each acyclic segment visits at most
    # all nodes. Two spare steps cover START/END and native child completion.
    return len(spec.nodes) * (1 + sum(limits.values())) + 2


def compile_workflow(
    spec: WorkflowSpec,
    snapshot: WorkflowResolvedSnapshot,
    *,
    checkpointer: Checkpointer = None,
    handlers: Mapping[str, NodeHandler] | None = None,
    cache: CompileCache | None = None,
    interrupt_before: list[str] | None = None,
) -> CompiledWorkflow:
    """Compile one isolated snapshot; missing external handlers fail on invocation."""
    report = validate_workflow(spec, snapshot)
    if not report.valid:
        raise WorkflowCompilationError(report)
    normalized = normalize_workflow(spec).model_copy(deep=True)
    bound_snapshot = snapshot.model_copy(deep=True)
    bound_handlers = dict(handlers or {})
    node_ids = {node.id for node in normalized.nodes}
    if set(bound_handlers) - node_ids:
        raise ValueError("Handlers must bind existing workflow node IDs")
    if any(
        node.id in bound_handlers and not NODE_DEFINITIONS[node.type].external
        for node in normalized.nodes
    ):
        raise ValueError("Only external node types accept injected service handlers")
    identity = compilation_identity(normalized, bound_snapshot)
    superstep_limit = _superstep_limit(normalized, bound_snapshot)
    handler_bindings = tuple(sorted(bound_handlers.items()))
    cache_key = (
        identity,
        id(checkpointer),
        tuple((key, id(value)) for key, value in handler_bindings),
        tuple(interrupt_before or []),
    )
    if cache is not None:
        existing = cache._get(cache_key)
        if existing is not None:
            return existing
    nodes = {node.id: node for node in normalized.nodes}
    outgoing = {
        node.id: sorted(
            [edge for edge in normalized.edges if edge.source == node.id],
            key=lambda edge: (edge.priority, edge.id),
        )
        for node in normalized.nodes
    }
    regions = _branch_regions(normalized)
    parallel_ids = {
        node_id
        for branches in regions.values()
        for region in branches.values()
        for node_id in region
    }

    def add_node(
        builder: StateGraph[WorkflowStateV1, None, WorkflowStateV1, Any], node: WorkflowNode
    ) -> None:
        factory = NODE_FACTORIES[node.type]
        execute = factory(
            NodeContext(node, effective_policy(normalized, node), bound_snapshot, ""),
            bound_handlers.get(node.id),
        )

        async def invoke(state: WorkflowStateV1, config: RunnableConfig) -> WorkflowStateV1:
            update = await execute(state, config)
            edges = outgoing[node.id]
            if edges and node.type is not WorkflowNodeType.FANOUT:
                target, counters = _choose_route(
                    normalized, bound_snapshot, node, edges, merged_state(state, update)
                )
                update["_route"] = target
                update["counters"] = {**update.get("counters", {}), **counters}
            return update

        builder.add_node(node.id, invoke)

    def route(state: WorkflowStateV1) -> str:
        return state["_route"]

    def wire(
        builder: StateGraph[WorkflowStateV1, None, WorkflowStateV1, Any],
        node: WorkflowNode,
        boundary: str | None = None,
    ) -> None:
        edges = outgoing[node.id]
        if not edges:
            builder.add_edge(node.id, END)
        elif len(edges) == 1 and edges[0].kind is WorkflowEdgeKind.ALWAYS:
            target = edges[0].target
            builder.add_edge(node.id, "__complete__" if target == boundary else target)
        else:
            destinations: dict[Hashable, str] = {
                edge.target: "__complete__" if edge.target == boundary else edge.target
                for edge in edges
            }
            builder.add_conditional_edges(node.id, route, destinations)

    builder = StateGraph(WorkflowStateV1)
    for node in sorted(normalized.nodes, key=lambda item: item.id):
        if node.id not in parallel_ids:
            add_node(builder, node)
    for fanout_id, branches in regions.items():
        fanout = nodes[fanout_id]
        join_id = str(fanout.config["join_id"])
        for child, region in sorted(branches.items()):
            child_builder = StateGraph(WorkflowStateV1, output_schema=BranchOutput)
            for node_id in sorted(region):
                add_node(child_builder, nodes[node_id])
                wire(child_builder, nodes[node_id], join_id)

            def complete(state: WorkflowStateV1) -> WorkflowStateV1:
                identity = state["child_identity"]
                values = {
                    key: value
                    for key, value in state.get("results", {}).items()
                    if key.startswith(f"{identity}:")
                }
                return {"child_results": {identity: values}, "completed_children": [identity]}

            child_builder.add_node("__complete__", complete)
            child_builder.add_edge(START, child)
            child_builder.add_edge("__complete__", END)
            child_graph = child_builder.compile(name=f"{fanout_id}_{child}").with_config(
                {"recursion_limit": superstep_limit}
            )
            builder.add_node(child, child_graph)
        # Each Send runs one complete native subgraph. The barrier waits for every
        # expected child even when branches have different numbers of supersteps.
        builder.add_edge(sorted(branches), join_id)

    for node in sorted(normalized.nodes, key=lambda item: item.id):
        if node.id in parallel_ids:
            continue
        if node.type is WorkflowNodeType.FANOUT:

            def fanout_route(state: WorkflowStateV1, fanout: WorkflowNode = node) -> list[Send]:
                visit = state.get("counters", {}).get(invocation_key(state, fanout.id), 0)
                children = cast(list[str], fanout.config["children"])
                if not children or len(children) > cast(int, fanout.config["max_fanout"]):
                    raise WorkflowInvariantError("Fanout exceeded its snapshotted child bound")
                return [
                    Send(
                        child,
                        {**deepcopy(state), "child_identity": child_id(fanout.id, visit, child)},
                    )
                    for child in children
                ]

            builder.add_conditional_edges(node.id, fanout_route, list(regions[node.id]))
        else:
            wire(builder, node)
    builder.add_edge(START, normalized.entrypoint)
    graph = builder.compile(
        checkpointer=checkpointer,
        interrupt_before=interrupt_before,
        name=f"workflow_{identity}",
    ).with_config({"recursion_limit": superstep_limit})
    if cache is not None:
        cache._put(cache_key, _CacheEntry(graph, checkpointer, handler_bindings))
    return graph
