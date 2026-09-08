"""Real local repositories, PostgreSQL evidence and M5 fenced integration acceptance."""

import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from uuid6 import uuid7

from jarvis_contracts.verification import ReviewDecision, ReviewEvidence, VerificationCommand
from jarvis_orchestrator.verification.artifacts import EvidenceArtifacts
from jarvis_orchestrator.verification.attempts import TaskAttemptWorkspaces
from jarvis_orchestrator.verification.executor import ConfirmedRepository, VerificationExecutor
from jarvis_orchestrator.verification.integration import LocalIntegrator
from jarvis_orchestrator.verification.leases import IntegrationLeases
from jarvis_orchestrator.verification.reviews import ReviewService
from jarvis_orchestrator.verification.service import VerificationService
from jarvis_orchestrator.verification.snapshots import SnapshotBuilder
from jarvis_orchestrator.workers.workspace import WorktreeManager
from jarvis_persistence.models import (
    EffectModel,
    EventModel,
    IntegrationHeadModel,
    TaskAttemptModel,
    TaskModel,
)
from tests.integration.test_m5_runtime import acquire, prepare_run

pytestmark = pytest.mark.integration


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(
        ("git", *args), cwd=root, text=True, stderr=subprocess.PIPE
    ).strip()


def base_repository(root: Path) -> str:
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "Fixture")
    git(root, "config", "user.email", "fixture@localhost")
    git(root, "config", "core.autocrlf", "false")
    (root / "shared.txt").write_text("base\n")
    git(root, "add", "--", "shared.txt")
    git(root, "commit", "-m", "base")
    return git(root, "rev-parse", "HEAD")


async def task_rows(
    sessions: async_sessionmaker[AsyncSession], run_id: UUID, index: int
) -> tuple[UUID, UUID, UUID]:
    task_id, attempt_id, effect_id = uuid7(), uuid7(), uuid7()
    async with sessions.begin() as session:
        session.add(
            TaskModel(
                id=task_id,
                run_id=run_id,
                key=f"DEV-{index}",
                title="Local change",
                status="running",
                weight=1,
                acceptance_criteria_json=["Current task content exists"],
                verification_json={},
            )
        )
        await session.flush()
        session.add(
            TaskAttemptModel(id=attempt_id, task_id=task_id, attempt_number=1, status="verifying")
        )
        await session.flush()
        session.add(
            EffectModel(
                id=effect_id,
                run_id=run_id,
                task_attempt_id=attempt_id,
                kind="integrate",
                idempotency_key=str(effect_id),
                request_digest="a" * 64,
                request_json={},
                status="prepared",
                fence_generation=1,
            )
        )
    return task_id, attempt_id, effect_id


