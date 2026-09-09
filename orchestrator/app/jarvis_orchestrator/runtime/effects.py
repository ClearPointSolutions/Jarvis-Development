"""Prepare/reconcile/dispatch/commit protocol for external node adapters."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol, cast
from uuid import UUID

from langchain_core.runnables import RunnableConfig
from pydantic import JsonValue
from sqlalchemy import select

from jarvis_api.events.redaction import RecursiveRedactor
from jarvis_contracts.base import canonical_json, sha256_digest
from jarvis_contracts.enums import FailureClass
from jarvis_contracts.workflow_nodes import NODE_DEFINITIONS
from jarvis_orchestrator.runtime.model_selection import select_model
from jarvis_orchestrator.runtime.ownership import RunFence, RunOwnership
from jarvis_orchestrator.workflows.factories import NodeContext, NodeHandler
from jarvis_orchestrator.workflows.state import WorkflowStateV1
from jarvis_persistence.models import EffectModel, NodeExecutionModel
from jarvis_persistence.repositories import EffectRepository


class AmbiguousEffectError(RuntimeError):
    """An adapter cannot prove whether a non-idempotent operation happened."""


class CooperativeCancelError(RuntimeError):
    """The controlled adapter acknowledged cancellation."""


@dataclass(frozen=True)
class EffectObservation:
    status: Literal["absent", "running", "succeeded", "cancelled", "unknown"]
    result: WorkflowStateV1 | None = None


class EffectAdapter(Protocol):
    idempotent: bool

    async def inspect(self, identity: str) -> EffectObservation: ...
    async def dispatch(
        self,
        identity: str,
        state: WorkflowStateV1,
        context: NodeContext,
        config: RunnableConfig,
    ) -> None: ...
    async def cancel(self, identity: str) -> None: ...


class EffectLedger:
    def __init__(
        self, ownership: RunOwnership, fence: RunFence, *, poll_seconds: float = 0.05
    ) -> None:
        self.ownership = ownership
        self.fence = fence
        self.poll_seconds = poll_seconds

    async def cancel_pending(self, adapters: Mapping[str, EffectAdapter]) -> None:
        async with self.ownership.fenced(self.fence) as (session, _run):
            pending = (
                await session.scalars(
                    select(EffectModel).where(
                        EffectModel.run_id == self.fence.run_id,
                        EffectModel.status.in_(
                            ("prepared", "dispatched", "running", "cancel_requested")
                        ),
                    )
                )
            ).all()
        for effect in pending:
            if effect.external_id is None:
                await self._record(effect.id, "cancelled")
                continue
            adapter = adapters.get(str(effect.request_json.get("node")))
            if adapter is None:
                raise AmbiguousEffectError("Cancellation requires the original adapter")
            while True:
                await self._record(effect.id, "cancel_requested")
                await adapter.cancel(effect.external_id)
                observation = await adapter.inspect(effect.external_id)
                if observation.status in {"succeeded", "cancelled", "absent"}:
                    await self._record(effect.id, "cancelled")
                    break
                if observation.status == "unknown":
                    await self._record(effect.id, "unknown")
                    raise AmbiguousEffectError("Cancellation outcome requires reconciliation")
                await asyncio.sleep(self.poll_seconds)

    def handler(self, adapter: EffectAdapter) -> NodeHandler:
        async def execute(
            state: WorkflowStateV1,
            context: NodeContext,
            config: RunnableConfig,
        ) -> WorkflowStateV1:
            identity = f"{self.fence.run_id}:{context.execution_id}"
            self.ownership.fault("before_effect_prepare")
            async with self.ownership.fenced(self.fence) as (session, run):
                effect, fresh = await EffectRepository().prepare(
                    session,
                    run_id=self.fence.run_id,
                    kind=context.node.type.value,
                    idempotency_key=context.execution_id,
                    request_digest=sha256_digest(
                        {"node": context.node.model_dump(mode="json"), "state": state}
                    ),
                    request={"node": context.node.id},
                    fence_generation=self.fence.generation,
                )
                effect_id = effect.id
                if fresh:
                    effect.node_execution_id = await session.scalar(
                        select(NodeExecutionModel.id).where(
                            NodeExecutionModel.run_id == run.id,
                            NodeExecutionModel.input_summary == context.execution_id,
                        )
                    )
                    instructions = (
                        list(run.runtime_json.get("instructions", []))
                        if context.policy.accepts_runtime_instructions
                        and context.node.type.value in {"organizer", "architect", "worker"}
                        else []
                    )
                    effect.request_json = {"node": context.node.id, "instructions": instructions}
                    if context.policy.model_route_ref is not None:
                        failed = run.runtime_json.get("model_failures", {}).get(context.node.id, {})
                        resolution = select_model(
                            context,
                            tuple(UUID(value) for value in failed.get("profiles", [])),
                            FailureClass(failed["failure_class"]) if failed else None,
                            self.ownership.clock.now(),
                        )
                        if resolution.decision != "allow":
                            raise AmbiguousEffectError(
                                "Immutable model route has no permitted candidate"
                            )
                        effect.request_json = {
                            **effect.request_json,
                            "model_profile_revision_id": str(
                                resolution.selected_profile_revision_id
                            ),
                            "provider_revision_id": str(resolution.selected_provider_revision_id),
                        }
                        await self.ownership.event(
                            session, run, "model.route_selected", resolution.model_dump(mode="json")
                        )
                    if instructions:
                        run.runtime_json = {**run.runtime_json, "instructions": []}
                        await self.ownership.event(
                            session,
                            run,
                            "instruction.applied",
                            {
                                "node_execution_id": str(effect.node_execution_id),
                                "count": len(instructions),
                                "command_ids": [item["command_id"] for item in instructions],
                            },
                        )
                    await self.ownership.event(
                        session,
                        run,
                        "effect.prepared",
                        {
                            "effect_id": str(effect.id),
                            "instruction_count": len(instructions),
                        },
                    )
                config = {
                    **config,
                    "configurable": {
                        **config.get("configurable", {}),
                        "runtime_instructions": effect.request_json.get("instructions", []),
                        "runtime_model_profile_revision_id": effect.request_json.get(
                            "model_profile_revision_id"
                        ),
                        "runtime_provider_revision_id": effect.request_json.get(
                            "provider_revision_id"
                        ),
                    },
                }
                if effect.status == "succeeded":
                    return cast(WorkflowStateV1, effect.result_json)
                if effect.status == "cancelled":
                    raise CooperativeCancelError()
                dispatched = effect.status != "prepared"
                effect.fence_generation = self.fence.generation
            self.ownership.fault("after_prepare_before_dispatch")
            observed = await adapter.inspect(identity)
            if observed.status == "unknown" or (
                observed.status == "absent" and dispatched and not adapter.idempotent
            ):
                await self._record(effect_id, "unknown")
                raise AmbiguousEffectError("External outcome requires reconciliation")
            if observed.status == "absent":
                # Persist dispatch intent first: a crash here is conservatively
                # ambiguous for non-idempotent adapters without an absence proof.
                await self._record(effect_id, "dispatched", identity=identity)
                await adapter.dispatch(identity, state, context, config)
                self.ownership.fault("after_dispatch_before_result")
            while True:
                async with self.ownership.fenced(self.fence) as (session, run):
                    current_effect = await session.get(EffectModel, effect_id)
                    assert current_effect is not None
                    cancel = run.desired_state == "cancelled"
                    if cancel and current_effect.status != "cancel_requested":
                        current_effect.status = "cancel_requested"
                if cancel:
                    self.ownership.fault("during_cancellation")
                    # Adapter cancellation itself must be idempotent by identity.
                    await adapter.cancel(identity)
                observed = await adapter.inspect(identity)
                if observed.status == "succeeded":
                    if cancel:
                        await self._record(effect_id, "cancelled")
                        raise CooperativeCancelError()
                    if observed.result is None:
                        raise AmbiguousEffectError("Successful effect has no validated result")
                    allowed = set(NODE_DEFINITIONS[context.node.type].outputs) | {"node", "outcome"}
                    if (
                        set(observed.result) - allowed
                        or len(canonical_json(observed.result)) > 32_768
                    ):
                        raise AmbiguousEffectError(
                            "Adapter returned an invalid or oversized result"
                        )
                    safe = cast(
                        WorkflowStateV1,
                        RecursiveRedactor().redact(cast(JsonValue, observed.result)).value,
                    )
                    await self._record(effect_id, "succeeded", result=safe)
                    self.ownership.fault("after_result_before_checkpoint")
                    return safe
                if observed.status == "cancelled":
                    await self._record(effect_id, "cancelled")
                    raise CooperativeCancelError()
                if observed.status in {"unknown", "absent"}:
                    await self._record(effect_id, "unknown")
                    raise AmbiguousEffectError("Dispatched effect cannot be reconciled")
                await asyncio.sleep(self.poll_seconds)

        return execute

    async def _record(
        self,
        effect_id: UUID,
        status: str,
        *,
        identity: str | None = None,
        result: WorkflowStateV1 | None = None,
    ) -> None:
        cancelled = False
        async with self.ownership.fenced(self.fence) as (session, run):
            effect = await session.scalar(select(EffectModel).where(EffectModel.id == effect_id))
            assert effect is not None
            if status in {"succeeded", "dispatched"} and run.desired_state == "cancelled":
                status, result, cancelled = "cancelled", None, True
            effect.status = status
            if identity is not None:
                effect.external_id = identity
                effect.dispatched_at = self.ownership.clock.now()
            if result is not None:
                effect.result_json = dict(result)
            if status in {"succeeded", "cancelled", "unknown"}:
                effect.completed_at = self.ownership.clock.now()
            await self.ownership.event(
                session,
                run,
                f"effect.{status}",
                {
                    "effect_id": str(effect.id),
                    "generation": self.fence.generation,
                },
            )
        if cancelled:
            raise CooperativeCancelError()
