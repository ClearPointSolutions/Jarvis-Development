"""Independent, current-task review bound to sealed deterministic evidence."""

from __future__ import annotations

import asyncio
from typing import Protocol
from uuid import UUID, uuid5

from sqlalchemy import select

from jarvis_contracts.verification import ReviewDecision, ReviewEvidence, VerificationExecution
from jarvis_orchestrator.runtime.effects import AmbiguousEffectError
from jarvis_orchestrator.verification.artifacts import EvidenceArtifacts
from jarvis_orchestrator.verification.executor import ConfirmedRepository, VerificationExecutor
from jarvis_orchestrator.workers.safety import WorkerBoundaryError
from jarvis_persistence.models import EventModel


class ReviewerAdapter(Protocol):
    async def review(
        self, review_id: UUID, evidence: ReviewEvidence, artifacts: EvidenceArtifacts
    ) -> ReviewDecision: ...


class ReviewService:
    def __init__(
        self,
        executor: VerificationExecutor,
        artifacts: EvidenceArtifacts,
        adapter: ReviewerAdapter,
        *,
        timeout_seconds: float = 120,
    ) -> None:
        if not 1 <= timeout_seconds <= 3600:
            raise ValueError("Reviewer deadline must be between 1 and 3600 seconds")
        self.executor, self.artifacts, self.adapter = executor, artifacts, adapter
        self.timeout_seconds = timeout_seconds

    async def current(self, repository: ConfirmedRepository, evidence: ReviewEvidence) -> bool:
        from jarvis_orchestrator.verification.snapshots import SnapshotBuilder

        try:
            captured = await SnapshotBuilder(self.executor, self.artifacts).capture(
                repository,
                base_sha=evidence.snapshot.base_sha,
                latest_base_sha=evidence.snapshot.latest_base_sha,
            )
        except (WorkerBoundaryError, ValueError):
            return False
        return (
            captured.digest == evidence.snapshot.content_digest
            and repository.head_sha == evidence.snapshot.head_sha
        )

    async def run(
        self, repository: ConfirmedRepository, evidence: ReviewEvidence, *, operation_id: UUID
    ) -> tuple[ReviewDecision, UUID, bool]:
        owner, fence = self.artifacts.ownership, self.artifacts.fence
        review_id = uuid5(operation_id, "review")
        for artifact_id in evidence.verification_artifact_ids:
            execution = VerificationExecution.model_validate(await self.artifacts.read(artifact_id))
            if (
                execution.status != "passed"
                or execution.snapshot_id != evidence.snapshot.id
                or execution.source_sha != evidence.snapshot.head_sha
            ):
                raise ValueError("Reviewer requires deterministic passing snapshot evidence")
        async with owner.fenced(fence) as (session, run):
            previous = await session.scalar(
                select(EventModel)
                .where(
                    EventModel.run_id == run.id,
                    EventModel.type.in_(
                        (
                            "review.started",
                            "review.completed",
                            "review.failed",
                            "review.snapshot_invalidated",
                        )
                    ),
                    EventModel.data_json["review_id"].astext == str(review_id),
                )
                .order_by(EventModel.global_position.desc())
                .limit(1)
            )
        recovering = previous is not None and previous.type == "review.started"
        if recovering and not getattr(self.adapter, "recoverable", False):
            raise AmbiguousEffectError("Reviewer dispatch requires reconciliation")
        if previous is not None and not recovering:
            artifact_id = UUID(previous.data_json["feedback_artifact_id"])
            decision = ReviewDecision.model_validate(await self.artifacts.read(artifact_id))
        else:
            if not await self.current(repository, evidence):
                raise ValueError("review snapshot changed before dispatch")
            if recovering:
                assert previous is not None
                original = ReviewEvidence.model_validate(
                    await self.artifacts.read(UUID(previous.data_json["evidence_artifact_id"]))
                )
                if (
                    original.task_id != evidence.task_id
                    or original.task_attempt_id != evidence.task_attempt_id
                    or original.snapshot != evidence.snapshot
                    or original.acceptance_criteria != evidence.acceptance_criteria
                ):
                    raise AmbiguousEffectError("Recovered review evidence identity changed")
                evidence = original
            async with owner.fenced(fence) as (session, run):
                evidence_id = await self.artifacts.put(
                    session,
                    run,
                    evidence.task_attempt_id,
                    "review-evidence",
                    evidence.model_dump(mode="json"),
                )
                if not recovering:
                    await owner.event(
                        session,
                        run,
                        "review.started",
                        {
                            "task_id": str(evidence.task_id),
                            "task_attempt_id": str(evidence.task_attempt_id),
                            "review_id": str(review_id),
                            "evidence_artifact_id": str(evidence_id),
                            "snapshot_id": str(evidence.snapshot.id),
                            "head_sha": evidence.snapshot.head_sha,
                        },
                    )
            owner.fault("m8_after_reviewer_dispatched")
            async with asyncio.timeout(self.timeout_seconds):
                decision = await self.adapter.review(review_id, evidence, self.artifacts)
            decision = ReviewDecision.model_validate(decision.model_dump())
            if (
                decision.id != review_id
                or decision.task_id != evidence.task_id
                or decision.task_attempt_id != evidence.task_attempt_id
                or decision.reviewed_snapshot_id != evidence.snapshot.id
                or decision.reviewed_head_sha != evidence.snapshot.head_sha
                or decision.snapshot_digest != evidence.snapshot.content_digest
                or any(
                    f.criterion_index >= len(evidence.acceptance_criteria)
                    for f in decision.findings
                )
                or (decision.verdict == "FAIL" and not decision.findings)
                or (decision.verdict == "PASS" and decision.findings)
            ):
                raise ValueError("Reviewer response is not bound to current-task evidence")
            async with owner.fenced(fence) as (session, run):
                artifact_id = await self.artifacts.put(
                    session,
                    run,
                    evidence.task_attempt_id,
                    "review-feedback",
                    decision.model_dump(mode="json"),
                )
        valid = await self.current(repository, evidence)
        # Recovered evidence is subject to exactly the same binding checks as a
        # newly returned decision. An old effect cannot authorize another task.
        if (
            decision.id != review_id
            or decision.task_id != evidence.task_id
            or decision.task_attempt_id != evidence.task_attempt_id
            or decision.reviewed_snapshot_id != evidence.snapshot.id
            or decision.reviewed_head_sha != evidence.snapshot.head_sha
            or decision.snapshot_digest != evidence.snapshot.content_digest
        ):
            raise ValueError("persisted review does not match current evidence")
        terminal = (
            "review.snapshot_invalidated"
            if not valid
            else "review.completed"
            if decision.verdict == "PASS"
            else "review.failed"
        )
        if previous is not None and previous.type == terminal:
            return decision, artifact_id, valid
        async with owner.fenced(fence) as (session, run):
            await owner.event(
                session,
                run,
                terminal,
                {
                    "task_id": str(evidence.task_id),
                    "task_attempt_id": str(evidence.task_attempt_id),
                    "review_id": str(review_id),
                    "reviewed_snapshot_id": str(evidence.snapshot.id),
                    "reviewed_head_sha": decision.reviewed_head_sha,
                    "feedback_artifact_id": str(artifact_id),
                    "valid": valid,
                    "verdict": decision.verdict,
                    "summary": "Repository snapshot changed" if not valid else decision.summary,
                },
            )
        owner.fault("m8_after_review_result_persisted")
        return decision, artifact_id, valid
