"""Bounded deterministic verification contracts; no caller-selected working directory."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, field_validator, model_validator

from jarvis_contracts.base import ContractModel

ParserKind = Literal[
    "exit_code",
    "pytest",
    "vitest",
    "playwright",
    "typescript",
    "next",
    "eslint",
    "ruff",
    "mypy",
]
EnvironmentKey = Literal["CI", "NO_COLOR", "FORCE_COLOR", "TZ", "PYTHONDONTWRITEBYTECODE"]
ExecutionProfileKey = Literal["python-pytest-v1", "node-build-v1", "browser-acceptance-v1"]
VerificationPurpose = Literal["build", "unit", "browser", "quality", "integration"]


class ResourceBounds(ContractModel):
    cpu_count: int = Field(default=1, ge=1, le=8)
    memory_mb: int = Field(default=512, ge=128, le=8192)
    pids: int = Field(default=128, ge=16, le=1024)
    workspace_mb: int = Field(default=256, ge=16, le=4096)
    timeout_seconds: int = Field(default=1200, ge=1, le=86400)
    output_bytes: int = Field(default=1048576, ge=1024, le=1048576)


class DependencyPolicy(ContractModel):
    manager: Literal["none", "pip", "npm"] = "none"
    lockfiles: tuple[Literal["requirements.lock", "package-lock.json"], ...] = ()
    require_lockfile: bool = True
    require_integrity: bool = True
    lifecycle_scripts: Literal["deny"] = "deny"
    registry_allowlist: tuple[Annotated[str, Field(pattern=r"^[a-z0-9.-]+$")], ...] = ()
    cache_max_mb: int = Field(default=512, ge=0, le=4096)


class NetworkPolicy(ContractModel):
    preparation: Literal["none", "registry_allowlist"] = "none"
    verification: Literal["none", "application_loopback"] = "none"
    deny_host: Literal[True] = True
    deny_lan: Literal[True] = True
    deny_metadata: Literal[True] = True
    deny_public_internet: Literal[True] = True


class ExecutionProfileSpec(ContractModel):
    """Versioned public profile policy. Runtime evidence binds its resolved image ID."""

    kind: Literal["execution_profile"] = "execution_profile"
    profile_key: ExecutionProfileKey
    profile_version: Literal["1.0"] = "1.0"
    project_types: tuple[Literal["python", "node", "full_stack"], ...] = Field(min_length=1)
    image_reference: str = Field(min_length=1, max_length=300)
    supported_commands: tuple[str, ...] = Field(min_length=1, max_length=32)
    tool_versions: dict[str, Annotated[str, Field(min_length=1, max_length=80)]] = Field(
        min_length=1, max_length=32
    )
    resources: ResourceBounds = Field(default_factory=ResourceBounds)
    dependencies: DependencyPolicy = Field(default_factory=DependencyPolicy)
    network: NetworkPolicy = Field(default_factory=NetworkPolicy)
    max_files: int = Field(default=1000, ge=1, le=10000)
    max_source_bytes: int = Field(default=4194304, ge=1024, le=67108864)
    source_formats: tuple[str, ...] = Field(min_length=1, max_length=64)

    @field_validator("supported_commands")
    @classmethod
    def unique_commands(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value) or any(not item or len(item) > 80 for item in value):
            raise ValueError("profile declarations must contain unique bounded tokens")
        return value

    @field_validator("source_formats")
    @classmethod
    def unique_formats(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value) or any(len(item) > 20 for item in value):
            raise ValueError("profile source formats must be unique and bounded")
        return value

    @model_validator(mode="after")
    def coherent_policy(self) -> ExecutionProfileSpec:
        if self.dependencies.manager == "none" and self.dependencies.lockfiles:
            raise ValueError("dependency-free profile cannot declare lockfiles")
        if self.dependencies.manager != "none" and not self.dependencies.lockfiles:
            raise ValueError("dependency manager requires a lockfile declaration")
        if self.network.preparation == "registry_allowlist" and not (
            self.dependencies.manager != "none" and self.dependencies.registry_allowlist
        ):
            raise ValueError("registry preparation requires a dependency manager and allowlist")
        if self.profile_key == "browser-acceptance-v1" and (
            "playwright" not in self.supported_commands
            or self.network.verification != "application_loopback"
        ):
            raise ValueError("browser profile requires Playwright and loopback-only verification")
        return self


class ResolvedExecutionProfile(ContractModel):
    revision_id: UUID
    spec: ExecutionProfileSpec
    profile_digest: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    image_id: Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]
    resolved_tool_versions: dict[str, str] = Field(min_length=1, max_length=32)


class ExecutionProfileTemplatePage(ContractModel):
    items: tuple[ExecutionProfileSpec, ...]


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
    purpose: VerificationPurpose = "unit"
    profile_revision_id: UUID | None = None
    required_check_id: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_.-]{0,79}$")
    require_nonempty_suite: bool = False
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
            "node",
            "npx",
            "playwright",
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


class RequiredAcceptanceCheck(ContractModel):
    check_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,79}$")
    purpose: VerificationPurpose
    profile_revision_id: UUID
    command: VerificationCommand

    @model_validator(mode="after")
    def command_identity(self) -> RequiredAcceptanceCheck:
        if (
            self.command.required_check_id != self.check_id
            or self.command.profile_revision_id != self.profile_revision_id
            or self.command.purpose != self.purpose
        ):
            raise ValueError("required check identity must match its immutable command")
        if self.purpose in {"unit", "browser"} and not self.command.require_nonempty_suite:
            raise ValueError("required test suites must prove a non-empty result")
        if self.purpose == "browser" and self.command.parser != "playwright":
            raise ValueError("required browser checks must use the Playwright result parser")
        return self


class ParsedVerification(ContractModel):
    parser: ParserKind
    confidence: Literal["summary", "exit_code"]
    passed: int | None = Field(default=None, ge=0)
    failed: int | None = Field(default=None, ge=0)
    skipped: int | None = Field(default=None, ge=0)
    errors: int | None = Field(default=None, ge=0)
    summary: str = Field(max_length=1000)
    complete: bool = True


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
    profile_revision_id: UUID | None = None
    profile_digest: Digest | None = None
    image_id: str | None = Field(default=None, pattern=r"^sha256:[a-f0-9]{64}$")
    dependency_digest: Digest | None = None
    command_digest: Digest | None = None
    required_checks_digest: Digest | None = None
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


class DependencyPreparationEvidence(ContractModel):
    id: UUID
    snapshot_id: UUID
    source_sha: Sha
    profile_revision_id: UUID
    profile_digest: Digest
    image_id: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    lockfile_path: str = Field(min_length=1, max_length=512)
    lockfile_digest: Digest
    dependency_digest: Digest
    registry_hosts: tuple[str, ...]
    lifecycle_scripts: Literal["denied"] = "denied"
    status: Literal["prepared", "failed", "unknown"]
    output_artifact_id: UUID | None = None
    output_truncated: bool = False
    started_at: AwareDatetime
    finished_at: AwareDatetime | None = None


class RepositoryContextEntry(ContractModel):
    path: str = Field(min_length=1, max_length=1024)
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    content_digest: Digest
    provenance: Literal["source", "manifest", "test", "brief", "directive", "decision", "outcome"]


class RepositoryContextSnapshot(ContractModel):
    id: UUID
    repository_id: UUID
    run_id: UUID
    source_sha: Sha
    tree_sha: Sha
    selection: Literal["full", "bounded"]
    coverage: Literal["complete", "sufficient", "insufficient"]
    entries: tuple[RepositoryContextEntry, ...] = Field(max_length=512)
    omitted_paths: tuple[str, ...] = Field(max_length=512)
    selection_policy: str = Field(min_length=1, max_length=120)
    context_digest: Digest
    created_at: AwareDatetime


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
