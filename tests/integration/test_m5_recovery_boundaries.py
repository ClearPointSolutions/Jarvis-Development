from __future__ import annotations

import asyncio
from datetime import timedelta
from uuid import UUID

import pytest
from langchain_core.runnables import RunnableConfig
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from uuid6 import uuid7

from jarvis_contracts.commands import RunCommandRequest
from jarvis_contracts.enums import FailureClass, RunCommandKind
from jarvis_orchestrator.runtime.commands import CommandProcessor
from jarvis_orchestrator.runtime.ownership import RunOwnership
from jarvis_orchestrator.runtime.service import OrchestratorService
from jarvis_orchestrator.workflows.factories import NodeContext
from jarvis_orchestrator.workflows.state import WorkflowStateV1
from jarvis_persistence.models import (
    EffectModel,
    FailureModel,
    RetryCounterModel,
    RunLeaseModel,
    RunModel,
)
from jarvis_persistence.repositories import CommandRepository
from jarvis_persistence.testing import FrozenClock
from tests.integration.support import NOW, seed_run
from tests.integration.test_m5_control import enqueue
from tests.integration.test_m5_effects import DeterministicAdapter, InjectedCrash
from tests.integration.test_m5_runtime import acquire, prepare_run
from tests.integration.test_m5_service import DelayedAdapter, dispatched, external_run
from tests.unit.test_m4_workflows_compiler import (
    edge,
    external_defaults,
    node,
    snapshot_for,
    spec_for,
)

pytestmark = pytest.mark.integration


async def expire(factory: async_sessionmaker[AsyncSession], identifier: UUID) -> None:
    async with factory.begin() as session:
        lease = await session.scalar(
            select(RunLeaseModel).where(
                RunLeaseModel.run_id == identifier, RunLeaseModel.released_at.is_(None)
            )
        )
        assert lease is not None
        lease.expires_at -= timedelta(days=1)


