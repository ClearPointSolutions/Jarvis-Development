from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from uuid6 import uuid7

from jarvis_orchestrator.runtime.checkpoints import fenced_saver
from jarvis_orchestrator.runtime.ownership import RunFence, RunOwnership, StaleExecutorError
from jarvis_orchestrator.workflows import compile_workflow, workflow_run_config
from jarvis_persistence.checkpoints import postgres_saver
from jarvis_persistence.repositories import LeaseRepository
from tests.integration.support import seed_run
from tests.unit.test_m4_workflows_compiler import edge, node, snapshot_for, spec_for

pytestmark = [pytest.mark.integration, pytest.mark.compatibility]


async def test_run002_native_checkpoint_and_pending_writes_are_fenced(
    database_url: str,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    seeded = await seed_run(session_factory)
    owner = RunOwnership(session_factory, owner=str(uuid7()))
    await owner.register()
    async with session_factory.begin() as session:
        lease = await LeaseRepository().acquire(
            session,
            run_id=seeded.run_id,
            owner_instance_id=owner.owner,
            ttl=timedelta(seconds=30),
        )
        assert lease is not None
        fence = RunFence(seeded.run_id, owner.owner, lease.generation)
    spec = spec_for((node("first"), node("finish", "finalize")), (edge("first", "finish"),))
    config = workflow_run_config(f"m5-fence-{seeded.run_id}")
    async with postgres_saver(database_url, setup=True):
        pass
    async with fenced_saver(database_url, fence) as saver:
        graph = compile_workflow(spec, snapshot_for(spec), checkpointer=saver)
        result = await graph.ainvoke({}, config)
        assert result["final"]["status"] == "completed"
        before = await saver.aget_tuple(config)
        assert before is not None
        await owner.release(fence)
        with pytest.raises(StaleExecutorError):
            await saver.aput_writes(before.config, [("cancelled", True)], "stale-task")
        with pytest.raises(StaleExecutorError):
            await saver.aput(before.config, before.checkpoint, before.metadata, {})
        after = await saver.aget_tuple(config)
        assert after == before
