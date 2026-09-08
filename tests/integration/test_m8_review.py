"""Authoritative cumulative Reviewer evidence and persisted SHA invalidation."""

import os
import sys
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from uuid6 import uuid7

from jarvis_contracts.verification import (
    ReviewDecision,
    ReviewEvidence,
    ReviewFinding,
    VerificationCommand,
)
from jarvis_orchestrator.verification.artifacts import EvidenceArtifacts
from jarvis_orchestrator.verification.executor import ConfirmedRepository, VerificationExecutor
from jarvis_orchestrator.verification.legacy import normalize_legacy
from jarvis_orchestrator.verification.reviews import ReviewService
from jarvis_orchestrator.verification.service import VerificationService
from jarvis_orchestrator.verification.snapshots import SnapshotBuilder
from jarvis_orchestrator.workers.workspace import WorktreeManager
from jarvis_persistence.models import EventModel, RunModel
from tests.integration.test_m5_runtime import acquire, prepare_run
from tests.integration.test_m8_evidence import base_repository, git, task_rows

pytestmark = pytest.mark.integration


class CurrentTaskReviewer:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail, self.calls = fail, 0

    async def review(
        self, review_id: UUID, evidence: ReviewEvidence, artifacts: EvidenceArtifacts
    ) -> ReviewDecision:
        self.calls += 1
        source = await artifacts.read(evidence.snapshot.source_artifact_id)
        cumulative = await artifacts.read(evidence.snapshot.cumulative_diff_artifact_id)
        latest = await artifacts.read(evidence.snapshot.latest_diff_artifact_id)
        assert isinstance(source, dict) and "earlier.txt" in source and "current.txt" in source
        assert (
            isinstance(cumulative, str)
            and "earlier.txt" in cumulative
            and "current.txt" in cumulative
        )
        assert isinstance(latest, str) and "current.txt" in latest and "earlier.txt" not in latest
        assert evidence.acceptance_criteria == ("Current task content exists",)
        now = artifacts.ownership.clock.now()
        return ReviewDecision(
            id=review_id,
            task_id=evidence.task_id,
            task_attempt_id=evidence.task_attempt_id,
            reviewed_snapshot_id=evidence.snapshot.id,
            reviewed_head_sha=evidence.snapshot.head_sha,
            snapshot_digest=evidence.snapshot.content_digest,
            verdict="FAIL" if self.fail else "PASS",
            summary="Current task issue" if self.fail else "Current task accepted",
            findings=(
                ReviewFinding(
                    criterion_index=0,
                    summary="Current content needs correction",
                    source_path="current.txt",
                ),
            )
            if self.fail
            else (),
            reviewer_revision="deterministic-local-v1",
            started_at=now,
            finished_at=now,
        )


@pytest.mark.parametrize("failure", [False, True])
async def test_cumulative_review_recovery_feedback_and_head_mutation(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path, failure: bool
) -> None:
    run_id = await prepare_run(session_factory)
    owner, fence = await acquire(session_factory, run_id)
    owner.ttl = timedelta(minutes=5)
    await owner.renew(fence)
    root = tmp_path / "repository"
    base = base_repository(root)
    (root / "earlier.txt").write_text("earlier task state\n")
    git(root, "add", "earlier.txt")
    git(root, "commit", "-m", "earlier task")
    latest_base = git(root, "rev-parse", "HEAD")
    (root / "current.txt").write_text("current task state\n")
    git(root, "add", "current.txt")
    git(root, "commit", "-m", "current task")
    task_id, attempt_id, operation_id = await task_rows(session_factory, run_id, 1)
    repository = ConfirmedRepository(root, "main", git(root, "rev-parse", "HEAD"))
    executor = VerificationExecutor(
        WorktreeManager(tmp_path), {"python": (sys.executable,)}, path=os.defpath
    )
    artifacts = EvidenceArtifacts(owner, fence, tmp_path / "artifacts")
    snapshot, _ = await SnapshotBuilder(executor, artifacts).seal(
        repository,
        repository_id=uuid7(),
        task_id=task_id,
        attempt_id=attempt_id,
        worker_result_id=uuid7(),
        base_sha=base,
        latest_base_sha=latest_base,
    )
    verifier = VerificationService(executor, artifacts)
    correction = normalize_legacy("cd /workspace && python --version")
    await verifier.correction(attempt_id, correction)
    assert (await executor.execute(repository, correction.command)).passed
    passed, reports = await verifier.run(
        repository,
        snapshot,
        (VerificationCommand(argv=("python", "-c", "print('passed')")),),
        task_id=task_id,
        operation_id=operation_id,
    )
    assert passed
    async with owner.fenced(fence) as (session, run):
        history = await artifacts.put(session, run, attempt_id, "failure-history", [])
        workflow_id, config_id = run.workflow_version_id, run.config_snapshot_id
    evidence = ReviewEvidence(
        objective="Complete current task, with future tasks separately planned",
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
    )
    adapter = CurrentTaskReviewer(fail=failure)
    review = ReviewService(executor, artifacts, adapter)
    decision, feedback, valid = await review.run(repository, evidence, operation_id=operation_id)
    assert valid and (decision.verdict == "FAIL") == failure
    recovered = ReviewService(executor, artifacts, adapter)
    assert await recovered.run(repository, evidence, operation_id=operation_id) == (
        decision,
        feedback,
        True,
    )
    assert adapter.calls == 1
    assert (await artifacts.read(feedback)) == decision.model_dump(mode="json")
    (root / "current.txt").write_text("changed after review\n")
    git(root, "add", "current.txt")
    git(root, "commit", "-m", "mutation")
    assert (await recovered.run(repository, evidence, operation_id=operation_id))[2] is False
    async with session_factory() as session:
        events = (
            await session.scalars(select(EventModel).where(EventModel.run_id == run_id))
        ).all()
        assert sum(e.type == "review.snapshot_invalidated" for e in events) == 1
        assert sum(e.type == "command.normalized" for e in events) == 1
        assert (
            sum(e.type == ("review.failed" if failure else "review.completed") for e in events) == 1
        )
        assert await session.get(RunModel, run_id) is not None
