from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from uuid6 import uuid7

from jarvis_orchestrator.runtime.ownership import RunOwnership, StaleExecutorError
from jarvis_persistence.models import RunLeaseModel, RunModel
from jarvis_persistence.testing import FrozenClock
from tests.integration.support import NOW, seed_run

pytestmark = pytest.mark.integration


async def test_run001_claim_separation_and_stale_fence(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    clock = FrozenClock(NOW)
    first, second = await seed_run(session_factory), await seed_run(session_factory)
    # Keep this test's queue independent from historical fixtures in the shared DB.
    async with session_factory.begin() as session:
        for identifier, priority in ((first.run_id, 10000), (second.run_id, 9999)):
            run = await session.get(RunModel, identifier)
            assert run is not None
            run.priority = priority
    a = RunOwnership(session_factory, owner=str(uuid7()), clock=clock)
    b = RunOwnership(session_factory, owner=str(uuid7()), clock=clock)
    await a.register()
    await b.register()
    claims = await asyncio.gather(a.claim(), b.claim())
    assert all(claim is not None for claim in claims)
    assert {claim.run_id for claim in claims if claim} == {first.run_id, second.run_id}
    claim = next(item for item in claims if item and item.owner == a.owner)
    async with a.fenced(claim) as (_session, run):
        run.status = "running"
    clock.advance(timedelta(seconds=31))
    recovered = await b.claim()
    assert recovered is not None
    # The highest-priority expired run is recovered first.
    assert recovered.run_id == first.run_id
    old = next(item for item in claims if item and item.run_id == recovered.run_id)
    assert recovered.generation == old.generation + 1
    with pytest.raises(StaleExecutorError):
        async with a.fenced(old) as (_session, run):
            run.status = "completed"
    async with b.fenced(recovered) as (_session, run):
        assert run.status == "claiming"
    await b.renew(recovered)
    async with session_factory() as session:
        lease = await session.scalar(
            select(RunLeaseModel).where(
                RunLeaseModel.run_id == recovered.run_id,
                RunLeaseModel.generation == recovered.generation,
            )
        )
        assert lease is not None
        assert lease.expires_at == clock.now() + b.ttl


async def test_run001_skip_locked_priority_and_drain(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    first, second = await seed_run(session_factory), await seed_run(session_factory)
    async with session_factory.begin() as session:
        for identifier, priority in ((first.run_id, 20000), (second.run_id, 19999)):
            run = await session.get(RunModel, identifier)
            assert run is not None
            run.priority = priority
    owner = RunOwnership(session_factory, owner=str(uuid7()))
    await owner.register()
    async with session_factory.begin() as blocker:
        await blocker.scalar(select(RunModel).where(RunModel.id == first.run_id).with_for_update())
        claimed = await asyncio.wait_for(owner.claim(), 3)
        assert claimed is not None and claimed.run_id == second.run_id
    claimed = await owner.claim()
    assert claimed is not None and claimed.run_id == first.run_id
    await owner.heartbeat(draining=True)
    assert await owner.claim() is None
    await owner.release(claimed)
    with pytest.raises(StaleExecutorError):
        await owner.renew(claimed)


async def test_run002_expiry_during_transaction_rolls_back(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    clock = FrozenClock(NOW)
    seeded = await seed_run(session_factory)
    async with session_factory.begin() as session:
        run = await session.get(RunModel, seeded.run_id)
        assert run is not None
        run.priority = 30000
    owner = RunOwnership(session_factory, owner=str(uuid7()), clock=clock)
    await owner.register()
    claim = await owner.claim()
    assert claim is not None and claim.run_id == seeded.run_id
    with pytest.raises(StaleExecutorError):
        async with owner.fenced(claim) as (_session, run):
            run.status = "completed"
            clock.advance(timedelta(seconds=31))
    async with session_factory() as session:
        run = await session.get(RunModel, seeded.run_id)
        assert run is not None and run.status == "claiming"
