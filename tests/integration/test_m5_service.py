from __future__ import annotations

import asyncio
from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from uuid6 import uuid7

from jarvis_contracts.enums import RunCommandKind
from jarvis_orchestrator.runtime.effects import EffectObservation
from jarvis_orchestrator.runtime.ownership import RunOwnership
from jarvis_orchestrator.runtime.service import OrchestratorService
from jarvis_persistence.models import EventModel, RunLeaseModel, RunModel
from tests.integration.test_m5_control import enqueue
from tests.integration.test_m5_effects import DeterministicAdapter
from tests.integration.test_m5_runtime import acquire, prepare_run
from tests.unit.test_m4_workflows_compiler import (
    edge,
    external_defaults,
    node,
    snapshot_for,
    spec_for,
)

pytestmark = pytest.mark.integration


class DelayedAdapter(DeterministicAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.ready = asyncio.Event()

    async def inspect(self, identity: str) -> EffectObservation:
        if (
            identity in self.results
            and not self.ready.is_set()
            and identity not in self.cancellations
        ):
            return EffectObservation("running")
        return await super().inspect(identity)


async def external_run(factory: async_sessionmaker[AsyncSession]) -> UUID:
    defaults, revisions = external_defaults()
    defaults = defaults.model_copy(update={"timeout_seconds": 60})
    spec = spec_for(
        (node("work", "worker"), node("finish", "finalize")),
        (edge("work", "finish"),),
        defaults=defaults,
    )
    return await prepare_run(factory, spec, snapshot_for(spec, *revisions))


async def dispatched(adapter: DeterministicAdapter, count: int = 1) -> None:
    async with asyncio.timeout(15):
        while adapter.dispatches < count:
            await asyncio.sleep(0.02)


async def test_two_instances_bounded_concurrency_and_survivor_recovery(
    database_url: str,
    session_factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    ids = [await external_run(session_factory) for _ in range(3)]
    async with session_factory.begin() as session:
        top = (await session.scalar(select(func.max(RunModel.priority))) or 0) + 10
        for index, identifier in enumerate(ids):
            run = await session.get(RunModel, identifier)
            assert run is not None
            run.priority = top - index
    adapter = DelayedAdapter()
    first = RunOwnership(session_factory, owner=str(uuid7()))
    second = RunOwnership(session_factory, owner=str(uuid7()))
    await first.register()
    await second.register()
    a = OrchestratorService(
        database_url, first, max_concurrency=2, global_concurrency=3, adapters={"work": adapter}
    )
    b = OrchestratorService(
        database_url, second, max_concurrency=1, global_concurrency=3, adapters={"work": adapter}
    )
    await a.tick()
    await b.tick()
    assert {f.run_id for f in a.active} == set(ids[:2])
    assert {f.run_id for f in b.active} == {ids[2]}
    await dispatched(adapter, 3)
    assert await second.claim(capacity=3) is None
    await a.tick()
    assert len(a.active) == 2
    lost = next(iter(a.active))
    async with session_factory.begin() as session:
        lease = await session.scalar(
            select(RunLeaseModel).where(
                RunLeaseModel.run_id == lost.run_id, RunLeaseModel.released_at.is_(None)
            )
        )
        assert lease is not None
        lease.expires_at = first.clock.now() - timedelta(seconds=1)
    await asyncio.wait_for(a.active[lost], 10)
    replacement = await second.claim()
    assert replacement is not None and replacement.run_id == lost.run_id
    assert replacement.generation > lost.generation
    recovery = asyncio.create_task(b.execute(replacement))
    adapter.ready.set()
    await asyncio.gather(*a.active.values(), *b.active.values(), recovery)
    assert adapter.dispatches == 3
    assert "Discarded stale executor" in caplog.text
    async with session_factory() as session:
        for identifier in ids:
            run = await session.get(RunModel, identifier)
            assert run is not None and run.status == "completed"
        events = (
            await session.scalars(select(EventModel.type).where(EventModel.run_id == lost.run_id))
        ).all()
        assert events.count("run.completed") == 1
        assert "run.recovering" in events and "run.recovered" in events


async def test_live_effect_pause_boundary_and_cancel_acknowledgement(
    database_url: str, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    run_id = await external_run(session_factory)
    owner, fence = await acquire(session_factory, run_id)
    adapter = DelayedAdapter()
    task = asyncio.create_task(
        OrchestratorService(database_url, owner, adapters={"work": adapter}).execute(fence)
    )
    await dispatched(adapter)
    await enqueue(session_factory, run_id, RunCommandKind.PAUSE)
    async with session_factory() as session:
        run = await session.get(RunModel, run_id)
        assert run is not None and run.status == "pause_requested"
    await enqueue(session_factory, run_id, RunCommandKind.CANCEL)
    await asyncio.wait_for(task, 10)
    assert len(adapter.cancellations) == 1
    async with session_factory() as session:
        run = await session.get(RunModel, run_id)
        assert run is not None and run.status == "cancelled"


async def test_graceful_drain_completes_active_run_without_claiming_next(
    database_url: str, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    ids = [await external_run(session_factory) for _ in range(2)]
    async with session_factory.begin() as session:
        top = (await session.scalar(select(func.max(RunModel.priority))) or 0) + 10
        for index, identifier in enumerate(ids):
            run = await session.get(RunModel, identifier)
            assert run is not None
            run.priority = top - index
    adapter = DelayedAdapter()
    stop = asyncio.Event()
    owner = RunOwnership(session_factory, owner=str(uuid7()))
    service = OrchestratorService(
        database_url, owner, max_concurrency=1, adapters={"work": adapter}
    )
    serving = asyncio.create_task(service.serve(stop))
    await dispatched(adapter)
    stop.set()
    adapter.ready.set()
    await asyncio.wait_for(serving, 15)
    async with session_factory() as session:
        active = await session.get(RunModel, ids[0])
        queued = await session.get(RunModel, ids[1])
        assert active is not None and active.status == "completed"
        assert queued is not None and queued.status == "queued"
    assert await owner.claim() is None
