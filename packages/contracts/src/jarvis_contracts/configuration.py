"""Immutable configuration revision and resolved run snapshot contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, JsonValue, model_validator

from jarvis_contracts.base import ContractModel, sha256_digest
from jarvis_contracts.enums import ConfigurationKind
from jarvis_contracts.ids import (
    ConfigurationId,
    ConfigurationRevisionId,
    RunSnapshotId,
    WorkflowVersionId,
)


class ConfigurationRevision(ContractModel):
    id: ConfigurationRevisionId
    configuration_id: ConfigurationId
    kind: ConfigurationKind
    key: str = Field(min_length=1, max_length=120, pattern=r"^[a-z][a-z0-9_-]*$")
    revision: Annotated[int, Field(gt=0)]
    schema_version: Literal["1.0"] = "1.0"
    spec: dict[str, JsonValue]
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    created_at: datetime

    def hash_payload(self) -> dict[str, JsonValue]:
        return {
            "kind": self.kind.value,
            "key": self.key,
            "revision": self.revision,
            "schema_version": self.schema_version,
            "spec": self.spec,
        }

    @model_validator(mode="after")
    def verify_hash(self) -> ConfigurationRevision:
        if self.content_hash != sha256_digest(self.hash_payload()):
            raise ValueError("configuration content_hash does not match canonical revision")
        return self


class ResolvedRevision(ContractModel):
    kind: ConfigurationKind
    key: str
    revision_id: ConfigurationRevisionId
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class RunConfigurationSnapshot(ContractModel):
    id: RunSnapshotId
    schema_version: Literal["1.0"] = "1.0"
    workflow_version_id: WorkflowVersionId
    workflow_content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    resolved_revisions: tuple[ResolvedRevision, ...]
    effective_spec: dict[str, JsonValue]
    snapshot_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    created_at: datetime

    def hash_payload(self) -> dict[str, JsonValue]:
        return {
            "schema_version": self.schema_version,
            "workflow_version_id": str(self.workflow_version_id),
            "workflow_content_hash": self.workflow_content_hash,
            "resolved_revisions": [
                revision.model_dump(mode="json") for revision in self.resolved_revisions
            ],
            "effective_spec": self.effective_spec,
        }

    @model_validator(mode="after")
    def verify_hash(self) -> RunConfigurationSnapshot:
        if self.snapshot_hash != sha256_digest(self.hash_payload()):
            raise ValueError("snapshot_hash does not match canonical resolved configuration")
        return self
