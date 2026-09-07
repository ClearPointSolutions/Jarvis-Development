"""Workflow Studio wire contracts. The editor stores the canonical WorkflowSpec."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, JsonValue, model_validator

from jarvis_contracts.base import ContractModel, sha256_digest
from jarvis_contracts.registry import RegistrySpec
from jarvis_contracts.workflow import COMPILER_VERSION, WorkflowSpec


class WorkflowPosition(ContractModel):
    x: float = Field(ge=-100000, le=100000, allow_inf_nan=False)
    y: float = Field(ge=-100000, le=100000, allow_inf_nan=False)


class WorkflowViewport(WorkflowPosition):
    zoom: float = Field(default=1, ge=0.1, le=4, allow_inf_nan=False)


class WorkflowLayout(ContractModel):
    nodes: dict[str, WorkflowPosition] = Field(default_factory=dict, max_length=500)
    viewport: WorkflowViewport | None = None


class WorkflowIssue(ContractModel):
    code: str
    message: str
    node_id: str | None = None
    edge_id: str | None = None
    path: str | None = None


class WorkflowValidationReport(ContractModel):
    valid: bool
    issues: tuple[WorkflowIssue, ...] = ()
    content_hash: str | None = None
    snapshot_hash: str | None = None


class WorkflowResolvedRevision(ContractModel):
    revision_id: UUID
    configuration_id: UUID
    key: str
    revision: int = Field(ge=1)
    display_name: str
    description: str = ""
    enabled: bool = True
    archived: bool = False
    spec: RegistrySpec
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class WorkflowResolvedSnapshot(ContractModel):
    workflow_content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    compiler_version: Literal["1.0.0"] = COMPILER_VERSION
    revisions: tuple[WorkflowResolvedRevision, ...] = ()

    @property
    def snapshot_hash(self) -> str:
        return sha256_digest(
            {
                "workflow_content_hash": self.workflow_content_hash,
                "compiler_version": self.compiler_version,
                "revisions": [
                    r.model_dump(mode="json")
                    for r in sorted(self.revisions, key=lambda r: str(r.revision_id))
                ],
            }
        )


class WorkflowCommand(ContractModel):
    expected_version: int = Field(ge=0)
    idempotency_key: str = Field(min_length=8, max_length=120)


class WorkflowCreateRequest(ContractModel):
    key: str = Field(min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9_-]*$")
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=2000)
    idempotency_key: str = Field(min_length=8, max_length=120)


class WorkflowDraftWrite(WorkflowCommand):
    spec: WorkflowSpec
    layout: WorkflowLayout = Field(default_factory=WorkflowLayout)


class WorkflowValidateRequest(WorkflowCommand):
    # Accept malformed drafts here so schema failures can be addressed to canvas IDs.
    spec: dict[str, JsonValue]
    layout: dict[str, JsonValue] = Field(default_factory=dict)


class WorkflowNewDraft(WorkflowCommand):
    source_version_id: UUID | None = None


class WorkflowArchiveRequest(WorkflowCommand):
    archived: bool


class WorkflowTemplateRecord(ContractModel):
    id: UUID
    key: str
    name: str
    description: str
    version: int
    archived: bool
    current_draft_version_id: UUID | None = None
    current_published_version_id: UUID | None = None
    created_at: datetime
    updated_at: datetime


class WorkflowVersionRecord(ContractModel):
    id: UUID
    workflow_template_id: UUID
    version: int
    spec: WorkflowSpec
    layout: WorkflowLayout
    content_hash: str
    compiler_version: str
    published: bool
    created_at: datetime
    published_at: datetime | None = None
    snapshot_hash: str | None = None

    @model_validator(mode="after")
    def consistent_hash(self) -> "WorkflowVersionRecord":
        if self.content_hash != self.spec.content_hash:
            raise ValueError("Workflow content hash does not match")
        return self


class WorkflowDocument(ContractModel):
    template: WorkflowTemplateRecord
    version: WorkflowVersionRecord


class WorkflowTemplatePage(ContractModel):
    items: tuple[WorkflowTemplateRecord, ...]
    next_after: UUID | None = None


class WorkflowVersionPage(ContractModel):
    items: tuple[WorkflowVersionRecord, ...]
    next_after: UUID | None = None


class WorkflowAuditData(ContractModel):
    template_id: UUID
    version_id: UUID | None = None
    actor_id: UUID
    action: Literal["created", "revised", "validated", "published", "archived", "restored"]
    valid: bool | None = None
    content_hash: str | None = None
