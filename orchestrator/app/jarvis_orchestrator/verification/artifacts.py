"""M8 evidence uses the existing immutable, scoped artifact and event store."""

import hashlib
import json
from pathlib import Path
from typing import cast
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jarvis_api.events.artifacts import LocalEventArtifactStore, artifact_path
from jarvis_api.events.normalizer import EventIntent
from jarvis_api.events.redaction import RecursiveRedactor
from jarvis_contracts.base import canonical_json
from jarvis_contracts.enums import EventMode, EventSeverity, EventVisibility
from jarvis_contracts.events import EventScope, EventSource
from jarvis_orchestrator.runtime.ownership import RunFence, RunOwnership
from jarvis_persistence.models import ArtifactModel, RunModel, TaskAttemptModel, TaskModel


class EvidenceArtifacts:
    def __init__(self, ownership: RunOwnership, fence: RunFence, root: Path) -> None:
        self.ownership, self.fence = ownership, fence
        self.store = LocalEventArtifactStore(root)
        self.root = root

    async def read(self, artifact_id: UUID) -> JsonValue:
        async with self.ownership.fenced(self.fence) as (session, run):
            row = await session.get(ArtifactModel, artifact_id)
            if (
                row is None
                or row.run_id != run.id
                or row.redaction_classification != "redacted"
                or row.size_bytes > 8388608
            ):
                raise ValueError("evidence artifact scope or size denied")
            with artifact_path(self.root, row.storage_key).open("rb") as stream:
                content = stream.read(row.size_bytes + 1)
            if len(content) != row.size_bytes or hashlib.sha256(content).hexdigest() != row.sha256:
                raise ValueError("immutable evidence artifact digest mismatch")
        return cast(JsonValue, json.loads(content)["content"])

    async def put(
        self, session: AsyncSession, run: RunModel, attempt_id: UUID, kind: str, content: JsonValue
    ) -> UUID:
        owned = await session.scalar(
            select(TaskAttemptModel.id)
            .join(TaskModel, TaskModel.id == TaskAttemptModel.task_id)
            .where(TaskAttemptModel.id == attempt_id, TaskModel.run_id == run.id)
        )
        if owned is None or run.id != self.fence.run_id:
            raise ValueError("evidence attempt scope mismatch")
        safe = canonical_json({"kind": kind, "content": RecursiveRedactor().redact(content).value})
        if len(safe) > 8388608:
            raise ValueError("evidence artifact exceeds the configured V1 limit")
        scope = EventScope(run_id=run.id, task_attempt_id=attempt_id)
        reference = await self.store.put(
            session, content=safe, scope=scope, relation=kind, media_type="application/json"
        )
        for event_type in ("artifact.created", "artifact.verified"):
            await self.ownership.writer.append(
                session,
                EventIntent(
                    occurred_at=self.ownership.clock.now(),
                    type=event_type,
                    severity=EventSeverity.INFO,
                    mode=EventMode(run.mode),
                    visibility=EventVisibility.OWNER,
                    scope=scope,
                    source=EventSource(kind="orchestrator", name="verification"),
                    correlation_id=str(run.id),
                    data={"kind": kind, "artifact_id": str(reference.artifact_id)},
                    artifact_refs=(reference,),
                ),
            )
        return UUID(str(reference.artifact_id))
