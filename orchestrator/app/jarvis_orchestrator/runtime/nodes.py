"""Checkpoint control boundaries and durable node lifecycle observations."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import cast

from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt
from pydantic import JsonValue
from sqlalchemy import func, select
from uuid6 import uuid7

from jarvis_api.events.redaction import RecursiveRedactor
from jarvis_api.routing.policies import evaluate_retry
from jarvis_contracts.base import canonical_json
from jarvis_contracts.enums import FailureClass
from jarvis_contracts.failures import FailureEvidence, RetryPolicySpec, classify_failure
from jarvis_contracts.registry import RetryRegistrySpec
from jarvis_orchestrator.runtime.effects import AmbiguousEffectError, CooperativeCancelError
from jarvis_orchestrator.runtime.ownership import RunFence, RunOwnership, StaleExecutorError
from jarvis_orchestrator.workflows.factories import (
    MissingWorkflowHandlerError,
    NodeCallable,
    NodeContext,
    invocation_key,
)
from jarvis_orchestrator.workflows.state import WorkflowStateV1
from jarvis_persistence.models import (
    EffectModel,
    FailureModel,
    NodeExecutionModel,
    RetryCounterModel,
    TaskAttemptModel,
    TaskModel,
)


class RuntimeBlockedError(RuntimeError):
    """An unknown/configuration/security outcome must stop graph execution."""


class ClassifiedNodeError(RuntimeError):
    def __init__(self, failure: FailureClass) -> None:
        super().__init__(failure.value)
        self.failure = failure


def safe_result(value: WorkflowStateV1) -> WorkflowStateV1:
    if len(canonical_json(value)) > 32_768:
        raise RuntimeBlockedError("Node result exceeds the inline checkpoint bound")
    result = RecursiveRedactor().redact(cast(JsonValue, value))
    return cast(WorkflowStateV1, result.value)


class NodeRuntime:
    def __init__(self, ownership: RunOwnership, fence: RunFence) -> None:
        self.ownership = ownership
        self.fence = fence

    def wrap(self, context: NodeContext, execute: NodeCallable) -> NodeCallable:
        async def invoke(state: WorkflowStateV1, config: RunnableConfig) -> WorkflowStateV1:
            visit = state.get("counters", {}).get(invocation_key(state, context.node.id), 0) + 1
            key = f"{state.get('child_identity', 'main')}:{context.node.id}:{visit}"
            wait: dict[str, JsonValue] | None = None
            async with self.ownership.fenced(self.fence) as (session, run):
                if run.desired_state == "cancelled":
                    return {"cancelled": True, "final": {"status": "cancelled"}}
                if run.runtime_json.get("wait"):
                    wait = run.runtime_json["wait"]
                elif run.desired_state == "paused" or run.claimable_at > self.ownership.clock.now():
                    wait = {
                        "kind": "pause" if run.desired_state == "paused" else "backoff",
                        "id": str(uuid7()),
                    }
                    run.runtime_json = {**run.runtime_json, "wait": wait}
                row = await session.scalar(
                    select(NodeExecutionModel).where(
                        NodeExecutionModel.run_id == run.id,
                        NodeExecutionModel.workflow_node_id == context.node.id,
                        NodeExecutionModel.input_summary == key,
                    )
                )
                if row is None:
                    task_key = state.get("tasks", {}).get("current_task")
                    task_id = (
                        await session.scalar(
                            select(TaskModel.id).where(
                                TaskModel.run_id == run.id, TaskModel.key == task_key
                            )
                        )
                        if isinstance(task_key, str)
                        else None
                    )
                    attempt_id = (
                        await session.scalar(
                            select(TaskAttemptModel.id)
                            .where(
                                TaskAttemptModel.task_id == task_id,
                                TaskAttemptModel.status.in_(("running", "verifying", "reviewing")),
                            )
                            .order_by(TaskAttemptModel.attempt_number.desc())
                            .limit(1)
                        )
                        if task_id
                        else None
                    )
                    row = NodeExecutionModel(
                        id=uuid7(),
                        run_id=run.id,
                        workflow_node_id=context.node.id,
                        execution_number=(
                            await session.scalar(
                                select(func.max(NodeExecutionModel.execution_number)).where(
                                    NodeExecutionModel.run_id == run.id,
                                    NodeExecutionModel.workflow_node_id == context.node.id,
                                )
                            )
                            or 0
                        )
                        + 1,
                        input_summary=key,
                        task_id=task_id,
                        task_attempt_id=attempt_id,
                        status="queued",
                    )
                    session.add(row)
                    await session.flush()
                    await self.ownership.event(
                        session,
                        run,
                        "node.queued",
                        {"node_execution_id": str(row.id), "workflow_node_id": context.node.id},
                    )
                node_id = row.id
                cached = row.result_json
                if wait is not None and row.status != "waiting":
                    row.status = "waiting"
                    await self.ownership.event(
                        session,
                        run,
                        "node.waiting",
                        {
                            "node_execution_id": str(row.id),
                            "reason": wait["kind"],
                        },
                    )
            if wait is not None:
                self.ownership.fault("during_pause")
                value = interrupt(wait)
                if not isinstance(value, dict) or value.get("id") != wait["id"]:
                    raise RuntimeBlockedError("Control resume does not match durable wait")
                async with self.ownership.fenced(self.fence) as (_session, run):
                    run.runtime_json = {**run.runtime_json, "wait": None}
                    if run.desired_state == "cancelled":
                        return {"cancelled": True, "final": {"status": "cancelled"}}
            if cached is not None:
                failure = cached.get("outcome", {}).get("failure_class")
                if failure == FailureClass.UNKNOWN.value:
                    raise RuntimeBlockedError("Unknown node outcome")
                if (
                    failure
                    and not classify_failure(
                        FailureEvidence(
                            explicit_class=FailureClass(failure), summary="Cached node failure"
                        )
                    ).retryable
                ):
                    raise RuntimeBlockedError("Non-transient node failure")
                return cast(WorkflowStateV1, cached)
            async with self.ownership.fenced(self.fence) as (session, run):
                row = await session.get(NodeExecutionModel, node_id)
                assert row is not None
                row.status = "running"
                row.started_at = row.started_at or self.ownership.clock.now()
                run.current_node = context.node.id
                await self.ownership.event(
                    session,
                    run,
                    "node.started",
                    {"node_execution_id": str(node_id), "workflow_node_id": context.node.id},
                )
            try:
                update = safe_result(await execute(state, config))
            except StaleExecutorError:
                raise
            except CooperativeCancelError:
                update = {"cancelled": True, "final": {"status": "cancelled"}}
            except Exception as error:
                logging.getLogger(__name__).warning("Node exception type=%s", type(error).__name__)
                explicit = error.failure if isinstance(error, ClassifiedNodeError) else None
                if isinstance(error, MissingWorkflowHandlerError):
                    explicit = FailureClass.CONFIGURATION_INVALID
                classified = classify_failure(
                    FailureEvidence(explicit_class=explicit, summary="Node execution failed")
                )
                async with self.ownership.fenced(self.fence) as (session, run):
                    session.add(
                        FailureModel(
                            run_id=run.id,
                            node_execution_id=node_id,
                            failure_class=classified.failure_class.value,
                            code=classified.code,
                            retryable=classified.retryable,
                            budget_scope=classified.budget_scope,
                            consumes_semantic_attempt=classified.consumes_semantic_attempt,
                            summary=classified.summary,
                        )
                    )
                    await self.ownership.event(
                        session,
                        run,
                        "failure.classified",
                        classified.model_dump(mode="json", by_alias=True),
                    )
                if (
                    explicit is None
                    or explicit is FailureClass.UNKNOWN
                    or not classified.retryable
                    or isinstance(error, AmbiguousEffectError)
                ):
                    raise RuntimeBlockedError(
                        "Node requires configuration or outcome reconciliation"
                    ) from None
                update = {
                    "outcome": {
                        "status": "failed",
                        "failure_class": classified.failure_class.value,
                    },
                    "counters": {invocation_key(state, context.node.id): visit},
                }
            async with self.ownership.fenced(self.fence) as (session, run):
                row = await session.get(NodeExecutionModel, node_id)
                assert row is not None
                if run.desired_state == "cancelled":
                    update = {"cancelled": True, "final": {"status": "cancelled"}}
                reported = update.get("outcome", {}).get("failure_class")
                if reported and not await session.scalar(
                    select(FailureModel.id).where(FailureModel.node_execution_id == node_id)
                ):
                    classification = classify_failure(
                        FailureEvidence(
                            explicit_class=FailureClass(str(reported)),
                            summary="Adapter reported a classified failure",
                        )
                    )
                    session.add(
                        FailureModel(
                            run_id=run.id,
                            node_execution_id=node_id,
                            failure_class=classification.failure_class.value,
                            code=classification.code,
                            retryable=classification.retryable,
                            budget_scope=classification.budget_scope,
                            consumes_semantic_attempt=classification.consumes_semantic_attempt,
                            summary=classification.summary,
                        )
                    )
                    await self.ownership.event(
                        session,
                        run,
                        "failure.classified",
                        classification.model_dump(mode="json", by_alias=True),
                    )
                row.status = (
                    "cancelled"
                    if update.get("cancelled")
                    else "failed"
                    if update.get("outcome", {}).get("failure_class")
                    else "succeeded"
                )
                row.result_json = dict(update)
                row.completed_at = self.ownership.clock.now()
                await self.ownership.event(
                    session,
                    run,
                    f"node.{row.status}",
                    {
                        "node_execution_id": str(node_id),
                        "workflow_node_id": context.node.id,
                        "execution_key": key,
                    },
                )
            if (
                reported
                and not classify_failure(
                    FailureEvidence(
                        explicit_class=FailureClass(str(reported)), summary="Node failure"
                    )
                ).retryable
            ):
                raise RuntimeBlockedError("Non-transient node failure")
            if reported == FailureClass.UNKNOWN.value:
                raise RuntimeBlockedError("Unknown node outcome")
            return update

        return invoke

    async def route(
        self, context: NodeContext, state: WorkflowStateV1, update: WorkflowStateV1
    ) -> None:
        async with self.ownership.fenced(self.fence) as (session, run):
            visit = state.get("counters", {}).get(invocation_key(state, context.node.id), 0) + 1
            key = f"route:{state.get('child_identity', 'main')}:{context.node.id}:{visit}"
            applied = list(run.runtime_json.get("routes", []))
            if key in applied:
                return
            # Bound cumulative metadata; execution counters/checkpoints retain history.
            run.runtime_json = {**run.runtime_json, "routes": [*applied[-999:], key]}
            reported = update.get("outcome", {}).get("failure_class")
            retry_policy = next(
                (
                    rev.spec
                    for rev in context.snapshot.revisions
                    if rev.revision_id == context.policy.retry_policy_ref
                ),
                None,
            )
            if reported and isinstance(retry_policy, RetryRegistrySpec):
                rule = next(
                    (rule for rule in retry_policy.rules if rule.failure_class.value == reported),
                    None,
                )
                retry_key = f"retry:{context.node.id}:{reported}"
                if (
                    rule is not None
                    and state.get("counters", {}).get(retry_key, 0) >= rule.max_retries
                ):
                    await self.ownership.event(
                        session,
                        run,
                        "retry.budget_exhausted",
                        {
                            "failure_class": str(reported),
                            "max_retries": rule.max_retries,
                            "exhaustion_action": rule.exhaustion_action,
                        },
                    )
                    update["outcome"] = {
                        **update.get("outcome", {}),
                        "status": "failed" if rule.exhaustion_action == "fail" else "blocked",
                    }
            if update.get("_route"):
                await self.ownership.event(
                    session,
                    run,
                    "graph.route_selected",
                    {"from": context.node.id, "to": update["_route"]},
                )
            for counter_key, count in update.get("counters", {}).items():
                if not counter_key.startswith("retry:") or count <= state.get("counters", {}).get(
                    counter_key, 0
                ):
                    continue
                failure = FailureClass(counter_key.split(":", 2)[2])
                policy = next(
                    (
                        rev.spec
                        for rev in context.snapshot.revisions
                        if rev.revision_id == context.policy.retry_policy_ref
                    ),
                    None,
                )
                if not isinstance(policy, RetryRegistrySpec):
                    raise RuntimeBlockedError("Missing immutable retry policy")
                decision = evaluate_retry(
                    RetryPolicySpec(rules=policy.rules),
                    failure,
                    {failure: count - 1},
                    jitter_key=str(run.id),
                )
                if not decision.retry:
                    raise RuntimeBlockedError("Compiler and retry policy disagree")
                counter = await session.scalar(
                    select(RetryCounterModel).where(
                        RetryCounterModel.run_id == run.id,
                        RetryCounterModel.scope_key == context.node.id,
                        RetryCounterModel.failure_class == failure.value,
                    )
                )
                maximum = next(
                    rule.max_retries for rule in policy.rules if rule.failure_class == failure
                )
                if counter is None:
                    counter = RetryCounterModel(
                        run_id=run.id,
                        scope_key=context.node.id,
                        failure_class=failure.value,
                        consumed=count,
                        maximum=maximum,
                    )
                    session.add(counter)
                counter.consumed = count
                if decision.allow_failover and context.policy.model_route_ref is not None:
                    effect = await session.scalar(
                        select(EffectModel).where(
                            EffectModel.run_id == run.id,
                            EffectModel.idempotency_key
                            == f"{state.get('child_identity', 'main')}:{context.node.id}:{visit}",
                        )
                    )
                    if effect is not None and effect.request_json.get("model_profile_revision_id"):
                        failures = dict(run.runtime_json.get("model_failures", {}))
                        previous = failures.get(context.node.id, {}).get("profiles", [])
                        failures[context.node.id] = {
                            "profiles": sorted(
                                set([*previous, effect.request_json["model_profile_revision_id"]])
                            ),
                            "failure_class": failure.value,
                        }
                        run.runtime_json = {**run.runtime_json, "model_failures": failures}
                        await self.ownership.event(
                            session,
                            run,
                            "model.failover",
                            {"failure_class": failure.value, "workflow_node_id": context.node.id},
                        )
                run.claimable_at = self.ownership.clock.now() + timedelta(
                    milliseconds=decision.delay_ms
                )
                run.runtime_json = {**run.runtime_json, "retry_at": run.claimable_at.isoformat()}
                self.ownership.fault("during_retry_scheduling")
                await self.ownership.event(
                    session,
                    run,
                    "retry.budget_consumed",
                    {
                        "failure_class": failure.value,
                        "used_retries": count,
                        "max_retries": maximum,
                        "delay_ms": decision.delay_ms,
                    },
                )
