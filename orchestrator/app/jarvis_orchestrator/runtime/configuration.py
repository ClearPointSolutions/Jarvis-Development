"""Private composition manifest; never included in API/generated contracts."""

from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from jarvis_contracts.verification import VerificationCommand
from jarvis_contracts.workers import WorkerProject
from jarvis_orchestrator.providers.configuration import ProviderRuntimeConfig
from jarvis_orchestrator.providers.worker_configuration import OpenHandsDeployment


class RepositoryBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)
    worker_revision_id: UUID
    project: WorkerProject
    combined_commands: tuple[VerificationCommand, ...] = Field(min_length=1, max_length=32)


class VerificationIsolation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)
    broker_argv: tuple[str, ...] = Field(min_length=1, max_length=32)
    image_id: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")

    @field_validator("broker_argv")
    @classmethod
    def configured_command(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not Path(value[0]).is_absolute() or any("\x00" in item for item in value):
            raise ValueError("verification broker requires a server-configured absolute executable")
        return value


class RealRuntimeConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)
    schema_version: str = Field(default="1.0", pattern=r"^1\.0$")
    providers: ProviderRuntimeConfig = Field(default_factory=ProviderRuntimeConfig)
    workers: dict[UUID, OpenHandsDeployment] = Field(default_factory=dict, repr=False)
    credential_files: dict[str, Path] = Field(default_factory=dict, repr=False)
    allowed_worker_hosts: tuple[str, ...] = ()
    workflows: dict[UUID, RepositoryBinding] = Field(default_factory=dict)
    project_workflows: dict[UUID, dict[UUID, RepositoryBinding]] = Field(default_factory=dict)
    source_root: Path
    verification_isolation: VerificationIsolation
    executables: dict[str, tuple[str, ...]]
    executable_path: str
    git_executable: Path
    ssh_executable: Path
    git_author_name: str = Field(min_length=1, max_length=120)
    git_author_email: str = Field(min_length=1, max_length=200)

    def repository_binding(self, project_id: UUID, workflow_id: UUID) -> RepositoryBinding:
        binding = self.project_workflows.get(project_id, {}).get(workflow_id)
        if binding is None:
            binding = self.workflows.get(workflow_id)
        if binding is None:
            raise ValueError("project/workflow has no server-side repository binding")
        if binding.project.project_id != project_id:
            raise ValueError("project does not match repository binding")
        return binding

    @field_validator("source_root", "git_executable", "ssh_executable")
    @classmethod
    def absolute_path(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError("runtime filesystem paths must be absolute")
        return value

    @field_validator("credential_files")
    @classmethod
    def absolute_credentials(cls, value: dict[str, Path]) -> dict[str, Path]:
        if any(not path.is_absolute() for path in value.values()):
            raise ValueError("credential paths must be absolute")
        return value

    @classmethod
    def load(cls, path: Path) -> "RealRuntimeConfiguration":
        with path.open("rb") as source:
            content = source.read(1048577)
        if len(content) > 1048576:
            raise ValueError("runtime manifest exceeds 1 MiB")
        return cls.model_validate_json(content)
