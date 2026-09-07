"""Validate producer intents, redact them, and extract oversized event data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from pydantic import Field, JsonValue, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jarvis_api.events.artifacts import EventArtifactSink
from jarvis_api.events.redaction import RecursiveRedactor
from jarvis_contracts.base import ContractModel, canonical_json
from jarvis_contracts.enums import EventCategory, EventMode, EventSeverity, EventVisibility
from jarvis_contracts.event_registry import event_definition
from jarvis_contracts.events import (
    ArtifactReference,
    EventScope,
    EventSource,
    EventTrace,
    NewEvent,
    NormalizedEvent,
)
from jarvis_contracts.ids import EventId
from jarvis_persistence.models import EventGlobalCounterModel
from jarvis_persistence.repositories import EventRepository


class UnknownEventTypeError(ValueError):
    """A producer attempted to persist an unregistered event type."""


class EventCategoryMismatchError(ValueError):
    """An event type was paired with the wrong stable category."""


class ArtifactExtractionRequiredError(ValueError):
    """Oversized redacted content cannot be persisted without an artifact sink."""


class EventIntent(ContractModel):
    """Unpersisted producer input; unlike NewEvent it may contain extractable content."""

    schema_version: str = Field(default="1.0", pattern=r"^\d+\.\d+$", max_length=20)
    occurred_at: datetime
    category: EventCategory | None = None
    type: str = Field(
        min_length=3,
        max_length=160,
        pattern=r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$",
    )
    severity: EventSeverity
    message: str | None = Field(default=None, max_length=16_384)
    mode: EventMode
    visibility: EventVisibility
    scope: EventScope = Field(default_factory=EventScope)
    source: EventSource
    correlation_id: str = Field(min_length=1, max_length=200)
    causation_event_id: EventId | None = None
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=200)
    trace: EventTrace | None = None
    data: dict[str, JsonValue]
    artifact_refs: tuple[ArtifactReference, ...] = ()

    @field_validator("occurred_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("event timestamps must include a timezone")
        return value


@dataclass(frozen=True)
class PreparedEvent:
    event: NewEvent
    redaction_rule_counts: dict[str, int]
    extracted: bool


@dataclass(frozen=True)
class WrittenEvent:
    event: NormalizedEvent
    redaction_rule_counts: dict[str, int]
    extracted: bool


class EventNormalizer:
    """Single producer boundary for schemas, redaction, summaries, and size rules."""

    def __init__(
        self,
        *,
        redactor: RecursiveRedactor,
        artifact_sink: EventArtifactSink | None,
        inline_bytes: int,
        max_bytes: int,
    ) -> None:
        if inline_bytes < 1 or inline_bytes >= max_bytes:
            raise ValueError("inline event limit must be positive and below maximum size")
        if max_bytes > 65_536:
            raise ValueError("event maximum cannot exceed the V1 64 KiB contract")
        self._redactor = redactor
        self._artifacts = artifact_sink
        self._inline_bytes = inline_bytes
        self._max_bytes = max_bytes

    async def prepare(self, session: AsyncSession, intent: EventIntent) -> PreparedEvent:
        if intent.schema_version.partition(".")[0] != "1":
            raise ValueError(f"unsupported producer event schema {intent.schema_version}")
        definition = event_definition(intent.type)
        if definition is None:
            raise UnknownEventTypeError(f"event type {intent.type!r} is not registered")
        if intent.category is not None and intent.category != definition.category:
            raise EventCategoryMismatchError(
                f"event type {intent.type!r} belongs to category {definition.category.value!r}"
            )

        redacted_report = self._redactor.redact(intent.data)
        if not isinstance(redacted_report.value, dict):
            raise TypeError("event payload redaction did not return an object")
        redacted_data = redacted_report.value
        if definition.payload_model is not None:
            validated = definition.payload_model.model_validate(redacted_data)
            redacted_data = validated.model_dump(mode="json")

        source_report = self._redactor.redact(intent.source.model_dump(mode="json"))
        if not isinstance(source_report.value, dict):
            raise TypeError("event source redaction did not return an object")
        source = EventSource.model_validate(source_report.value)

        raw_message = definition.default_message
        message, message_counts = self._redactor.redact_text(raw_message)
        if len(message) > 1_024:
            message = f"{message[:1021]}..."

        metadata_counts: dict[str, int] = {}

        def safe_metadata(value: str) -> str:
            redacted, rule_counts = self._redactor.redact_text(value)
            self._merge_counts(metadata_counts, rule_counts)
            return redacted

        artifact_refs = [
            ArtifactReference(
                artifact_id=reference.artifact_id,
                relation=safe_metadata(reference.relation),
            )
            for reference in intent.artifact_refs
        ]
        workflow_node_id = intent.scope.workflow_node_id
        if workflow_node_id is not None:
            redacted_node_id = safe_metadata(workflow_node_id)
            # Scope identity is verified against the producer's original value by
            # EventWriter. Omit a sensitive label instead of inventing an identity
            # that no longer matches the referenced node execution.
            if redacted_node_id != workflow_node_id:
                workflow_node_id = None
        safe_scope = EventScope.model_validate(
            intent.scope.model_dump(mode="json") | {"workflow_node_id": workflow_node_id}
        )
        extracted = False
        encoded_data = canonical_json(redacted_data)
        if len(encoded_data) > self._inline_bytes:
            if self._artifacts is None:
                raise ArtifactExtractionRequiredError(
                    "oversized event content requires an artifact sink"
                )
            reference = await self._artifacts.put(
                session,
                content=encoded_data,
                scope=intent.scope,
                relation="data",
                media_type="application/json",
            )
            artifact_refs.append(reference)
            redacted_data = {
                "content_extracted": True,
                "artifact_id": str(reference.artifact_id),
                "original_size_bytes": len(encoded_data),
            }
            extracted = True

        counts = dict(redacted_report.rule_counts)
        self._merge_counts(counts, source_report.rule_counts)
        self._merge_counts(counts, message_counts)
        event = NewEvent(
            occurred_at=intent.occurred_at,
            category=definition.category,
            type=intent.type,
            severity=intent.severity,
            message=message,
            mode=intent.mode,
            visibility=intent.visibility,
            scope=safe_scope,
            source=source,
            correlation_id=safe_metadata(intent.correlation_id),
            causation_event_id=intent.causation_event_id,
            idempotency_key=(
                safe_metadata(intent.idempotency_key)
                if intent.idempotency_key is not None
                else None
            ),
            trace=intent.trace,
            data=redacted_data,
            artifact_refs=tuple(artifact_refs),
        )
        self._merge_counts(counts, metadata_counts)
        # Reserve ordering/timestamp/UUID overhead added by persistence.
        if len(canonical_json(event)) + 256 > self._max_bytes:
            raise ValueError("normalized event exceeds the configured persistence limit")
        return PreparedEvent(
            event=event,
            redaction_rule_counts=counts,
            extracted=extracted,
        )

    @staticmethod
    def _merge_counts(target: dict[str, int], additions: dict[str, int]) -> None:
        for rule, count in additions.items():
            target[rule] = target.get(rule, 0) + count


class EventWriter:
    """Required application path from untrusted producer intent to immutable row."""

    def __init__(self, *, normalizer: EventNormalizer, repository: EventRepository) -> None:
        self._normalizer = normalizer
        self._repository = repository

    async def append(self, session: AsyncSession, intent: EventIntent) -> WrittenEvent:
        # Artifacts can acquire unique-key locks, so take the global lock before
        # normalization too. Every event producer follows this same lock order.
        await session.scalar(
            select(EventGlobalCounterModel).where(EventGlobalCounterModel.id == 1).with_for_update()
        )
        await self._repository.validate_scope(session, intent.scope, intent.artifact_refs)
        prepared = await self._normalizer.prepare(session, intent)
        written = await self._repository.append(session, prepared.event)
        return WrittenEvent(
            event=written,
            redaction_rule_counts=prepared.redaction_rule_counts,
            extracted=prepared.extracted,
        )
