"""Repository integration serialization under M5 run fencing and lock ordering."""

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from sqlalchemy import select

from jarvis_orchestrator.runtime.ownership import RunFence, RunOwnership, StaleExecutorError
from jarvis_persistence.models import ArtifactModel, EffectModel, IntegrationHeadModel


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
            row = await session.get(IntegrationHeadModel, (run.id, repository_id))
            if row is None:
                session.add(
                    IntegrationHeadModel(
                        run_id=run.id,
                        repository_id=repository_id,
                        base_sha=base_sha,
                        head_sha=base_sha,
                        branch=branch,
                        generation=0,
                    )
                )
            elif row.base_sha != base_sha:
                raise ValueError("immutable integration base changed")

    async def acquire(self, repository_id: UUID, effect_id: UUID) -> IntegrationFence | None:
        async with self.ownership.fenced(self.fence) as (session, run):
            row = await session.get(
                IntegrationHeadModel, (run.id, repository_id), with_for_update=True
            )
            effect = await session.get(EffectModel, effect_id)
            if (
                row is None
                or effect is None
                or effect.run_id != run.id
                or effect.kind != "integrate"
            ):
                raise ValueError("integration identity is not a prepared runtime effect")
            now = self.ownership.clock.now()
            if (
                row.lease_owner is not None
                and row.released_at is None
                and row.expires_at is not None
                and row.expires_at > now
            ):
                return None
            first = await session.scalar(
                select(EffectModel.id)
                .where(
                    EffectModel.run_id == run.id,
                    EffectModel.kind == "integrate",
                    EffectModel.status.in_(("prepared", "dispatched", "running")),
                    EffectModel.result_json.is_(None),
                )
                .order_by(EffectModel.created_at, EffectModel.id)
                .limit(1)
            )
            if first != effect_id:
                return None
            row.generation += 1
            row.lease_owner = effect_id
            row.acquired_at = row.renewed_at = now
            row.expires_at = now + self.ttl
            row.released_at = None
            await self.ownership.event(
                session,
                run,
                "git.integration_lease_acquired",
                {
                    "repository_id": str(repository_id),
                    "effect_id": str(effect_id),
                    "generation": row.generation,
                    "base_sha": row.head_sha,
                    "lease_action": "acquired",
                    "owner": self.fence.owner,
                    "expires_at": row.expires_at.isoformat(),
                },
            )
            return IntegrationFence(repository_id, effect_id, row.generation, row.head_sha)

    def validate(
        self, row: IntegrationHeadModel | None, fence: IntegrationFence
    ) -> IntegrationHeadModel:
        if (
            row is None
            or row.lease_owner != fence.effect_id
            or row.generation != fence.generation
            or row.released_at is not None
            or row.expires_at is None
            or row.expires_at <= self.ownership.clock.now()
            or row.head_sha != fence.base_sha
        ):
            raise StaleExecutorError("integration lease is stale")
        return row

    async def renew(self, fence: IntegrationFence) -> None:
        async with self.ownership.fenced(self.fence) as (session, run):
            row = self.validate(
                await session.get(
                    IntegrationHeadModel, (run.id, fence.repository_id), with_for_update=True
                ),
                fence,
            )
            row.renewed_at = self.ownership.clock.now()
            row.expires_at = row.renewed_at + self.ttl
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
            row = await session.get(
                IntegrationHeadModel, (run.id, fence.repository_id), with_for_update=True
            )
            if (
                row is not None
                and row.generation == fence.generation
                and row.lease_owner == fence.effect_id
                and row.released_at is None
            ):
                row.released_at = self.ownership.clock.now()
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
            row = self.validate(
                await session.get(
                    IntegrationHeadModel, (run.id, fence.repository_id), with_for_update=True
                ),
                fence,
            )
            artifact = await session.get(ArtifactModel, snapshot_artifact_id)
            if (
                artifact is None
                or artifact.run_id != run.id
                or artifact.redaction_classification != "redacted"
            ):
                raise ValueError("integration snapshot is not authorized immutable evidence")
            row.head_sha, row.branch, row.snapshot_artifact_id = (
                head_sha,
                branch,
                snapshot_artifact_id,
            )
            effect = await session.get(EffectModel, fence.effect_id)
            assert effect is not None
            effect.request_json = {
                **effect.request_json,
                "integration_committed": {
                    "head_sha": head_sha,
                    "branch": branch,
                    "worktree_root": worktree_root,
                    "snapshot_artifact_id": str(snapshot_artifact_id),
                    "combined_gate_artifact_id": str(gate_artifact_id)
                    if gate_artifact_id
                    else None,
                },
            }
            row.released_at = self.ownership.clock.now()
            await self.ownership.event(
                session,
                run,
                "git.integration_completed",
                {
                    "repository_id": str(fence.repository_id),
                    "generation": fence.generation,
                    "effect_id": str(fence.effect_id),
                    "base_sha": fence.base_sha,
                    "head_sha": head_sha,
                    "branch": branch,
                    "snapshot_artifact_id": str(snapshot_artifact_id),
                    "combined_gate_artifact_id": str(gate_artifact_id)
                    if gate_artifact_id
                    else None,
                },
            )
            # Event persistence may await I/O. Expiry still fences this entire
            # transaction, including its effect receipt and selected HEAD.
            if row.expires_at is None or row.expires_at <= self.ownership.clock.now():
                raise StaleExecutorError("integration lease expired before advancement commit")
