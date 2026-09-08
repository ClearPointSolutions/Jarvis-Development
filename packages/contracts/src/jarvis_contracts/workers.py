"""Versioned, credential-free worker lifecycle and repository evidence contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, field_validator, model_validator

from jarvis_contracts.base import ContractModel
from jarvis_contracts.registry import Capability, HealthStatus

Sha = Annotated[str, Field(pattern=r"^[a-f0-9]{40}$")]
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
SafeKey = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")]
TerminalStatus = Literal["succeeded", "failed", "cancelled", "unknown"]
InvocationState = Literal[
    "absent", "starting", "running", "succeeded", "failed", "cancelled", "unknown"
]


def validate_branch(value: str) -> str:
    import re

    if (
        not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9/_-]{0,199}", value)
        or "//" in value
        or value.endswith("/")
        or any(part.startswith("-") for part in value.split("/"))
    ):
        raise ValueError("invalid task branch")
    return value


def validate_absolute_path(value: str) -> str:
    import re

    if not re.fullmatch(r"/(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+", value) or any(
        part in {".", ".."} for part in value.split("/")
    ):
        raise ValueError("expected canonical absolute POSIX path")
    return value


class WorkerSlotFence(ContractModel):
    lease_id: UUID
    worker_revision_id: UUID
    slot: int = Field(ge=0, le=127)
    generation: int = Field(gt=0)
    run_generation: int = Field(gt=0)
    expires_at: AwareDatetime


class WorkerVerification(ContractModel):
    kind: Literal["argv"] = "argv"
    argv: tuple[str, ...] = Field(min_length=1, max_length=64)
    timeout_seconds: int = Field(default=1200, ge=1, le=86400)

    @field_validator("argv")
    @classmethod
    def bounded_argv(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item or len(item) > 1024 or "\x00" in item for item in value):
            raise ValueError("invalid bounded argv")
        return value


class WorkerTask(ContractModel):
    key: SafeKey
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=16000)
    acceptance_criteria: tuple[Annotated[str, Field(max_length=2000)], ...] = Field(
        min_length=1, max_length=64
    )
    verification: tuple[WorkerVerification, ...] = Field(default=(), max_length=32)


class WorkerProject(ContractModel):
    project_id: UUID
    repository_id: UUID
    slug: SafeKey
    workspace_root: str = Field(max_length=1024)
    branch: str
    base_sha: Sha

    _path = field_validator("workspace_root")(validate_absolute_path)
    _branch = field_validator("branch")(validate_branch)


class WorkerLimits(ContractModel):
    max_runtime_seconds: int = Field(default=7200, ge=1, le=86400)
    max_output_bytes: int = Field(default=1048576, ge=1024, le=104857600)
    max_result_bytes: int = Field(default=65536, ge=1024, le=262144)


class WorkerInvocationRequest(ContractModel):
    protocol_version: Literal["1.0"] = "1.0"
    invocation_id: UUID
    idempotency_key: str = Field(min_length=1, max_length=200)
    run_id: UUID
    task_id: UUID
    task_attempt_id: UUID
    worker_revision_id: UUID
    lease: WorkerSlotFence
    project: WorkerProject
    objective: str = Field(min_length=1, max_length=16000)
    task: WorkerTask
    architecture_artifact_id: UUID | None = None
    feedback_artifact_ids: tuple[UUID, ...] = Field(default=(), max_length=32)
    model_profile_revision_id: UUID
    required_capabilities: tuple[Capability, ...] = Field(default=("code", "git"), max_length=64)
    limits: WorkerLimits = Field(default_factory=WorkerLimits)

    @model_validator(mode="after")
    def identity(self) -> WorkerInvocationRequest:
        if self.worker_revision_id != self.lease.worker_revision_id:
            raise ValueError("worker fence identity mismatch")
        return self


class PreparedInvocation(ContractModel):
    request: WorkerInvocationRequest
    request_digest: Digest


class WorkerInvocationHandle(ContractModel):
    invocation_id: UUID
    request_digest: Digest
    worker_revision_id: UUID
    generation: int = Field(gt=0)


class WorkerInvocationStatus(ContractModel):
    invocation_id: UUID
    state: InvocationState
    source_sequence: int = Field(default=0, ge=0)
    last_activity_at: AwareDatetime | None = None
    possibly_stalled: bool = False


class WorkerEvent(ContractModel):
    invocation_id: UUID
    source_sequence: int = Field(gt=0)
    occurred_at: AwareDatetime
    type: Literal[
        "worker.invocation_dispatched",
        "worker.heartbeat",
        "worker.invocation_completed",
        "worker.invocation_failed",
        "worker.cancel_requested",
        "worker.cancelled",
    ]


class WorkerRepositorySnapshot(ContractModel):
    head_sha: Sha
    tree_digest: Digest
    status_digest: Digest
    git_status: Literal["clean", "dirty"]
    file_count: int = Field(ge=0, le=100000)
    manifest_digest: Digest
    diff_digest: Digest
    metadata_truncated: bool = False


class WorkerArtifact(ContractModel):
    kind: Literal["stdout", "stderr", "repository"]
    sha256: Digest
    size_bytes: int = Field(ge=0, le=104857600)


class WorkerResult(ContractModel):
    protocol_version: Literal["1.0"] = "1.0"
    invocation_id: UUID
    task_id: UUID
    task_attempt_id: UUID
    request_digest: Digest
    generation: int = Field(gt=0)
    status: TerminalStatus
    workspace_root: str
    branch: str
    start_head: Sha
    end_head: Sha
    repository_snapshot: WorkerRepositorySnapshot
    artifact_manifest: tuple[WorkerArtifact, ...] = Field(max_length=16)
    summary: str = Field(max_length=1024)
    error: Annotated[str, Field(max_length=120)] | None = None
    model_profile_revision_id: UUID
    started_at: AwareDatetime
    finished_at: AwareDatetime
    source_sequence: int = Field(gt=0)

    _path = field_validator("workspace_root")(validate_absolute_path)
    _branch = field_validator("branch")(validate_branch)

    @model_validator(mode="after")
    def consistent(self) -> WorkerResult:
        if self.finished_at < self.started_at:
            raise ValueError("invalid result timestamps")
        if (self.status == "succeeded") != (self.error is None):
            raise ValueError("inconsistent result status/error")
        if self.repository_snapshot.head_sha != self.end_head:
            raise ValueError("snapshot HEAD mismatch")
        return self


class WorkerHealth(ContractModel):
    status: HealthStatus
    observed_at: datetime
    capabilities: tuple[Capability, ...] = ()
    issues: tuple[SafeKey, ...] = ()
    network_checked: bool = False


class WorkerValidationReport(ContractModel):
    valid: bool
    health: WorkerHealth
    exclusive_workspace: bool = True


class CancelResult(ContractModel):
    invocation_id: UUID
    status: Literal["cancelled", "unknown", "already_terminal"]


class ReconciliationResult(ContractModel):
    invocation_id: UUID
    state: InvocationState
    safe_to_start: bool = False

    @model_validator(mode="after")
    def safe_absence(self) -> ReconciliationResult:
        if self.safe_to_start and self.state != "absent":
            raise ValueError("only proven absence permits start")
        return self
