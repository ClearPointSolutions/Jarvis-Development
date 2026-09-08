"""M5 effect bridge: graph sees generic results, never SSH/OpenHands details."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import NAMESPACE_URL, uuid5

from langchain_core.runnables import RunnableConfig
from pydantic import JsonValue
from sqlalchemy import select

from jarvis_api.events.redaction import RecursiveRedactor
from jarvis_contracts.base import sha256_digest
from jarvis_contracts.enums import FailureClass
from jarvis_contracts.registry import WorkerSpec
from jarvis_contracts.workers import (
    PreparedInvocation,
    WorkerInvocationHandle,
    WorkerInvocationRequest,
    WorkerResult,
)
from jarvis_orchestrator.runtime.effects import EffectObservation
from jarvis_orchestrator.runtime.nodes import ClassifiedNodeError
from jarvis_orchestrator.runtime.ownership import RunFence, RunOwnership, StaleExecutorError
from jarvis_orchestrator.workers.base import WorkerAdapter, WorkerCallContext
from jarvis_orchestrator.workers.leases import WorkerSlots
from jarvis_orchestrator.workers.safety import WorkerBoundaryError, validation_failure
from jarvis_orchestrator.workflows.factories import NodeContext
from jarvis_orchestrator.workflows.state import WorkflowStateV1
from jarvis_persistence.models import (
    EffectModel,
    TaskAttemptModel,
    WorkerHealthModel,
    WorkerInvocationModel,
)

RequestSource = Callable[
    [WorkflowStateV1, NodeContext, RunnableConfig], Awaitable[WorkerInvocationRequest]
]


class WorkerEffectAdapter:
    idempotent = True

    def __init__(
        self,
        ownership: RunOwnership,
        fence: RunFence,
        worker: WorkerSpec,
        adapter: WorkerAdapter,
        request_source: RequestSource,
    ) -> None:
        self.ownership = ownership
        self.fence = fence
        self.worker = worker
        self.adapter = adapter
        self.request_source = request_source
        self.slots = WorkerSlots(ownership, fence)

    def context(self) -> WorkerCallContext:
        return WorkerCallContext(
            datetime.now(UTC) + timedelta(seconds=self.worker.timeouts.run_seconds),
            self.fence.run_id,
        )

    async def load(self, identity: str) -> PreparedInvocation | None:
        async with self.ownership.fenced(self.fence) as (session, _run):
            row = await session.get(WorkerInvocationModel, uuid5(NAMESPACE_URL, identity))
            if row is None:
                return None
            return PreparedInvocation(
                request=WorkerInvocationRequest.model_validate(row.request_json),
                request_digest=row.request_digest,
            )

    @staticmethod
    def handle(prepared: PreparedInvocation) -> WorkerInvocationHandle:
        return WorkerInvocationHandle(
            invocation_id=prepared.request.invocation_id,
            worker_revision_id=prepared.request.worker_revision_id,
            request_digest=prepared.request_digest,
            generation=prepared.request.lease.generation,
        )

    async def dispatch(
        self, identity: str, state: WorkflowStateV1, context: NodeContext, config: RunnableConfig
    ) -> None:
        prepared = await self.load(identity)
        try:
            if prepared is None:
                request = await self.request_source(state, context, config)
                if request.run_id != self.fence.run_id:
                    raise WorkerBoundaryError("invocation_run_mismatch")
                selector = context.policy.worker_selector
                if selector is None or selector.revision_id != request.worker_revision_id:
                    raise WorkerBoundaryError("invocation_worker_mismatch")
                selected_profile = config.get("configurable", {}).get(
                    "runtime_model_profile_revision_id"
                )
                if selected_profile is not None and str(request.model_profile_revision_id) != str(
                    selected_profile
                ):
                    raise WorkerBoundaryError("incompatible_model_binding")
                public = request.model_dump(mode="json")
                if RecursiveRedactor().redact(public).value != public:
                    raise WorkerBoundaryError("credential_in_worker_request")
                lease = await self.slots.acquire(
                    request.worker_revision_id, request.task_attempt_id, self.worker
                )
                request = request.model_copy(
                    update={
                        "invocation_id": uuid5(NAMESPACE_URL, identity),
                        "idempotency_key": identity,
                        "lease": lease,
                    }
                )
                public = request.model_dump(mode="json")
                prepared = PreparedInvocation(
                    request=request, request_digest=sha256_digest(request)
                )
                async with self.ownership.fenced(self.fence) as (session, run):
                    effect = await session.scalar(
                        select(EffectModel).where(
                            EffectModel.run_id == run.id, EffectModel.external_id == identity
                        )
                    )
                    if effect is None:
                        raise WorkerBoundaryError("worker_effect_missing")
                    effect.task_attempt_id = request.task_attempt_id
                    session.add(
                        WorkerInvocationModel(
                            id=request.invocation_id,
                            effect_id=effect.id,
                            lease_id=lease.lease_id,
                            generation=lease.generation,
                            request_digest=prepared.request_digest,
                            request_json=public,
                        )
                    )
            report = await self.adapter.validate(self.worker, self.context())
            async with self.ownership.fenced(self.fence) as (session, run):
                health = await session.get(WorkerHealthModel, prepared.request.worker_revision_id)
                if health is None:
                    session.add(
                        WorkerHealthModel(
                            revision_id=prepared.request.worker_revision_id,
                            report_json=report.model_dump(mode="json"),
                            observed_at=self.ownership.clock.now(),
                        )
                    )
                else:
                    health.report_json = report.model_dump(mode="json")
                    health.observed_at = self.ownership.clock.now()
                await self.ownership.event(
                    session,
                    run,
                    "worker.health_changed",
                    {
                        "worker_revision_id": str(prepared.request.worker_revision_id),
                        "health": report.health.status,
                    },
                )
            if not report.valid:
                raise validation_failure(report)
            await self.adapter.prepare(prepared.request, prepared.request.lease, self.context())
            await self.adapter.start(prepared, self.context())
            async with self.ownership.fenced(self.fence) as (session, run):
                await self.slots.require(session, prepared.request.lease)
                await self.ownership.event(
                    session,
                    run,
                    "worker.invocation_dispatched",
                    {
                        "invocation_id": str(prepared.request.invocation_id),
                        "generation": prepared.request.lease.generation,
                    },
                )
        except WorkerBoundaryError as error:
            raise ClassifiedNodeError(error.failure_class) from None

    async def inspect(self, identity: str) -> EffectObservation:
        prepared = await self.load(identity)
        if prepared is None:
            return EffectObservation("absent")
        # Generic implementations recover from the durable prepared request.
        restore = getattr(self.adapter, "restore", None)
        if restore is not None:
            restore(prepared)
        handle = self.handle(prepared)
        async with self.ownership.fenced(self.fence) as (session, _run):
            row = await session.get(WorkerInvocationModel, handle.invocation_id)
            assert row is not None
            if row.result_json is not None:
                if row.cancellation_requested_at is not None:
                    return EffectObservation("cancelled")
                return EffectObservation(
                    "succeeded", self.output(WorkerResult.model_validate(row.result_json), identity)
                )
        observation = await self.adapter.reconcile(handle, self.context())
        if observation.state in {"absent", "unknown", "cancelled"}:
            if observation.state == "cancelled":
                async with self.ownership.fenced(self.fence) as (session, run):
                    await self.ownership.event(
                        session,
                        run,
                        "worker.cancelled",
                        {"invocation_id": str(handle.invocation_id)},
                    )
                await self.slots.release(prepared.request.lease, reconciled_terminal=True)
            return EffectObservation(observation.state)
        if observation.state in {"starting", "running"}:
            status = await self.adapter.inspect(handle, self.context())
            async with self.ownership.fenced(self.fence) as (session, run):
                row = await session.get(WorkerInvocationModel, handle.invocation_id)
                assert row is not None
                if row.last_activity_at is None or (
                    status.last_activity_at
                    and (status.last_activity_at - row.last_activity_at).total_seconds()
                    >= self.worker.timeouts.heartbeat_seconds
                ):
                    row.last_activity_at = status.last_activity_at
                    await self.ownership.event(
                        session,
                        run,
                        "worker.heartbeat",
                        {
                            "invocation_id": str(handle.invocation_id),
                            "source_sequence": status.source_sequence,
                        },
                    )
                row.possibly_stalled = status.possibly_stalled
            await self.slots.renew(prepared.request.lease)
            return EffectObservation("running")
        try:
            result = await self.adapter.collect(handle, self.context())
        except WorkerBoundaryError as error:
            async with self.ownership.fenced(self.fence) as (session, _run):
                await self.slots.require(session, prepared.request.lease)
            # Reconciliation already proved terminal; malformed results remain failures.
            await self.slots.release(prepared.request.lease, reconciled_terminal=True)
            return EffectObservation(
                "succeeded",
                {"outcome": {"status": "failed", "failure_class": error.failure_class.value}},
            )
        stale = False
        cancelled = False
        async with self.ownership.fenced(self.fence) as (session, run):
            row = await session.get(WorkerInvocationModel, handle.invocation_id)
            assert row is not None
            try:
                await self.slots.require(session, prepared.request.lease)
            except StaleExecutorError:
                stale = True
            cancelled = (
                row.cancellation_requested_at is not None or run.desired_state == "cancelled"
            )
            if stale or cancelled:
                row.diagnostic_result_json = cast(
                    dict[str, JsonValue],
                    RecursiveRedactor().redact(result.model_dump(mode="json")).value,
                )
                await self.ownership.event(
                    session,
                    run,
                    "worker.lease_lost" if stale else "worker.cancelled",
                    {"invocation_id": str(handle.invocation_id), "generation": handle.generation},
                )
            else:
                if (
                    result.invocation_id != handle.invocation_id
                    or result.generation != handle.generation
                    or result.request_digest != prepared.request_digest
                    or result.task_attempt_id != prepared.request.task_attempt_id
                    or result.task_id != prepared.request.task_id
                    or result.model_profile_revision_id
                    != prepared.request.model_profile_revision_id
                    or result.workspace_root != prepared.request.project.workspace_root
                    or result.branch != prepared.request.project.branch
                    or result.start_head != prepared.request.project.base_sha
                ):
                    raise WorkerBoundaryError("result_identity_mismatch")
                row.result_json = result.model_dump(mode="json")
                attempt = await session.get(TaskAttemptModel, result.task_attempt_id)
                assert attempt is not None
                attempt.result_sha = result.end_head
                attempt.status = "verifying" if result.status == "succeeded" else "failed"
                await self.ownership.event(
                    session,
                    run,
                    "worker.invocation_completed"
                    if result.status == "succeeded"
                    else "worker.invocation_failed",
                    {
                        "invocation_id": str(result.invocation_id),
                        "task_attempt_id": str(result.task_attempt_id),
                        "generation": result.generation,
                    },
                )
        if stale:
            raise ClassifiedNodeError(FailureClass.SECURITY_POLICY_DENIED)
        await self.slots.release(prepared.request.lease, reconciled_terminal=True)
        if cancelled:
            return EffectObservation("cancelled")
        return EffectObservation("succeeded", self.output(result, identity))

    @staticmethod
    def output(result: WorkerResult, identity: str) -> WorkflowStateV1:
        outcome: dict[str, JsonValue] = {
            "status": "succeeded" if result.status == "succeeded" else "failed"
        }
        if result.status != "succeeded":
            outcome["failure_class"] = FailureClass.CODE_IMPLEMENTATION_FAILURE.value
        return {
            "outcome": outcome,
            "results": {
                identity.split(":", 1)[1]: cast(
                    JsonValue,
                    {
                        "invocation_id": str(result.invocation_id),
                        "task_attempt_id": str(result.task_attempt_id),
                        "end_head": result.end_head,
                        "generation": result.generation,
                    },
                )
            },
        }

    async def cancel(self, identity: str) -> None:
        prepared = await self.load(identity)
        if prepared is None:
            return
        async with self.ownership.fenced(self.fence) as (session, run):
            row = await session.get(WorkerInvocationModel, prepared.request.invocation_id)
            assert row is not None
            if row.cancellation_requested_at is None:
                row.cancellation_requested_at = self.ownership.clock.now()
                await self.ownership.event(
                    session, run, "worker.cancel_requested", {"invocation_id": str(row.id)}
                )
        restore = getattr(self.adapter, "restore", None)
        if restore is not None:
            restore(prepared)
        await self.adapter.cancel(self.handle(prepared), "run cancellation", self.context())
