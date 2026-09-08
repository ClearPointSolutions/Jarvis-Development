from __future__ import annotations

from datetime import timedelta

import pytest
from langchain_core.runnables import RunnableConfig
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from jarvis_orchestrator.runtime.effects import EffectObservation
from jarvis_orchestrator.runtime.service import OrchestratorService
from jarvis_orchestrator.workflows.factories import NodeContext
from jarvis_orchestrator.workflows.state import WorkflowStateV1
from jarvis_persistence.models import EffectModel, RunLeaseModel, RunModel
from tests.integration.test_m5_runtime import acquire, prepare_run
from tests.unit.test_m4_workflows_compiler import (
    edge,
    external_defaults,
    node,
    snapshot_for,
    spec_for,
)

pytestmark = pytest.mark.integration


class InjectedCrash(BaseException):
    pass


class DeterministicAdapter:
    idempotent = True

    def __init__(self) -> None:
        self.results: dict[str, WorkflowStateV1] = {}
        self.dispatches = 0
        self.cancellations: set[str] = set()

    async def inspect(self, identity: str) -> EffectObservation:
        if identity in self.cancellations:
            return EffectObservation("cancelled")
        return (
            EffectObservation("succeeded", self.results[identity])
            if identity in self.results
            else EffectObservation("absent")
        )

    async def dispatch(
        self, identity: str, state: WorkflowStateV1, context: NodeContext, config: RunnableConfig
    ) -> None:
        if identity not in self.results:
            self.dispatches += 1
            self.results[identity] = {
                "results": {context.execution_id: {"status": "succeeded"}},
                "outcome": {"status": "completed"},
            }

    async def cancel(self, identity: str) -> None:
        self.cancellations.add(identity)


@pytest.mark.parametrize(
    "point",
    [
        "before_effect_prepare",
        "after_prepare_before_dispatch",
        "after_dispatch_before_result",
        "after_result_before_checkpoint",
        "after_checkpoint_before_projection",
    ],
)
async def test_run006_crash_reentry_reuses_effect(
    database_url: str, session_factory: async_sessionmaker[AsyncSession], point: str
) -> None:
    policy, revisions = external_defaults()
    spec = spec_for(
        (node("work", "worker"), node("finish", "finalize")),
        (edge("work", "finish"),),
        defaults=policy,
    )
    run_id = await prepare_run(session_factory, spec, snapshot_for(spec, *revisions))
    owner, fence = await acquire(session_factory, run_id)
    adapter = DeterministicAdapter()
    fired = False

    def crash(candidate: str) -> None:
        nonlocal fired
        if candidate == point and not fired:
            fired = True
            raise InjectedCrash()

    owner.fault = crash
    with pytest.raises(InjectedCrash):
        await OrchestratorService(database_url, owner, adapters={"work": adapter})._execute(fence)
    async with session_factory.begin() as session:
        lease = await session.scalar(
            select(RunLeaseModel).where(
                RunLeaseModel.run_id == run_id, RunLeaseModel.generation == fence.generation
            )
        )
        assert lease is not None
        lease.expires_at = owner.clock.now() - timedelta(seconds=1)
    replacement, new_fence = await acquire(session_factory, run_id)
    await OrchestratorService(database_url, replacement, adapters={"work": adapter})._execute(
        new_fence
    )
    assert adapter.dispatches == 1
    async with session_factory() as session:
        run = await session.get(RunModel, run_id)
        assert run is not None and run.status == "completed"
        effects = (
            await session.scalars(select(EffectModel).where(EffectModel.run_id == run_id))
        ).all()
        assert len(effects) == 1 and effects[0].status == "succeeded"


async def test_run007_unknown_non_idempotent_effect_blocks(
    database_url: str, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    class UnknownAdapter(DeterministicAdapter):
        idempotent = False

        async def inspect(self, identity: str) -> EffectObservation:
            return EffectObservation("unknown")

    policy, revisions = external_defaults()
    spec = spec_for(
        (node("work", "worker"), node("finish", "finalize")),
        (edge("work", "finish"),),
        defaults=policy,
    )
    run_id = await prepare_run(session_factory, spec, snapshot_for(spec, *revisions))
    owner, fence = await acquire(session_factory, run_id)
    adapter = UnknownAdapter()
    await OrchestratorService(database_url, owner, adapters={"work": adapter}).execute(fence)
    assert adapter.dispatches == 0
    async with session_factory() as session:
        run = await session.get(RunModel, run_id)
        assert run is not None and run.status == "blocked"
        effect = await session.scalar(select(EffectModel).where(EffectModel.run_id == run_id))
        assert effect is not None and effect.status == "unknown"
