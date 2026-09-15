"""Repository/target-branch integration authority with fenced CAS advancement."""

from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from uuid6 import uuid7

from jarvis_orchestrator.runtime.ownership import RunFence, RunOwnership, StaleExecutorError
from jarvis_persistence.models import (
    AcceptedTargetHeadModel,
    ArtifactModel,
    EffectModel,
    IntegrationHeadModel,
    MergeCandidateModel,
)


@dataclass(frozen=True)
class IntegrationFence:
    repository_id: UUID
    effect_id: UUID
    generation: int
    base_sha: str


class IntegrationLeases:
    def __init__(
        self, ownership: RunOwnership, fence: RunFence, *, ttl: timedelta = timedelta(seconds=30)
    ) -> None:
        if not timedelta(seconds=1) <= ttl <= timedelta(minutes=10):
            raise ValueError("invalid integration lease lifetime")
        self.ownership, self.fence, self.ttl = ownership, fence, ttl

    async def initialize(self, repository_id: UUID, *, base_sha: str, branch: str) -> None:
        async with self.ownership.fenced(self.fence) as (session, run):
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
                {"key": f"{repository_id}:{branch}"},
            )
            accepted = await session.scalar(
                select(AcceptedTargetHeadModel)
                .where(
                    AcceptedTargetHeadModel.repository_id == repository_id,
                    AcceptedTargetHeadModel.target_branch == branch,
                )
                .with_for_update()
            )
            if accepted is None:
                accepted = AcceptedTargetHeadModel(
                    id=uuid7(), repository_id=repository_id, target_branch=branch, head_sha=base_sha
                )
                session.add(accepted)
                await session.flush()
            row = await session.get(IntegrationHeadModel, (run.id, repository_id))
            if row is None:
                session.add(
                    IntegrationHeadModel(
                        run_id=run.id,
                        repository_id=repository_id,
                        base_sha=accepted.head_sha,
                        head_sha=accepted.head_sha,
                        branch=branch,
                        target_branch=branch,
                        generation=accepted.generation,
                    )
                )
            elif row.target_branch != branch:
                raise ValueError("immutable integration target changed")

    async def queue(
        self,
        repository_id: UUID,
        effect_id: UUID,
        *,
        task_attempt_id: UUID,
        base_sha: str,
        candidate_sha: str,
        profile_revision_id: UUID,
        verification_identity: str,
        review_identity: str,
        directive_identity: str,
    ) -> None:
        async with self.ownership.fenced(self.fence) as (session, run):
            head = await session.get(IntegrationHeadModel, (run.id, repository_id))
            effect = await session.get(EffectModel, effect_id)
            if head is None or effect is None or effect.run_id != run.id:
                raise ValueError("merge candidate does not own its run effect")
            existing = await session.scalar(
                select(MergeCandidateModel).where(MergeCandidateModel.effect_id == effect_id)
            )
            if existing is not None:
                if existing.candidate_sha != candidate_sha:
                    raise ValueError("merge candidate identity changed")
                return
            session.add(
                MergeCandidateModel(
                    id=uuid7(),
                    repository_id=repository_id,
                    target_branch=head.target_branch,
                    run_id=run.id,
                    effect_id=effect_id,
                    task_attempt_id=task_attempt_id,
                    profile_revision_id=profile_revision_id,
                    base_sha=base_sha,
                    candidate_sha=candidate_sha,
                    verification_identity=verification_identity,
                    review_identity=review_identity,
                    directive_identity=directive_identity,
                    status="queued",
                )
            )

    async def acquire(self, repository_id: UUID, effect_id: UUID) -> IntegrationFence | None:
        async with self.ownership.fenced(self.fence) as (session, run):
            row = await session.get(
                IntegrationHeadModel, (run.id, repository_id), with_for_update=True
            )
            effect = await session.get(EffectModel, effect_id)
            candidate = await session.scalar(
                select(MergeCandidateModel).where(MergeCandidateModel.effect_id == effect_id)
            )
            if (
                candidate is None
                and row is not None
                and effect is not None
                and effect.task_attempt_id
            ):
                candidate = MergeCandidateModel(
                    id=uuid7(),
                    repository_id=repository_id,
                    target_branch=row.target_branch,
                    run_id=run.id,
                    effect_id=effect_id,
                    task_attempt_id=effect.task_attempt_id,
                    profile_revision_id=UUID(int=0),
                    base_sha=row.head_sha,
                    candidate_sha=str(effect.request_json.get("candidate_sha", row.head_sha)),
                    verification_identity=effect.request_digest,
                    review_identity=effect.request_digest,
                    directive_identity=effect.request_digest,
                    status="queued",
                )
                session.add(candidate)
                await session.flush()
            if (
                row is None
                or effect is None
                or candidate is None
                or effect.run_id != run.id
                or effect.kind != "integrate"
            ):
                raise ValueError("integration identity is not a queued runtime effect")
            accepted = await session.scalar(
                select(AcceptedTargetHeadModel)
                .where(
                    AcceptedTargetHeadModel.repository_id == repository_id,
                    AcceptedTargetHeadModel.target_branch == row.target_branch,
                )
                .with_for_update()
            )
            if accepted is None:
                raise ValueError("accepted target is unavailable")
            now = self.ownership.clock.now()
            if (
                accepted.lease_owner is not None
                and accepted.lease_expires_at is not None
                and accepted.lease_expires_at <= now
            ):
                expired = await session.get(
                    MergeCandidateModel, accepted.lease_owner, with_for_update=True
                )
                if expired is not None and expired.status == "integrating":
                    expired.status = "queued"
                accepted.lease_owner = None
                accepted.lease_expires_at = None
            if (
                accepted.lease_owner is not None
                and accepted.lease_expires_at
                and accepted.lease_expires_at > now
            ):
                return None
            first = await session.scalar(
                select(MergeCandidateModel.id)
                .where(
                    MergeCandidateModel.repository_id == repository_id,
                    MergeCandidateModel.target_branch == row.target_branch,
                    MergeCandidateModel.status == "queued",
                )
                .order_by(MergeCandidateModel.created_at, MergeCandidateModel.id)
                .limit(1)
            )
            if first != candidate.id:
                return None
            accepted.lease_generation += 1
            accepted.lease_owner = candidate.id
            accepted.lease_expires_at = now + self.ttl
            candidate.status = "integrating"
            candidate.expected_head_sha = accepted.head_sha
            row.generation = accepted.lease_generation
            row.lease_owner = effect_id
            row.acquired_at = row.renewed_at = now
            row.expires_at = accepted.lease_expires_at
            row.released_at = None
            await self.ownership.event(
                session,
                run,
                "git.integration_lease_acquired",
                {
                    "repository_id": str(repository_id),
                    "target_branch": row.target_branch,
                    "effect_id": str(effect_id),
                    "generation": row.generation,
                    "base_sha": accepted.head_sha,
                    "lease_action": "acquired",
                    "owner": self.fence.owner,
                    "expires_at": row.expires_at.isoformat(),
                },
            )
            return IntegrationFence(repository_id, effect_id, row.generation, accepted.head_sha)

    async def _locked(
        self, session: AsyncSession, run_id: UUID, fence: IntegrationFence
    ) -> tuple[IntegrationHeadModel, AcceptedTargetHeadModel, MergeCandidateModel]:
        row = await session.get(
            IntegrationHeadModel, (run_id, fence.repository_id), with_for_update=True
        )
        if row is None:
            raise StaleExecutorError("integration lease is stale")
        accepted = await session.scalar(
            select(AcceptedTargetHeadModel)
            .where(
                AcceptedTargetHeadModel.repository_id == fence.repository_id,
                AcceptedTargetHeadModel.target_branch == row.target_branch,
            )
            .with_for_update()
        )
        candidate = await session.scalar(
            select(MergeCandidateModel)
            .where(MergeCandidateModel.effect_id == fence.effect_id)
            .with_for_update()
        )
        if (
            accepted is None
            or candidate is None
            or accepted.lease_owner != candidate.id
            or accepted.lease_generation != fence.generation
            or accepted.lease_expires_at is None
            or accepted.lease_expires_at <= self.ownership.clock.now()
            or accepted.head_sha != fence.base_sha
            or candidate.expected_head_sha != fence.base_sha
            or candidate.status != "integrating"
        ):
            raise StaleExecutorError("integration lease is stale")
        return row, accepted, candidate

    async def renew(self, fence: IntegrationFence) -> None:
        async with self.ownership.fenced(self.fence) as (session, run):
            row, accepted, _ = await self._locked(session, run.id, fence)
            now = self.ownership.clock.now()
            accepted.lease_expires_at = now + self.ttl
            row.renewed_at, row.expires_at = now, accepted.lease_expires_at
            await self.ownership.event(
                session,
                run,
                "git.integration_lease_renewed",
                {
                    "repository_id": str(fence.repository_id),
                    "generation": fence.generation,
                    "effect_id": str(fence.effect_id),
                    "expires_at": row.expires_at.isoformat(),
                },
            )

    async def release(self, fence: IntegrationFence) -> None:
        async with self.ownership.fenced(self.fence) as (session, run):
            try:
                row, accepted, candidate = await self._locked(session, run.id, fence)
            except StaleExecutorError:
                return
            accepted.lease_owner = None
            accepted.lease_expires_at = None
            row.released_at = self.ownership.clock.now()
            if candidate.status == "integrating":
                candidate.status = "queued"
            await self.ownership.event(
                session,
                run,
                "git.integration_lease_released",
                {
                    "repository_id": str(fence.repository_id),
                    "generation": fence.generation,
                    "lease_action": "released",
                    "effect_id": str(fence.effect_id),
                },
            )

    async def reject(
        self, fence: IntegrationFence, *, conflict: dict[str, Any] | None = None
    ) -> None:
        async with self.ownership.fenced(self.fence) as (session, run):
            row, accepted, candidate = await self._locked(session, run.id, fence)
            candidate.status = "conflicted" if conflict else "rejected"
            candidate.conflict_json = conflict
            candidate.completed_at = self.ownership.clock.now()
            accepted.lease_owner = None
            accepted.lease_expires_at = None
            row.released_at = candidate.completed_at

    async def bind_review(self, fence: IntegrationFence, *, review_identity: str) -> None:
        """Replace stale review identity only while holding the candidate fence."""
        async with self.ownership.fenced(self.fence) as (session, run):
            _row, _accepted, candidate = await self._locked(session, run.id, fence)
            candidate.review_identity = review_identity

    async def advance(
        self,
        fence: IntegrationFence,
        *,
        head_sha: str,
        branch: str,
        snapshot_artifact_id: UUID,
        worktree_root: str,
        gate_artifact_id: UUID | None = None,
    ) -> None:
        async with self.ownership.fenced(self.fence) as (session, run):
            row, accepted, candidate = await self._locked(session, run.id, fence)
            artifact = await session.get(ArtifactModel, snapshot_artifact_id)
            gate = await session.get(ArtifactModel, gate_artifact_id) if gate_artifact_id else None
            if (
                artifact is None
                or artifact.run_id != run.id
                or artifact.redaction_classification != "redacted"
                or gate is None
                or gate.run_id != run.id
                or gate.task_attempt_id != candidate.task_attempt_id
            ):
                raise ValueError("advancement requires authorized snapshot and combined gates")
            accepted.head_sha = head_sha
            accepted.generation += 1
            accepted.updated_at = self.ownership.clock.now()
            accepted.lease_owner = None
            accepted.lease_expires_at = None
            candidate.status = "accepted"
            candidate.accepted_generation = accepted.generation
            candidate.completed_at = accepted.updated_at
            row.head_sha, row.branch, row.snapshot_artifact_id = (
                head_sha,
                branch,
                snapshot_artifact_id,
            )
            row.released_at = accepted.updated_at
            effect = await session.get(EffectModel, fence.effect_id)
            assert effect is not None
            effect.request_json = {
                **effect.request_json,
                "integration_committed": {
                    "head_sha": head_sha,
                    "branch": branch,
                    "worktree_root": worktree_root,
                    "snapshot_artifact_id": str(snapshot_artifact_id),
                    "combined_gate_artifact_id": str(gate_artifact_id),
                },
            }
            await self.ownership.event(
                session,
                run,
                "git.integration_completed",
                {
                    "repository_id": str(fence.repository_id),
                    "target_branch": row.target_branch,
                    "generation": accepted.generation,
                    "effect_id": str(fence.effect_id),
                    "base_sha": fence.base_sha,
                    "head_sha": head_sha,
                    "branch": branch,
                    "snapshot_artifact_id": str(snapshot_artifact_id),
                    "combined_gate_artifact_id": str(gate_artifact_id),
                },
            )
