"""Integration ownership, expiry, generation fencing and least privilege."""

from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from uuid6 import uuid7

from jarvis_orchestrator.runtime.ownership import StaleExecutorError
from jarvis_orchestrator.verification.leases import IntegrationLeases
from jarvis_persistence.models import IntegrationHeadModel
from tests.integration.test_m5_runtime import acquire, prepare_run
from tests.integration.test_m8_evidence import task_rows

pytestmark = pytest.mark.integration


async def test_expired_generation_and_competing_integration_cannot_advance(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = await prepare_run(session_factory)
    owner, fence = await acquire(session_factory, run_id)
    repository_id = uuid7()
    _, _, first = await task_rows(session_factory, run_id, 1)
    _, _, second = await task_rows(session_factory, run_id, 2)
    leases = IntegrationLeases(owner, fence)
    await leases.initialize(repository_id, base_sha="a" * 40, branch="main")
    original = await leases.acquire(repository_id, first)
    assert original is not None
    assert await leases.acquire(repository_id, second) is None
    assert await leases.acquire(repository_id, first) is None
    async with session_factory.begin() as session:
        row = await session.get(IntegrationHeadModel, (run_id, repository_id))
        assert row is not None
        row.expires_at = owner.clock.now() - timedelta(seconds=1)
    replacement = await leases.acquire(repository_id, first)
    assert replacement is not None and replacement.generation == original.generation + 1
    with pytest.raises(StaleExecutorError):
        await leases.advance(
            original,
            head_sha="b" * 40,
            branch="stale",
            snapshot_artifact_id=uuid7(),
            worktree_root="unused",
        )
    with pytest.raises(StaleExecutorError):
        await leases.renew(original)
    await leases.release(original)
    await leases.renew(replacement)
    async with session_factory() as session:
        row = await session.get(IntegrationHeadModel, (run_id, repository_id))
        assert row is not None and row.head_sha == "a" * 40 and row.released_at is None
    await leases.release(replacement)
