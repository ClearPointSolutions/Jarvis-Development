from __future__ import annotations

from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from uuid6 import uuid7

from jarvis_contracts.base import sha256_digest
from jarvis_contracts.workflow import WorkflowSpec
from jarvis_contracts.workflow_api import WorkflowResolvedSnapshot
from jarvis_orchestrator.runtime.ownership import RunFence, RunOwnership
from jarvis_orchestrator.runtime.service import OrchestratorService
from jarvis_persistence.checkpoints import postgres_saver
from jarvis_persistence.models import RunConfigSnapshotModel, RunModel, WorkflowVersionModel
from jarvis_persistence.repositories import LeaseRepository
from tests.integration.support import NOW, seed_run
from tests.unit.test_m4_workflows_compiler import edge, node, snapshot_for, spec_for

pytestmark = pytest.mark.integration


async def prepare_run(
    session_factory: async_sessionmaker[AsyncSession],
    spec: WorkflowSpec | None = None,
    snapshot: WorkflowResolvedSnapshot | None = None,
) -> UUID:
    seeded = await seed_run(session_factory)
    spec = spec or spec_for((node("first"), node("finish", "finalize")), (edge("first", "finish"),))
    snapshot = snapshot or snapshot_for(spec)
    async with session_factory.begin() as session:
        old_version = await session.get(WorkflowVersionModel, seeded.workflow_version_id)
        assert old_version is not None
        version = WorkflowVersionModel(
            id=uuid7(),
            workflow_template_id=old_version.workflow_template_id,
            version=2,
            spec_version=spec.spec_version,
            compiler_version=snapshot.compiler_version,
            spec_json=spec.model_dump(mode="json", by_alias=True),
            layout_json={},
            content_hash=spec.content_hash,
            published_at=NOW,
        )
        session.add(version)
        await session.flush()
        config = RunConfigSnapshotModel(
            id=uuid7(),
            workflow_version_id=version.id,
            schema_version="1.0",
            resolved_revisions_json=[],
            effective_spec_json={"snapshot": snapshot.model_dump(mode="json")},
            snapshot_hash=sha256_digest(
                {"version_id": str(version.id), "snapshot": snapshot.model_dump(mode="json")}
            ),
        )
        session.add(config)
        await session.flush()
        run = await session.get(RunModel, seeded.run_id)
        assert run is not None
        run.workflow_version_id = version.id
        run.config_snapshot_id = config.id
    return seeded.run_id


async def acquire(
    session_factory: async_sessionmaker[AsyncSession], run_id: UUID
) -> tuple[RunOwnership, RunFence]:
    ownership = RunOwnership(session_factory, owner=str(uuid7()))
    await ownership.register()
    async with session_factory.begin() as session:
        lease = await LeaseRepository().acquire(
            session,
            run_id=run_id,
            owner_instance_id=ownership.owner,
            ttl=timedelta(seconds=30),
        )
        assert lease is not None
        fence = RunFence(run_id, ownership.owner, lease.generation)
    return ownership, fence


async def test_m5_compiled_graph_executes_under_dedicated_service(
    database_url: str,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = await prepare_run(session_factory)
    ownership, fence = await acquire(session_factory, run_id)
    async with postgres_saver(database_url, setup=True):
        pass
    service = OrchestratorService(database_url, ownership)
    await service._execute(fence)
    async with session_factory() as session:
        run = await session.get(RunModel, run_id)
        assert run is not None and run.status == "completed"
