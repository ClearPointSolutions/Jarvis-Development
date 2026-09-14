"""Phase 1 durable mission, manager conversation, and backlog contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from jarvis_contracts.base import ContractModel

MissionLifecycle = Literal["active", "waiting", "blocked", "completed", "archived"]
WorkItemLifecycle = Literal["pending", "ready", "started", "accepted", "blocked", "cancelled"]
ManagerAction = Literal["explain", "propose", "clarify", "wait"]
ConstraintText = Annotated[str, Field(min_length=1, max_length=2000)]
WorkItemKey = Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_-]{1,39}$")]


class FixedTeamSelection(ContractModel):
    team_template_revision_id: UUID
    manager_role_revision_id: UUID
    manager_profile_revision_id: UUID
    developer_role_revision_id: UUID
    developer_worker_revision_id: UUID
    reviewer_role_revision_id: UUID
    reviewer_profile_revision_id: UUID
    workflow_version_id: UUID


class MissionCreate(ContractModel):
    project_id: UUID
    objective: str = Field(min_length=1, max_length=8000)
    constraints: tuple[ConstraintText, ...] = Field(default=(), max_length=40)
    mode: Literal["demo", "real"] = "demo"
    team_template_revision_id: UUID
    idempotency_key: str = Field(min_length=8, max_length=120)


class DirectiveUpdate(ContractModel):
    objective: str = Field(min_length=1, max_length=8000)
    constraints: tuple[ConstraintText, ...] = Field(default=(), max_length=40)
    expected_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=8, max_length=120)


class MissionView(ContractModel):
    id: UUID
    project_id: UUID
    objective: str
    constraints: tuple[str, ...]
    lifecycle: MissionLifecycle
    mode: Literal["demo", "real"]
    version: int
    directive_version: int
    team_version: int
    created_at: datetime
    updated_at: datetime


class MissionPage(ContractModel):
    items: tuple[MissionView, ...]
    next_after: UUID | None = None


class MissionMessageView(ContractModel):
    id: UUID
    sequence: int
    role: Literal["user", "manager", "system"]
    identity: str
    body: str
    directive_version: int
    management_turn_id: UUID | None = None
    disposition: Literal["queued", "delivered", "stale", "failed"] = "delivered"
    created_at: datetime


class MissionMessagePage(ContractModel):
    items: tuple[MissionMessageView, ...]
    next_after: int | None = None


class WorkItemProposal(ContractModel):
    key: WorkItemKey
    title: str = Field(min_length=1, max_length=240)
    objective: str = Field(min_length=1, max_length=4000)
    acceptance_criteria: tuple[ConstraintText, ...] = Field(min_length=1, max_length=20)
    priority: int = Field(default=0, ge=-100, le=100)
    dependencies: tuple[WorkItemKey, ...] = Field(default=(), max_length=20)


class ManagerDecision(ContractModel):
    action: ManagerAction
    message: str = Field(min_length=1, max_length=8000)
    work_items: tuple[WorkItemProposal, ...] = Field(default=(), max_length=8)
    lifecycle: Literal["active", "waiting", "blocked"] = "active"

    @model_validator(mode="after")
    def bounded_action(self) -> ManagerDecision:
        if (self.action == "propose") != bool(self.work_items):
            raise ValueError("only propose actions may contain work items")
        keys = {item.key for item in self.work_items}
        if len(keys) != len(self.work_items):
            raise ValueError("work item keys must be unique")
        if any(set(item.dependencies) - keys for item in self.work_items):
            raise ValueError("proposal dependencies must stay inside this proposal")
        edges = {item.key: set(item.dependencies) for item in self.work_items}
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(key: str) -> None:
            if key in visiting:
                raise ValueError("work item dependencies must be acyclic")
            if key in visited:
                return
            visiting.add(key)
            for dependency in edges[key]:
                visit(dependency)
            visiting.remove(key)
            visited.add(key)

        for key in keys:
            visit(key)
        return self


class MissionMessageCreate(ContractModel):
    body: str = Field(min_length=1, max_length=8000)
    expected_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=8, max_length=120)
    allow_paid_inference: bool = False


class WorkItemView(ContractModel):
    id: UUID
    key: str
    title: str
    objective: str
    acceptance_criteria: tuple[str, ...]
    priority: int
    dependencies: tuple[UUID, ...]
    lifecycle: WorkItemLifecycle
    directive_version: int
    team_version: int
    job_id: UUID | None = None
    run_id: UUID | None = None
    created_at: datetime


class WorkItemPage(ContractModel):
    items: tuple[WorkItemView, ...]
    next_after: UUID | None = None


class WorkItemStart(ContractModel):
    expected_mission_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=8, max_length=120)


class ManagementTurnView(ContractModel):
    id: UUID
    status: Literal["queued", "running", "applied", "stale", "failed"]
    directive_version: int
    team_version: int
    model_call_id: UUID | None = None
    decision: ManagerDecision | None = None
    failure_code: str | None = None
    created_at: datetime
    completed_at: datetime | None = None


class ManagementTurnPage(ContractModel):
    items: tuple[ManagementTurnView, ...]
    next_after: UUID | None = None
