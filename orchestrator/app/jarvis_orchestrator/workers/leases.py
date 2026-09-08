"""Numbered worker capacity under the existing M5 run transaction fence."""

from __future__ import annotations

import hashlib
import secrets
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from uuid6 import uuid7

from jarvis_contracts.registry import WorkerSpec
from jarvis_contracts.workers import WorkerSlotFence
from jarvis_orchestrator.runtime.ownership import RunFence, RunOwnership, StaleExecutorError
from jarvis_orchestrator.workers.safety import WorkerBoundaryError
from jarvis_persistence.models import (
    ConfigurationRevisionModel,
    TaskAttemptModel,
    TaskModel,
    WorkerLeaseModel,
    WorkerSlotModel,
)


class WorkerSlots:
    def __init__(self, ownership: RunOwnership, fence: RunFence) -> None:
        self.ownership = ownership
        self.fence = fence

    async def acquire(
        self, revision_id: UUID, attempt_id: UUID, spec: WorkerSpec
    ) -> WorkerSlotFence:
        async with self.ownership.fenced(self.fence) as (session, run):
            revision = await session.get(ConfigurationRevisionModel, revision_id)
            attempt = await session.get(TaskAttemptModel, attempt_id)
            task = await session.get(TaskModel, attempt.task_id) if attempt else None
            if revision is None or task is None or task.run_id != run.id:
                raise WorkerBoundaryError("worker_lease_identity_invalid")
            if WorkerSpec.model_validate(revision.spec_json.get("spec")) != spec:
                raise WorkerBoundaryError("worker_revision_spec_mismatch")
            slots = list(
                (
                    await session.scalars(
                        select(WorkerSlotModel)
                        .where(WorkerSlotModel.worker_id == revision.configuration_id)
                        .order_by(WorkerSlotModel.slot_number)
                        .with_for_update()
                    )
                ).all()
            )
            for number in range(spec.max_concurrency):
                if not any(slot.slot_number == number for slot in slots):
                    slot = WorkerSlotModel(
                        id=uuid7(),
                        worker_id=revision.configuration_id,
                        slot_number=number,
                        generation=0,
                    )
                    session.add(slot)
                    slots.append(slot)
            await session.flush()
            now = self.ownership.clock.now()
            for slot in slots:
                if slot.slot_number >= spec.max_concurrency:
                    continue
                current = await session.scalar(
                    select(WorkerLeaseModel).where(
                        WorkerLeaseModel.slot_id == slot.id, WorkerLeaseModel.released_at.is_(None)
                    )
                )
                if current is not None:
                    # Expiry does not prove the remote writer stopped. Reconcile first.
                    if (
                        current.task_attempt_id == attempt_id
                        and current.run_id == run.id
                        and current.expires_at > now
                    ):
                        return self.contract(current, slot)
                    continue
                slot.generation += 1
                lease = WorkerLeaseModel(
                    id=uuid7(),
                    slot_id=slot.id,
                    worker_revision_id=revision_id,
                    run_id=run.id,
                    task_attempt_id=attempt_id,
                    owner_instance_id=self.fence.owner,
                    generation=slot.generation,
                    run_generation=self.fence.generation,
                    token_hash=hashlib.sha256(secrets.token_bytes(32)).hexdigest(),
                    acquired_at=now,
                    renewed_at=now,
                    expires_at=now + self.ownership.ttl,
                )
                session.add(lease)
                await self.ownership.event(
                    session,
                    run,
                    "worker.lease_acquired",
                    {
                        "lease_id": str(lease.id),
                        "generation": lease.generation,
                        "slot": slot.slot_number,
                        "worker_revision_id": str(revision_id),
                    },
                )
                return self.contract(lease, slot)
            raise WorkerBoundaryError("worker_capacity_unavailable")

    @staticmethod
    def contract(lease: WorkerLeaseModel, slot: WorkerSlotModel) -> WorkerSlotFence:
        return WorkerSlotFence(
            lease_id=lease.id,
            worker_revision_id=lease.worker_revision_id,
            slot=slot.slot_number,
            generation=lease.generation,
            run_generation=lease.run_generation,
            expires_at=lease.expires_at,
        )

    async def require(self, session: AsyncSession, lease: WorkerSlotFence) -> WorkerLeaseModel:
        row = await session.get(WorkerLeaseModel, lease.lease_id, with_for_update=True)
        slot = await session.get(WorkerSlotModel, row.slot_id) if row else None
        if (
            row is None
            or slot is None
            or row.run_id != self.fence.run_id
            or row.worker_revision_id != lease.worker_revision_id
            or row.generation != lease.generation
            or slot.generation != lease.generation
            or slot.slot_number != lease.slot
            or row.released_at is not None
            or row.expires_at <= self.ownership.clock.now()
        ):
            raise StaleExecutorError("Worker slot fence expired or was superseded")
        return row

    async def renew(self, lease: WorkerSlotFence) -> None:
        async with self.ownership.fenced(self.fence) as (session, _run):
            row = await self.require(session, lease)
            row.renewed_at = self.ownership.clock.now()
            row.expires_at = row.renewed_at + self.ownership.ttl

    async def release(self, lease: WorkerSlotFence, *, reconciled_terminal: bool) -> None:
        if not reconciled_terminal:
            raise WorkerBoundaryError("worker_release_requires_reconciliation")
        async with self.ownership.fenced(self.fence) as (session, run):
            row = await session.get(WorkerLeaseModel, lease.lease_id, with_for_update=True)
            if row is None or row.run_id != run.id or row.generation != lease.generation:
                raise StaleExecutorError("Worker lease identity changed")
            if row.released_at is not None:
                return
            row.released_at = self.ownership.clock.now()
            await self.ownership.event(
                session,
                run,
                "worker.lease_lost",
                {"lease_id": str(row.id), "generation": row.generation},
            )
