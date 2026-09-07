"""Authentication facts written through the append-only event repository."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from jarvis_api.events.normalizer import EventIntent, EventNormalizer, EventWriter
from jarvis_api.events.redaction import RecursiveRedactor
from jarvis_contracts.base import ContractModel
from jarvis_contracts.enums import EventCategory, EventMode, EventSeverity, EventVisibility
from jarvis_contracts.event_registry import event_definition
from jarvis_contracts.events import EventSource
from jarvis_persistence.repositories import EventRepository


class AuthAuditWriter:
    def __init__(self, *, instance_id: str, repository: EventRepository | None = None) -> None:
        self._instance_id = instance_id
        self._repository = repository or EventRepository()
        self._writer = EventWriter(
            normalizer=EventNormalizer(
                redactor=RecursiveRedactor(),
                artifact_sink=None,
                inline_bytes=32_768,
                max_bytes=65_536,
            ),
            repository=self._repository,
        )

    async def append(
        self,
        session: AsyncSession,
        *,
        event_type: str,
        payload: ContractModel,
        occurred_at: datetime,
        correlation_id: str,
        severity: EventSeverity,
        source_kind: str = "api",
        source_name: str = "authentication",
    ) -> None:
        definition = event_definition(event_type)
        if definition is None or definition.category is not EventCategory.AUTH:
            raise ValueError(f"unregistered authentication event: {event_type}")
        if definition.payload_model is not None and not isinstance(
            payload, definition.payload_model
        ):
            raise TypeError(f"invalid payload for authentication event: {event_type}")
        await self._writer.append(
            session,
            EventIntent(
                occurred_at=occurred_at,
                category=EventCategory.AUTH,
                type=event_type,
                severity=severity,
                message=definition.default_message,
                mode=EventMode.REAL,
                visibility=EventVisibility.OWNER,
                source=EventSource(
                    kind=source_kind,
                    name=source_name,
                    instance_id=self._instance_id,
                ),
                correlation_id=correlation_id,
                data=payload.model_dump(mode="json"),
            ),
        )
