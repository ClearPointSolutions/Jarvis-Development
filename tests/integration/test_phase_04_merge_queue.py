import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from uuid6 import uuid7

from jarvis_orchestrator.runtime.ownership import StaleExecutorError
from jarvis_orchestrator.verification.leases import IntegrationLeases
from jarvis_persistence.models import ArtifactModel, IntegrationHeadModel
from tests.integration.test_m5_runtime import acquire, prepare_run
from tests.integration.test_m8_evidence import task_rows

pytestmark = pytest.mark.integration


async def test_repository_branch_head_is_shared_and_stale_fence_cannot_advance(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    repository_id = uuid7()
    first_run = await prepare_run(session_factory)
    first_owner, first_run_fence = await acquire(session_factory, first_run)
    _, first_attempt, first_effect = await task_rows(session_factory, first_run, 1)
    first = IntegrationLeases(first_owner, first_run_fence)
    await first.initialize(repository_id, base_sha="a" * 40, branch="main")
    await first.queue(
        repository_id,
        first_effect,
        task_attempt_id=first_attempt,
        base_sha="a" * 40,
        candidate_sha="b" * 40,
        profile_revision_id=uuid7(),
        verification_identity="1" * 64,
        review_identity="2" * 64,
        directive_identity="3" * 64,
    )
    fence = await first.acquire(repository_id, first_effect)
    assert fence is not None
    snapshot_id, gate_id = uuid7(), uuid7()
    async with session_factory.begin() as session:
        session.add(
            ArtifactModel(
                id=snapshot_id,
                run_id=first_run,
                task_attempt_id=first_attempt,
                kind="repository-snapshot",
                storage_key=str(snapshot_id),
                sha256="4" * 64,
                size_bytes=1,
                media_type="application/json",
                redaction_classification="redacted",
            )
        )
        session.add(
            ArtifactModel(
                id=gate_id,
                run_id=first_run,
                task_attempt_id=first_attempt,
                kind="combined-integration-gates",
                storage_key=str(gate_id),
                sha256="5" * 64,
                size_bytes=1,
                media_type="application/json",
                redaction_classification="redacted",
            )
        )
    await first.advance(
        fence,
        head_sha="b" * 40,
        branch="integration/first",
        snapshot_artifact_id=snapshot_id,
        worktree_root="/srv/worktrees/first",
        gate_artifact_id=gate_id,
    )
    with pytest.raises(StaleExecutorError):
        await first.renew(fence)

    second_run = await prepare_run(session_factory)
    second_owner, second_run_fence = await acquire(session_factory, second_run)
    second = IntegrationLeases(second_owner, second_run_fence)
    await second.initialize(repository_id, base_sha="a" * 40, branch="main")
    async with session_factory() as session:
        projection = await session.get(IntegrationHeadModel, (second_run, repository_id))
        assert projection is not None
        assert projection.base_sha == projection.head_sha == "b" * 40