async def test_crash_during_cancellation_reconciles_controlled_adapter(
    database_url: str, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    identifier = await external_run(session_factory)
    owner, fence = await acquire(session_factory, identifier)
    adapter = DelayedAdapter()

    def crash(point: str) -> None:
        if point == "during_cancellation":
            raise InjectedCrash()

    owner.fault = crash
    task = asyncio.create_task(
        OrchestratorService(database_url, owner, adapters={"work": adapter})._execute(fence)
    )
    await dispatched(adapter)
    await enqueue(session_factory, identifier, RunCommandKind.CANCEL)
    with pytest.raises(InjectedCrash):
        await task
    await expire(session_factory, identifier)
    replacement, new_fence = await acquire(session_factory, identifier)
    await OrchestratorService(database_url, replacement, adapters={"work": adapter})._execute(
        new_fence
    )
    assert adapter.dispatches == 1 and len(adapter.cancellations) == 1
    async with session_factory() as session:
        effect = await session.scalar(select(EffectModel).where(EffectModel.run_id == identifier))
        assert effect is not None and effect.status == "cancelled"


async def test_crash_before_pause_interrupt_reenters_durable_boundary(
    database_url: str, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    identifier = await prepare_run(session_factory)
    await enqueue(session_factory, identifier, RunCommandKind.PAUSE)
    owner, fence = await acquire(session_factory, identifier)

    def crash(point: str) -> None:
        if point == "during_pause":
            raise InjectedCrash()

    owner.fault = crash
    with pytest.raises(InjectedCrash):
        await OrchestratorService(database_url, owner)._execute(fence)
    await expire(session_factory, identifier)
    replacement, new_fence = await acquire(session_factory, identifier)
    await OrchestratorService(database_url, replacement)._execute(new_fence)
    async with session_factory() as session:
        run = await session.get(RunModel, identifier)
        assert run is not None and run.status == "paused"


@pytest.mark.parametrize(
    "failure",
    [FailureClass.CONFIGURATION_INVALID, FailureClass.SECURITY_POLICY_DENIED, FailureClass.UNKNOWN],
)
async def test_fail006_nontransient_adapter_results_block_without_retry(
    database_url: str, session_factory: async_sessionmaker[AsyncSession], failure: FailureClass
) -> None:
    class Denied(DeterministicAdapter):
        async def dispatch(
            self,
            identity: str,
            state: WorkflowStateV1,
            context: NodeContext,
            config: RunnableConfig,
        ) -> None:
            await super().dispatch(identity, state, context, config)
            self.results[identity] = {
                "outcome": {"status": "failed", "failure_class": failure.value}
            }

    identifier = await external_run(session_factory)
    owner, fence = await acquire(session_factory, identifier)
    adapter = Denied()
    await OrchestratorService(database_url, owner, adapters={"work": adapter}).execute(fence)
    async with session_factory() as session:
        run = await session.get(RunModel, identifier)
        assert run is not None and run.status == "blocked"
        failures = (
            await session.scalars(select(FailureModel).where(FailureModel.run_id == identifier))
        ).all()
        assert [row.failure_class for row in failures] == [failure.value]
        assert (
            await session.scalar(
                select(func.count())
                .select_from(RetryCounterModel)
                .where(RetryCounterModel.run_id == identifier)
            )
            == 0
        )
    assert adapter.dispatches == 1


async def test_instruction_delivery_respects_published_opt_in_and_objective(
    database_url: str, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    class Receiver(DeterministicAdapter):
        def __init__(self) -> None:
            super().__init__()
            self.received: list[object] = []

        async def dispatch(
            self,
            identity: str,
            state: WorkflowStateV1,
            context: NodeContext,
            config: RunnableConfig,
        ) -> None:
            self.received.extend(config["configurable"]["runtime_instructions"])
            assert config["configurable"]["runtime_objective"]
            await super().dispatch(identity, state, context, config)

    defaults, revisions = external_defaults()
    defaults = defaults.model_copy(update={"accepts_runtime_instructions": True})
    spec = spec_for(
        (node("work", "worker"), node("finish", "finalize")),
        (edge("work", "finish"),),
        defaults=defaults,
    )
    identifier = await prepare_run(session_factory, spec, snapshot_for(spec, *revisions))
    async with session_factory.begin() as session:
        await CommandRepository().enqueue(
            session,
            RunCommandRequest(
                run_id=identifier,
                kind=RunCommandKind.INSTRUCTION,
                idempotency_key=str(uuid7()),
                payload={"instruction": "Keep output concise"},
            ),
        )
    owner, fence = await acquire(session_factory, identifier)
    await CommandProcessor(owner).apply(identifier)
    adapter = Receiver()
    await OrchestratorService(database_url, owner, adapters={"work": adapter})._execute(fence)
    assert len(adapter.received) == 1


async def test_100_queued_runs_keep_deterministic_priority_order(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    seed = await seed_run(session_factory)
    identifiers: list[UUID] = []
    async with session_factory.begin() as session:
        base = await session.get(RunModel, seed.run_id)
        assert base is not None
        priority = (await session.scalar(select(func.max(RunModel.priority))) or 0) + 1000
        for number in range(100):
            identifier = uuid7()
            identifiers.append(identifier)
            session.add(
                RunModel(
                    id=identifier,
                    job_id=base.job_id,
                    run_number=number + 2,
                    workflow_version_id=base.workflow_version_id,
                    config_snapshot_id=base.config_snapshot_id,
                    langgraph_thread_id=str(identifier),
                    status="queued",
                    desired_state="running",
                    priority=priority - number,
                    claimable_at=NOW,
                )
            )
    owner = RunOwnership(session_factory, owner=str(uuid7()), clock=FrozenClock(NOW))
    await owner.register()
    actual = []
    for _ in range(100):
        claimed = await owner.claim()
        assert claimed is not None
        actual.append(claimed.run_id)
    assert actual == identifiers
