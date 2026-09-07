"""Normalized append-only event envelope contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, JsonValue, field_validator, model_validator

from jarvis_contracts.base import ContractModel, canonical_json
from jarvis_contracts.enums import EventCategory, EventMode, EventSeverity, EventVisibility
from jarvis_contracts.ids import (
    ArtifactId,
    EventId,
    JobId,
    NodeExecutionId,
    ProjectId,
    RunId,
    TaskAttemptId,
    TaskId,
    ThreadId,
)


class EventScope(ContractModel):
    project_id: ProjectId | None = None
    thread_id: ThreadId | None = None
    job_id: JobId | None = None
    run_id: RunId | None = None
    task_id: TaskId | None = None
    task_attempt_id: TaskAttemptId | None = None
    workflow_node_id: str | None = Field(default=None, max_length=80)
    node_execution_id: NodeExecutionId | None = None


class EventSource(ContractModel):
    kind: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_-]*$")
    name: str = Field(min_length=1, max_length=120)
    instance_id: str | None = Field(default=None, max_length=160)
    host_id: str | None = Field(default=None, max_length=160)
    source_sequence: Annotated[int, Field(gt=0)] | None = None


class EventTrace(ContractModel):
    trace_id: str = Field(min_length=16, max_length=64, pattern=r"^[a-fA-F0-9]+$")
    span_id: str = Field(min_length=8, max_length=32, pattern=r"^[a-fA-F0-9]+$")


class ArtifactReference(ContractModel):
    artifact_id: ArtifactId
    relation: str = Field(min_length=1, max_length=80)


class EventCore(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    occurred_at: datetime
    category: EventCategory
    type: str = Field(
        min_length=3,
        max_length=160,
        pattern=r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$",
    )
    severity: EventSeverity
    message: str = Field(min_length=1, max_length=1_024)
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

    @model_validator(mode="after")
    def enforce_size_limit(self) -> EventCore:
        if len(canonical_json(self)) > 65_536:
            raise ValueError("event exceeds the 64 KiB persistence limit")
        return self


class NewEvent(EventCore):
    """Validated event before database ordering fields are allocated."""


class NormalizedEvent(EventCore):
    event_id: EventId
    global_position: Annotated[int, Field(gt=0)]
    run_sequence: Annotated[int, Field(gt=0)] | None = None
    recorded_at: datetime

    @field_validator("recorded_at")
    @classmethod
    def require_recorded_timezone(cls, value: datetime) -> datetime:
        return EventCore.require_timezone(value)

    @model_validator(mode="after")
    def validate_run_order(self) -> NormalizedEvent:
        if (self.scope.run_id is None) != (self.run_sequence is None):
            raise ValueError("run_id and run_sequence must be present together")
        return self
