"""Phase 1 durable mission, manager conversation, and backlog contracts."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from jarvis_contracts.base import ContractModel
from jarvis_contracts.registry import TeamBudgetPolicy, TeamMemberSpec

MissionLifecycle = Literal[
    "active",
    "idle",
    "waiting_for_capacity",
    "waiting_for_approval",
    "blocked",
    "paused",
    "cancelling",
    "cancelled",
    "completed",
    "archived",
]
WorkItemLifecycle = Literal["pending", "ready", "started", "accepted", "blocked", "cancelled"]
ManagerAction = Literal["explain", "propose", "clarify", "wait", "complete"]
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
    members: tuple[TeamMemberSpec, ...] = ()
    budgets: TeamBudgetPolicy = Field(default_factory=TeamBudgetPolicy)
    escalation_policy_revision_id: UUID | None = None
    eligible_worker_revision_ids: tuple[UUID, ...] = ()
    worker_pool_snapshot_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class MissionResourceLimits(ContractModel):
    """Conservative UTC-window limits for unattended mission activity."""

    window_seconds: int = Field(default=86_400, ge=60, le=31_536_000)
    timezone: Literal["UTC"] = "UTC"
    max_calls: int = Field(default=20, ge=0, le=1_000_000)
    max_input_tokens: int = Field(default=500_000, ge=0, le=1_000_000_000)
    max_output_tokens: int = Field(default=100_000, ge=0, le=1_000_000_000)
    max_active_jobs: int = Field(default=1, ge=0, le=128)
    max_wall_seconds: int = Field(default=86_400, ge=0, le=31_536_000)
    max_iterations: int = Field(default=20, ge=0, le=100_000)
    max_new_work_items: int = Field(default=20, ge=0, le=100_000)
    max_cost: Decimal | None = Field(default=None, ge=0, le=1_000_000)
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")


class MissionUsageView(ContractModel):
    window_started_at: datetime
    window_seconds: int
    timezone: Literal["UTC"] = "UTC"
    reserved: dict[str, int | str | None]
    actual: dict[str, int | str | None]
    unknown_liability: bool = False
    limits: MissionResourceLimits


class MissionCreate(ContractModel):
    project_id: UUID
    objective: str = Field(min_length=1, max_length=8000)
    constraints: tuple[ConstraintText, ...] = Field(default=(), max_length=40)
    mode: Literal["demo", "real"] = "demo"
    team_template_revision_id: UUID
    autonomous: bool = False
    limits: MissionResourceLimits = Field(default_factory=MissionResourceLimits)
    idempotency_key: str = Field(min_length=8, max_length=120)


class MissionTeamUpdate(ContractModel):
    team_template_revision_id: UUID
    expected_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=8, max_length=120)


class MissionTeamVersionView(ContractModel):
    id: UUID
    version: int
    selection: FixedTeamSelection
    content_hash: str
    active: bool
    created_at: datetime


class MissionTeamVersionPage(ContractModel):
    items: tuple[MissionTeamVersionView, ...]
    next_after: UUID | None = None


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
    autonomous: bool = False
    waiting_reason: str | None = None
    next_action: str | None = None
    next_action_basis: str | None = None
    user_action_required: str | None = None
    active_work_directive_version: int | None = None
    controls: dict[str, str] = Field(default_factory=dict)
    usage: MissionUsageView | None = None
    paid_unattended_available: bool = False
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
    lifecycle: Literal["active", "idle", "waiting_for_approval", "blocked", "completed"] = "active"
    scheduled_wakeup_at: datetime | None = None

    @model_validator(mode="after")
    def bounded_action(self) -> ManagerDecision:
        if (self.action == "propose") != bool(self.work_items):
            raise ValueError("only propose actions may contain work items")
        if self.action == "complete" and self.lifecycle != "completed":
            raise ValueError("complete action requires completed lifecycle")
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


class MissionAutonomyUpdate(ContractModel):
    enabled: bool
    expected_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=8, max_length=120)


class MissionControlRequest(ContractModel):
    scope: Literal["mission", "team", "global"] = "mission"
    action: Literal["pause", "resume", "drain", "safe_point", "cancel"]
    instruction: str | None = Field(default=None, min_length=1, max_length=2000)
    limits: MissionResourceLimits | None = None
    expected_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=8, max_length=120)

    @model_validator(mode="after")
    def instruction_matches_action(self) -> MissionControlRequest:
        if (self.action == "safe_point") != (self.instruction is not None):
            raise ValueError("safe_point requires an instruction and other actions forbid one")
        return self


class MissionControlView(ContractModel):
    scope: Literal["mission", "team", "global"]
    state: Literal["open", "paused", "draining", "cancelling"]
    instruction: str | None = None
    limits: MissionResourceLimits
    version: int


class MissionWakeupView(ContractModel):
    id: UUID
    kind: Literal[
        "user_direction",
        "job_completed",
        "job_failed",
        "approval_decided",
        "deadline",
    ]
    status: Literal["pending", "claimed", "turn_queued", "committed", "stale", "failed"]
    deduplication_key: str
    directive_version: int
    source_event_cursor: int | None = None
    management_turn_id: UUID | None = None
    scheduled_for: datetime
    created_at: datetime


class MissionWakeupPage(ContractModel):
    items: tuple[MissionWakeupView, ...]
    next_after: UUID | None = None


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
    team_version_id: UUID
    job_id: UUID | None = None
    run_id: UUID | None = None
    selected_worker_revision_id: UUID | None = None
    selected_model_profile_revision_id: UUID | None = None
    assignment_status: str | None = None
    queued_reason: str | None = None
    merge_queue_status: str | None = None
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
