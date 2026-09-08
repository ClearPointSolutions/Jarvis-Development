"""Bounded deterministic verification contracts; no caller-selected working directory."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, field_validator

from jarvis_contracts.base import ContractModel

ParserKind = Literal[
    "exit_code", "pytest", "vitest", "typescript", "next", "eslint", "ruff", "mypy"
]
EnvironmentKey = Literal["CI", "NO_COLOR", "FORCE_COLOR", "TZ", "PYTHONDONTWRITEBYTECODE"]


class VerificationCommand(ContractModel):
    kind: Literal["argv"] = "argv"
    argv: tuple[str, ...] = Field(min_length=1, max_length=64)
    timeout_seconds: int = Field(default=1200, ge=1, le=86400)
    expected_exit_codes: tuple[Annotated[int, Field(ge=0, le=255)], ...] = Field(
        default=(0,), min_length=1, max_length=8
    )
    environment: dict[EnvironmentKey, Annotated[str, Field(max_length=128)]] = Field(
        default_factory=dict, max_length=5
    )
    parser: ParserKind = "exit_code"
    working_root_policy: Literal["adapter_confirmed_root"] = "adapter_confirmed_root"
    max_output_bytes: int = Field(default=1048576, ge=1024, le=1048576)

    @field_validator("argv")
    @classmethod
    def bounded_argv(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item or len(item) > 1024 or "\x00" in item for item in value):
            raise ValueError("invalid bounded argv")
        # Tools are resolved from a server-owned executable map, never PATH or
        # a model-selected absolute executable. No shell adapter is exposed.
        if value[0] not in {
            "python",
            "pytest",
            "npm",
            "vitest",
            "tsc",
            "next",
            "eslint",
            "ruff",
            "mypy",
        }:
            raise ValueError("verification executable is not supported")
        return value

    @field_validator("environment")
    @classmethod
    def safe_environment(cls, value: dict[EnvironmentKey, str]) -> dict[EnvironmentKey, str]:
        for key, item in value.items():
            allowed = {"UTC"} if key == "TZ" else {"0", "1", "true", "false"}
            if item not in allowed:
                raise ValueError("verification environment value is not supported")
        return value


class ParsedVerification(ContractModel):
    parser: ParserKind
    confidence: Literal["summary", "exit_code"]
    passed: int | None = Field(default=None, ge=0)
    failed: int | None = Field(default=None, ge=0)
    skipped: int | None = Field(default=None, ge=0)
    errors: int | None = Field(default=None, ge=0)
    summary: str = Field(max_length=1000)


Sha = Annotated[str, Field(pattern=r"^[a-f0-9]{40}$")]
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class SealedRepositorySnapshot(ContractModel):
    id: UUID
    repository_id: UUID
    run_id: UUID
    task_attempt_id: UUID
    worker_result_id: UUID
    branch: str = Field(min_length=1, max_length=200)
    head_sha: Sha
    base_sha: Sha
    latest_base_sha: Sha
    tree_sha: Sha
    content_digest: Digest
    git_status: Literal["clean"] = "clean"
    submodules: Literal["absent"] = "absent"
    lfs: Literal["absent"] = "absent"
    file_count: int = Field(ge=0, le=10000)
    manifest_artifact_id: UUID
    source_artifact_id: UUID
    cumulative_diff_artifact_id: UUID
    latest_diff_artifact_id: UUID
    created_at: AwareDatetime


class VerificationExecution(ContractModel):
    phase: Literal["task", "integration"] = "task"
    id: UUID
    run_id: UUID
    task_id: UUID
    task_attempt_id: UUID
    snapshot_id: UUID
    source_sha: Sha
    command: VerificationCommand
    cwd: str = Field(max_length=2048)
    environment_keys: tuple[str, ...] = Field(max_length=16)
    started_at: AwareDatetime
    finished_at: AwareDatetime | None = None
    status: Literal["started", "passed", "failed", "timed_out", "unknown"]
    exit_code: int | None = None
    stdout_artifact_id: UUID | None = None
    stderr_artifact_id: UUID | None = None
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    parsed: ParsedVerification | None = None
    failure_class: str | None = Field(default=None, max_length=80)


class ReviewEvidence(ContractModel):
    objective: str = Field(max_length=16000)
    workflow_version_id: UUID
    config_snapshot_id: UUID
    task_id: UUID
    task_attempt_id: UUID
    task_title: str = Field(max_length=240)
    acceptance_criteria: tuple[Annotated[str, Field(max_length=2000)], ...] = Field(
        min_length=1, max_length=64
    )
    snapshot: SealedRepositorySnapshot
    verification_artifact_ids: tuple[UUID, ...] = Field(min_length=1, max_length=32)
    prior_feedback_artifact_ids: tuple[UUID, ...] = Field(max_length=100)
    failure_history_artifact_id: UUID
    architecture_artifact_ids: tuple[UUID, ...] = Field(default=(), max_length=32)


class ReviewFinding(ContractModel):
    criterion_index: int = Field(ge=0, le=63)
    summary: str = Field(min_length=1, max_length=2000)
    source_path: str = Field(min_length=1, max_length=1024)


class ReviewDecision(ContractModel):
    id: UUID
    task_id: UUID
    task_attempt_id: UUID
    reviewed_snapshot_id: UUID
    reviewed_head_sha: Sha
    snapshot_digest: Digest
    verdict: Literal["PASS", "FAIL"]
    summary: str = Field(min_length=1, max_length=2000)
    findings: tuple[ReviewFinding, ...] = Field(default=(), max_length=64)
    reviewer_revision: str = Field(min_length=1, max_length=160)
    started_at: AwareDatetime
    finished_at: AwareDatetime


class IntegrationHeadView(ContractModel):
    repository_id: UUID
    base_sha: Sha
    head_sha: Sha
    branch: str
    snapshot_artifact_id: UUID | None
    generation: int
    lease_owner: UUID | None
    expires_at: AwareDatetime | None
    released_at: AwareDatetime | None


class IntegrationHeadPage(ContractModel):
    items: tuple[IntegrationHeadView, ...]
    next_after: UUID | None
