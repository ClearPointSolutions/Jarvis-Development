"""Durable binding freezes precede inference and reject changed authority."""

from uuid import uuid4

import pytest
from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from jarvis_orchestrator.runtime.binding import configuration_digest, freeze_binding
from jarvis_orchestrator.runtime.errors import RuntimeDependencyError
from jarvis_persistence.models import JobModel, RunConfigSnapshotModel, RunModel
from tests.integration.test_m5_runtime import acquire, prepare_run

pytestmark = pytest.mark.integration


async def test_binding_is_immutable_and_recoverable(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = await prepare_run(session_factory)
    owner, fence = await acquire(session_factory, run_id)
    async with session_factory() as session:
        run = await session.get(RunModel, run_id)
        assert run is not None
        original = run.config_snapshot_id
        version = run.workflow_version_id
        job = await session.get(JobModel, run.job_id)
        assert job is not None
        identity: dict[str, JsonValue] = {
            "project_id": str(job.project_id),
            "workflow_version_id": str(version),
            "repository_id": str(uuid4()),
            "worker_revision_id": str(uuid4()),
            "binding_digest": "a" * 64,
            "target_digest": "b" * 64,
        }
    with pytest.raises(RuntimeDependencyError, match="project does not match"):
        await freeze_binding(owner, fence, {**identity, "project_id": str(uuid4())})
    await freeze_binding(owner, fence, identity)
    await freeze_binding(owner, fence, identity)
    async with session_factory() as session:
        run = await session.get(RunModel, run_id)
        assert run is not None and run.config_snapshot_id != original
        prior = await session.get(RunConfigSnapshotModel, original)
        frozen = await session.get(RunConfigSnapshotModel, run.config_snapshot_id)
        assert prior is not None and "repository_binding" not in prior.effective_spec_json
        assert frozen is not None and frozen.effective_spec_json["repository_binding"] == identity
        assert frozen.snapshot_hash == configuration_digest(version, frozen.effective_spec_json)
    with pytest.raises(RuntimeDependencyError, match="binding changed"):
        await freeze_binding(owner, fence, {**identity, "binding_digest": "c" * 64})
