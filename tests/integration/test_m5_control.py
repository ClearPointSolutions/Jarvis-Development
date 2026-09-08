from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from uuid6 import uuid7

from jarvis_contracts.commands import RunCommandRequest
from jarvis_contracts.enums import RunCommandKind
from jarvis_orchestrator.runtime.commands import CommandProcessor
from jarvis_orchestrator.runtime.ownership import RunOwnership
from jarvis_orchestrator.runtime.service import OrchestratorService
from jarvis_persistence.checkpoints import postgres_saver
from jarvis_persistence.models import RunCommandModel, RunModel
from jarvis_persistence.repositories import CommandRepository
from tests.integration.test_m5_runtime import acquire, prepare_run

pytestmark = pytest.mark.integration


async def enqueue(
    factory: async_sessionmaker[AsyncSession], run_id: UUID, kind: RunCommandKind
) -> None:
    async with factory.begin() as session:
        await CommandRepository().enqueue(
            session, RunCommandRequest(run_id=run_id, kind=kind, idempotency_key=str(uuid7()))
        )
    await CommandProcessor(RunOwnership(factory, owner="command-test")).apply(run_id)


async def test_run004_pause_restart_resume_same_thread_once(
    database_url: str, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    run_id = await prepare_run(session_factory)
    await enqueue(session_factory, run_id, RunCommandKind.PAUSE)
    owner, fence = await acquire(session_factory, run_id)
    async with postgres_saver(database_url, setup=True):
        pass
    await OrchestratorService(database_url, owner)._execute(fence)
    async with session_factory() as session:
        run = await session.get(RunModel, run_id)
        assert run is not None and run.status == "paused"
        thread = run.langgraph_thread_id
    await enqueue(session_factory, run_id, RunCommandKind.RESUME)
    replacement, new_fence = await acquire(session_factory, run_id)
    assert new_fence.generation > fence.generation
    await OrchestratorService(database_url, replacement)._execute(new_fence)
    async with session_factory() as session:
        run = await session.get(RunModel, run_id)
        assert run is not None and run.status == "completed"
        assert run.langgraph_thread_id == thread
    async with postgres_saver(database_url) as saver:
        saved = await saver.aget_tuple({"configurable": {"thread_id": thread}})
        assert saved is not None
        counters = saved.checkpoint["channel_values"]["counters"]
        assert counters["visit:main:first"] == 1
        assert counters["visit:main:finish"] == 1


async def test_run005_cancel_dominates_ordered_commands(
    database_url: str, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    run_id = await prepare_run(session_factory)
    async with session_factory.begin() as session:
        for kind in (RunCommandKind.PAUSE, RunCommandKind.CANCEL, RunCommandKind.RESUME):
            await CommandRepository().enqueue(
                session, RunCommandRequest(run_id=run_id, kind=kind, idempotency_key=str(uuid7()))
            )
    owner, fence = await acquire(session_factory, run_id)
    await CommandProcessor(owner).apply(run_id)
    await OrchestratorService(database_url, owner)._execute(fence)
    await enqueue(session_factory, run_id, RunCommandKind.RESUME)
    async with session_factory() as session:
        run = await session.get(RunModel, run_id)
        assert run is not None and run.status == "cancelled"
        commands = (
            await session.scalars(
                select(RunCommandModel)
                .where(RunCommandModel.run_id == run_id)
                .order_by(RunCommandModel.sequence)
            )
        ).all()
        assert [command.status for command in commands] == [
            "superseded",
            "applied",
            "superseded",
            "rejected",
        ]


async def test_run009_retry_preserves_terminal_history(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = await prepare_run(session_factory)
    async with session_factory.begin() as session:
        run = await session.get(RunModel, run_id)
        assert run is not None
        run.status = "failed"
        previous_thread = run.langgraph_thread_id
    await enqueue(session_factory, run_id, RunCommandKind.RETRY)
    async with session_factory() as session:
        old = await session.get(RunModel, run_id)
        linked = await session.scalar(select(RunModel).where(RunModel.parent_run_id == run_id))
        assert old is not None and old.status == "failed"
        assert linked is not None and linked.status == "queued"
        assert linked.langgraph_thread_id != previous_thread
        assert linked.config_snapshot_id == old.config_snapshot_id
