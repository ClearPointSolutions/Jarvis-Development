"""Durable task-attempt preparation from the selected integration HEAD."""

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from uuid6 import uuid7

from jarvis_orchestrator.verification.leases import IntegrationLeases
from jarvis_orchestrator.workers.workspace import WorktreeManager
from jarvis_persistence.models import IntegrationHeadModel, TaskAttemptModel, TaskModel


@dataclass(frozen=True)
class AttemptWorkspace:
    attempt_id: UUID
    number: int
    base_sha: str
    branch: str
    root: Path


class TaskAttemptWorkspaces:
    def __init__(self, manager: WorktreeManager, leases: IntegrationLeases) -> None:
        self.manager, self.leases = manager, leases

    async def prepare(
        self,
        repository: Path,
        repository_id: UUID,
        task_id: UUID,
        *,
        worker_revision_id: UUID,
    ) -> AttemptWorkspace:
        owner, fence = self.leases.ownership, self.leases.fence
        async with owner.fenced(fence) as (session, run):
            task = await session.get(TaskModel, task_id)
            head = await session.get(IntegrationHeadModel, (run.id, repository_id))
            if task is None or task.run_id != run.id or head is None:
                raise ValueError("attempt requires an owned task and initialized integration HEAD")
            previous = await session.scalar(
                select(TaskAttemptModel)
                .where(
                    TaskAttemptModel.task_id == task.id,
                )
                .order_by(TaskAttemptModel.attempt_number.desc())
                .limit(1)
            )
            if previous is not None and previous.status == "queued":
                attempt = previous
            else:
                if previous is not None and previous.status not in {"failed", "cancelled"}:
                    raise ValueError("task already has an active or successful attempt")
                attempt = TaskAttemptModel(
                    id=uuid7(),
                    task_id=task.id,
                    attempt_number=previous.attempt_number + 1 if previous else 1,
                    status="queued",
                    worker_revision_id=worker_revision_id,
                    base_sha=head.head_sha,
                )
                session.add(attempt)
            if attempt.worker_revision_id != worker_revision_id or attempt.base_sha is None:
                raise ValueError("attempt preparation binding changed")
            attempt_id, number, base_sha, key = (
                attempt.id,
                attempt.attempt_number,
                attempt.base_sha,
                task.key,
            )
        root, branch = await self.manager.create(
            repository,
            run_id=fence.run_id,
            task_key=key,
            attempt=number,
            base_sha=base_sha,
        )
        async with owner.fenced(fence) as (session, run):
            prepared = await session.get(TaskAttemptModel, attempt_id)
            assert prepared is not None
            if prepared.status != "queued":
                raise ValueError("attempt preparation was superseded")
            prepared.status, prepared.started_at = "running", owner.clock.now()
            await owner.event(
                session,
                run,
                "git.branch_created",
                {
                    "task_id": str(task_id),
                    "task_attempt_id": str(attempt_id),
                    "branch": branch,
                    "base_sha": base_sha,
                    "repository_id": str(repository_id),
                    "attempt": number,
                },
            )
        return AttemptWorkspace(attempt_id, number, base_sha, branch, root)
