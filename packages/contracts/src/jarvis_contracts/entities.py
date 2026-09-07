"""Durable entity metadata exposed across API/runtime boundaries."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, JsonValue

from jarvis_contracts.base import ContractModel
from jarvis_contracts.commands import IdempotencyKey
from jarvis_contracts.enums import (
    AttemptStatus,
    CommandStatus,
    DesiredRunState,
    EffectStatus,
    JobStatus,
    RunCommandKind,
    RunStatus,
    TaskStatus,
)
from jarvis_contracts.ids import (
    ArtifactId,
    CommandId,
    EffectId,
    JobId,
    LeaseId,
    ProjectId,
    RunId,
    RunSnapshotId,
    TaskAttemptId,
    TaskId,
    ThreadId,
    WorkflowVersionId,
)


class Job(ContractModel):
    id: JobId
    project_id: ProjectId
    thread_id: ThreadId | None = None
    objective: str = Field(min_length=1, max_length=20_000)
    status: JobStatus
    created_at: datetime
    updated_at: datetime
    version: Annotated[int, Field(ge=0)]


class Run(ContractModel):
    id: RunId
    job_id: JobId
    run_number: Annotated[int, Field(gt=0)]
    workflow_version_id: WorkflowVersionId
    config_snapshot_id: RunSnapshotId
    langgraph_thread_id: str = Field(min_length=1, max_length=200)
    status: RunStatus
    desired_state: DesiredRunState
    claimable_at: datetime
    created_at: datetime
    updated_at: datetime
    version: Annotated[int, Field(ge=0)]


class Task(ContractModel):
    id: TaskId
    run_id: RunId
    key: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=240)
    status: TaskStatus
    weight: Annotated[int, Field(gt=0, le=10_000)] = 1
    acceptance_criteria: tuple[str, ...]
    verification: dict[str, JsonValue]
    created_at: datetime
    updated_at: datetime
    version: Annotated[int, Field(ge=0)]


class TaskAttempt(ContractModel):
    id: TaskAttemptId
    task_id: TaskId
    attempt_number: Annotated[int, Field(gt=0)]
    status: AttemptStatus
    base_sha: str | None = Field(default=None, pattern=r"^[a-f0-9]{40,64}$")
    result_sha: str | None = Field(default=None, pattern=r"^[a-f0-9]{40,64}$")
    started_at: datetime | None = None
    completed_at: datetime | None = None


class RunCommand(ContractModel):
    id: CommandId
    run_id: RunId
    sequence: Annotated[int, Field(gt=0)]
    kind: RunCommandKind
    status: CommandStatus
    idempotency_key: IdempotencyKey
    request_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    payload: dict[str, JsonValue]
    created_at: datetime


class Lease(ContractModel):
    id: LeaseId
    run_id: RunId
    owner_instance_id: str = Field(min_length=1, max_length=160)
    generation: Annotated[int, Field(gt=0)]
    acquired_at: datetime
    expires_at: datetime
    released_at: datetime | None = None


class Effect(ContractModel):
    id: EffectId
    run_id: RunId
    task_attempt_id: TaskAttemptId | None = None
    kind: str = Field(min_length=1, max_length=120)
    idempotency_key: IdempotencyKey
    request_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    status: EffectStatus
    fence_generation: Annotated[int, Field(gt=0)]
    external_id: str | None = Field(default=None, max_length=240)
    result: dict[str, JsonValue] | None = None
    created_at: datetime
    updated_at: datetime


class ArtifactMetadata(ContractModel):
    id: ArtifactId
    run_id: RunId | None = None
    task_attempt_id: TaskAttemptId | None = None
    kind: str = Field(min_length=1, max_length=120)
    storage_key: str = Field(min_length=1, max_length=1_024)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size_bytes: Annotated[int, Field(ge=0)]
    media_type: str = Field(min_length=1, max_length=200)
    redaction_classification: Literal["public", "owner", "sensitive", "redacted"]
    created_at: datetime
