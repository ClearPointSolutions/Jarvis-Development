"""Immutable digest-addressed storage used by the event normalizer."""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from uuid6 import uuid7

from jarvis_contracts.events import ArtifactReference, EventScope
from jarvis_contracts.ids import ArtifactId
from jarvis_persistence.models import ArtifactModel


class EventArtifactSink(Protocol):
    async def put(
        self,
        session: AsyncSession,
        *,
        content: bytes,
        scope: EventScope,
        relation: str,
        media_type: str,
    ) -> ArtifactReference: ...


class LocalEventArtifactStore:
    """Write redacted bytes under a server-selected, content-addressed path."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    async def put(
        self,
        session: AsyncSession,
        *,
        content: bytes,
        scope: EventScope,
        relation: str,
        media_type: str,
    ) -> ArtifactReference:
        digest = hashlib.sha256(content).hexdigest()
        security_scope = "system"
        for label, identifier in (
            ("run", scope.run_id),
            ("job", scope.job_id),
            ("project", scope.project_id),
        ):
            if identifier is not None:
                security_scope = f"{label}-{identifier}"
                break
        storage_key = f"events/{security_scope}/{digest[:2]}/{digest}"
        target = (self._root / storage_key).resolve()
        if not target.is_relative_to(self._root):
            raise ValueError("artifact storage key escaped the configured root")
        target.parent.mkdir(parents=True, exist_ok=True)
        self._write_once(Path(_native_link_path(str(target))), content)

        artifact_id = uuid7()
        inserted_id = await session.scalar(
            insert(ArtifactModel)
            .values(
                id=artifact_id,
                run_id=scope.run_id,
                task_attempt_id=scope.task_attempt_id,
                kind="event_payload",
                storage_key=storage_key,
                sha256=digest,
                size_bytes=len(content),
                media_type=media_type,
                redaction_classification="redacted",
            )
            .on_conflict_do_nothing(index_elements=[ArtifactModel.storage_key])
            .returning(ArtifactModel.id)
        )
        if inserted_id is None:
            inserted_id = await session.scalar(
                select(ArtifactModel.id).where(ArtifactModel.storage_key == storage_key)
            )
        if inserted_id is None:
            raise RuntimeError("artifact metadata disappeared after deduplication")
        return ArtifactReference(artifact_id=ArtifactId(inserted_id), relation=relation)

    @staticmethod
    def _write_once(path: Path, content: bytes) -> None:
        # Publish only a fully written file. Concurrent readers never see partial bytes.
        descriptor, temporary = tempfile.mkstemp(prefix=".event-", dir=path.parent)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(_native_link_path(temporary), _native_link_path(str(path)))
            except FileExistsError:
                if hashlib.sha256(path.read_bytes()).hexdigest() != path.name:
                    raise OSError("immutable artifact content does not match its digest") from None
        finally:
            os.unlink(temporary)


def _native_link_path(value: str) -> str:
    # CreateHardLinkW retains MAX_PATH unless paths use the extended namespace.
    # Artifact scopes/digests can exceed it under a deep Windows checkout.
    if os.name != "nt" or value.startswith("\\\\?\\"):
        return value
    if value.startswith("\\\\"):
        return "\\\\?\\UNC\\" + value[2:]
    return "\\\\?\\" + value


def artifact_path(root: Path, storage_key: str) -> Path:
    """Resolve a persisted key for authorized readers without accepting traversal."""

    resolved_root = root.resolve()
    target = (resolved_root / storage_key).resolve()
    if not target.is_relative_to(resolved_root):
        raise ValueError("artifact key escaped the configured root")
    return Path(_native_link_path(str(target)))


def artifact_scope_key(scope: EventScope) -> UUID | None:
    """Expose the authorization scope without exposing a filesystem path."""

    return UUID(str(scope.run_id)) if scope.run_id is not None else None
