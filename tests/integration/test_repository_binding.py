"""Durable binding freezes precede inference and reject changed authority."""

from uuid import uuid4

import pytest
from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from jarvis_contracts.verification import VerificationCommand
from jarvis_orchestrator.runtime.binding import configuration_digest, freeze_binding
from jarvis_orchestrator.runtime.configuration import RepositoryBinding
from jarvis_orchestrator.runtime.errors import RuntimeDependencyError
from jarvis_orchestrator.runtime.repository_lifecycle import (
    accepted_source,
    integration_target_branch,
)
from jarvis_orchestrator.verification.leases import IntegrationLeases
from jarvis_persistence.models import JobModel, RunConfigSnapshotModel, RunModel
from tests.integration.test_m5_runtime import acquire, prepare_run
from tests.m7_worker_fixture import worker_request

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


async def test_historical_target_is_frozen_and_reconstructed_without_switching(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = await prepare_run(session_factory)
    owner, fence = await acquire(session_factory, run_id)
    request = worker_request()
    async with session_factory() as session:
        run = await session.get(RunModel, run_id)
        assert run is not None
        job = await session.get(JobModel, run.job_id)
        assert job is not None
        project_id, workflow_id = job.project_id, run.workflow_version_id
    binding = RepositoryBinding(
        project=request.project.model_copy(update={"project_id": project_id}),
        worker_revision_id=request.worker_revision_id,
        base_policy="historical",
        combined_commands=(VerificationCommand(argv=("python", "-m", "pytest")),),
    )
    lifecycle = await accepted_source(owner, fence, binding)
    target = integration_target_branch(binding, run_id)
    assert target != binding.project.branch
    assert lifecycle["integration_target_branch"] == target
    identity: dict[str, JsonValue] = {
        "project_id": str(project_id),
        "workflow_version_id": str(workflow_id),
        "lifecycle": lifecycle,
    }
    await freeze_binding(owner, fence, identity)
    leases = IntegrationLeases(owner, fence)
    await leases.initialize(
        binding.project.repository_id, base_sha=binding.project.base_sha, branch=target
    )
    # Rebuild from durable state, including compatibility with a manifest's newer seed.
    changed_seed = binding.model_copy(
        update={"project": binding.project.model_copy(update={"base_sha": "f" * 40})}
    )
    assert await accepted_source(owner, fence, changed_seed) == lifecycle
    rebuilt = IntegrationLeases(owner, fence)
    await rebuilt.initialize(
        binding.project.repository_id, base_sha=binding.project.base_sha, branch=target
    )
    with pytest.raises(ValueError, match="immutable integration target"):
        await rebuilt.initialize(binding.project.repository_id, base_sha="f" * 40, branch="main")
    with pytest.raises(RuntimeDependencyError, match="binding changed"):
        await freeze_binding(
            owner,
            fence,
            {
                **identity,
                "lifecycle": {
                    **lifecycle,
                    "integration_target_branch": "main",
                },
            },
        )
