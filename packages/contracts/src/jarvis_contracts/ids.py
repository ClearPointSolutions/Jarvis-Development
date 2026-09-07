"""Domain identity types and UUIDv7 generation."""

from __future__ import annotations

from typing import NewType, Protocol
from uuid import UUID

from uuid6 import uuid7

UserId = NewType("UserId", UUID)
ProjectId = NewType("ProjectId", UUID)
ThreadId = NewType("ThreadId", UUID)
MessageId = NewType("MessageId", UUID)
ConfigurationId = NewType("ConfigurationId", UUID)
ConfigurationRevisionId = NewType("ConfigurationRevisionId", UUID)
WorkflowTemplateId = NewType("WorkflowTemplateId", UUID)
WorkflowVersionId = NewType("WorkflowVersionId", UUID)
RunSnapshotId = NewType("RunSnapshotId", UUID)
JobId = NewType("JobId", UUID)
RunId = NewType("RunId", UUID)
TaskId = NewType("TaskId", UUID)
TaskAttemptId = NewType("TaskAttemptId", UUID)
NodeExecutionId = NewType("NodeExecutionId", UUID)
CommandId = NewType("CommandId", UUID)
LeaseId = NewType("LeaseId", UUID)
EffectId = NewType("EffectId", UUID)
FailureId = NewType("FailureId", UUID)
ArtifactId = NewType("ArtifactId", UUID)
EventId = NewType("EventId", UUID)
IdempotencyRecordId = NewType("IdempotencyRecordId", UUID)


class IdFactory[DomainId](Protocol):
    def __call__(self, value: UUID, /) -> DomainId: ...


def new_id[DomainId](id_type: IdFactory[DomainId]) -> DomainId:
    """Generate a time-sortable UUIDv7 and cast it to a domain-specific ID."""

    return id_type(uuid7())
