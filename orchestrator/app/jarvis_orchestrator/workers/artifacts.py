"""Publish redacted worker logs through existing authorized immutable artifacts."""

import hashlib
from pathlib import Path
from uuid import UUID

from jarvis_api.events.artifacts import LocalEventArtifactStore, artifact_path
from jarvis_api.events.normalizer import EventIntent
from jarvis_api.events.redaction import RecursiveRedactor
from jarvis_contracts.enums import EventMode, EventSeverity, EventVisibility
from jarvis_contracts.events import EventScope, EventSource
from jarvis_contracts.ids import RunId, TaskAttemptId, TaskId
from jarvis_contracts.workers import WorkerInvocationRequest
from jarvis_orchestrator.runtime.ownership import RunFence, RunOwnership
from jarvis_orchestrator.workers.safety import WorkerBoundaryError
from jarvis_persistence.models import ArtifactModel


class WorkerContextReader:
    def __init__(self, ownership: RunOwnership, fence: RunFence, root: Path) -> None:
        self.ownership = ownership
        self.fence = fence
        self.root = root

    async def __call__(self, artifact_id: UUID) -> str:
        async with self.ownership.fenced(self.fence) as (session, _run):
            artifact = await session.get(ArtifactModel, artifact_id)
            if artifact is None or artifact.run_id != self.fence.run_id:
                raise WorkerBoundaryError("worker_context_scope_denied")
            if artifact.size_bytes > 16000 or artifact.redaction_classification != "redacted":
                raise WorkerBoundaryError("worker_context_invalid")
            with artifact_path(self.root, artifact.storage_key).open("rb") as stream:
                content = stream.read(16001)
            if (
                len(content) != artifact.size_bytes
                or hashlib.sha256(content).hexdigest() != artifact.sha256
            ):
                raise WorkerBoundaryError("worker_context_integrity_failed")
            return RecursiveRedactor().redact_text(content.decode(errors="replace"))[0]


class WorkerLogPublisher:
    def __init__(self, ownership: RunOwnership, fence: RunFence, root: Path) -> None:
        self.ownership = ownership
        self.fence = fence
        self.store = LocalEventArtifactStore(root)

    async def __call__(self, request: WorkerInvocationRequest, kind: str, content: bytes) -> None:
        safe = RecursiveRedactor().redact_text(content.decode(errors="replace"))[0].encode()
        if len(safe) > request.limits.max_output_bytes:
            raise ValueError("Worker artifact limit exceeded")
        scope = EventScope(
            run_id=RunId(request.run_id),
            task_id=TaskId(request.task_id),
            task_attempt_id=TaskAttemptId(request.task_attempt_id),
        )
        async with self.ownership.fenced(self.fence) as (session, run):
            reference = await self.store.put(
                session, content=safe, scope=scope, relation=kind, media_type="text/plain"
            )
            await self.ownership.writer.append(
                session,
                EventIntent(
                    occurred_at=self.ownership.clock.now(),
                    type="artifact.created",
                    severity=EventSeverity.INFO,
                    mode=EventMode(run.mode),
                    visibility=EventVisibility.OWNER,
                    scope=scope,
                    source=EventSource(
                        kind="worker_adapter", name="worker", instance_id=self.fence.owner
                    ),
                    correlation_id=str(request.run_id),
                    idempotency_key=f"worker-log:{request.invocation_id}:{kind}",
                    data={"kind": kind, "invocation_id": str(request.invocation_id)},
                    artifact_refs=(reference,),
                ),
            )