@pytest.mark.parametrize("scenario", ["unrelated", "conflict", "combined_failure"])
async def test_rep004_real_git_serialized_integration(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path, scenario: str
) -> None:
    run_id = await prepare_run(session_factory)
    owner, fence = await acquire(session_factory, run_id)
    owner.ttl = timedelta(minutes=5)
    await owner.renew(fence)
    root = tmp_path / "repository"
    base = base_repository(root)
    repository_id = uuid7()
    manager = WorktreeManager(tmp_path)
    executor = VerificationExecutor(manager, {"python": (sys.executable,)}, path=os.defpath)
    artifacts = EvidenceArtifacts(owner, fence, tmp_path / "artifacts")
    snapshots = SnapshotBuilder(executor, artifacts)
    verifier = VerificationService(executor, artifacts)
    leases = IntegrationLeases(owner, fence)
    await leases.initialize(repository_id, base_sha=base, branch="main")
    integrator = LocalIntegrator(
        verifier, snapshots, leases, author_name="Fixture", author_email="fixture@localhost"
    )
    candidates = []
    for index in (1, 2):
        task_id, attempt_id, effect_id = await task_rows(session_factory, run_id, index)
        worktree, branch = await manager.create(
            root, run_id=run_id, task_key=f"DEV-{index}", attempt=1, base_sha=base
        )
        name = "shared.txt" if scenario == "conflict" else f"task{index}.txt"
        (worktree / name).write_text(f"task{index}\n")
        git(worktree, "add", "--", name)
        git(worktree, "commit", "-m", f"task {index}")
        candidate = ConfirmedRepository(worktree, branch, git(worktree, "rev-parse", "HEAD"))
        snapshot, _ = await snapshots.seal(
            candidate,
            repository_id=repository_id,
            task_id=task_id,
            attempt_id=attempt_id,
            worker_result_id=uuid7(),
            base_sha=base,
            latest_base_sha=base,
        )
        passed, reports = await verifier.run(
            candidate,
            snapshot,
            (
                VerificationCommand(
                    argv=(
                        "python",
                        "-c",
                        "from pathlib import Path; "
                        f"assert Path('{name}').read_text().strip() == 'task{index}'; "
                        "print('x' * 40000)",
                    )
                ),
            ),
            task_id=task_id,
            operation_id=uuid7(),
        )
        assert passed and len(reports) == 1

        class BranchReviewer:
            def __init__(self, filename: str) -> None:
                self.filename = filename

            async def review(
                self, review_id: UUID, evidence: ReviewEvidence, store: EvidenceArtifacts
            ) -> ReviewDecision:
                source = await store.read(evidence.snapshot.source_artifact_id)
                assert isinstance(source, dict) and self.filename in source
                return ReviewDecision(
                    id=review_id,
                    task_id=evidence.task_id,
                    task_attempt_id=evidence.task_attempt_id,
                    reviewed_snapshot_id=evidence.snapshot.id,
                    reviewed_head_sha=evidence.snapshot.head_sha,
                    snapshot_digest=evidence.snapshot.content_digest,
                    verdict="PASS",
                    summary="Task source checked",
                    reviewer_revision="local-fixture-v1",
                    started_at=owner.clock.now(),
                    finished_at=owner.clock.now(),
                )

        async with owner.fenced(fence) as (session, run):
            history = await artifacts.put(session, run, attempt_id, "failure-history", [])
            workflow_id, config_id = run.workflow_version_id, run.config_snapshot_id
        decision, _, valid = await ReviewService(executor, artifacts, BranchReviewer(name)).run(
            candidate,
            ReviewEvidence(
                objective="Integrate both independent tasks",
                workflow_version_id=workflow_id,
                config_snapshot_id=config_id,
                task_id=task_id,
                task_attempt_id=attempt_id,
                task_title="Current task",
                acceptance_criteria=("Current task content exists",),
                snapshot=snapshot,
                verification_artifact_ids=reports,
                prior_feedback_artifact_ids=(),
                failure_history_artifact_id=history,
            ),
            operation_id=effect_id,
        )
        assert valid
        candidates.append((candidate, snapshot, decision, task_id, effect_id))
    accepted = None
    for index, (candidate, snapshot, decision, task_id, effect_id) in enumerate(candidates):
        code = (
            "raise SystemExit(1)"
            if scenario == "combined_failure" and index == 1
            else "print('combined gate executed')"
        )
        result = await integrator.integrate(
            candidate,
            snapshot,
            decision,
            effect_id=effect_id,
            task_id=task_id,
            combined_commands=(VerificationCommand(argv=("python", "-c", code)),),
        )
        if index == 0:
            assert result.status == "completed"
            accepted = result.repository
        elif scenario == "unrelated":
            assert result.status == "completed" and result.repository is not None
            accepted = result.repository
            assert (accepted.root / "task1.txt").read_text().strip() == "task1"
            assert (accepted.root / "task2.txt").read_text().strip() == "task2"
        else:
            assert result.status == (
                "code.git_conflict" if scenario == "conflict" else "code.test_failure"
            )
            assert git(candidate.root, "rev-parse", "HEAD") == candidate.head_sha
        async with session_factory.begin() as session:
            effect = await session.get(EffectModel, effect_id)
            assert effect is not None
            effect.status = "succeeded"
    assert accepted is not None
    async with session_factory() as session:
        head = await session.get(IntegrationHeadModel, (run_id, repository_id))
        assert head is not None and head.head_sha == accepted.head_sha
        events = (
            await session.scalars(select(EventModel).where(EventModel.run_id == run_id))
        ).all()
        assert sum(e.type == "git.integration_completed" for e in events) == (
            2 if scenario == "unrelated" else 1
        )
        assert all(len(str(e.data_json)) < 8192 for e in events)
    assert git(root, "rev-parse", "main") == base
    # Subsequent work starts from selected cumulative state, not the original
    # repository branch, which deliberately remains untouched.
    next_task, previous_attempt, _ = await task_rows(session_factory, run_id, 3)
    async with session_factory.begin() as session:
        prior = await session.get(TaskAttemptModel, previous_attempt)
        assert prior is not None
        prior.status = "failed"
    prepared = await TaskAttemptWorkspaces(manager, leases).prepare(
        root,
        repository_id,
        next_task,
        worker_revision_id=uuid7(),
    )
    assert prepared.base_sha == accepted.head_sha and prepared.number == 2
    assert git(prepared.root, "rev-parse", "HEAD") == accepted.head_sha
    with pytest.raises(ValueError, match="active"):
        await TaskAttemptWorkspaces(manager, leases).prepare(
            root,
            repository_id,
            next_task,
            worker_revision_id=uuid7(),
        )
