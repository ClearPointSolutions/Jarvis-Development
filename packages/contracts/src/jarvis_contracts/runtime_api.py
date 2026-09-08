"""Bounded M5 enqueue, query and control HTTP contracts."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from jarvis_contracts.base import ContractModel
from jarvis_contracts.commands import IdempotencyKey
from jarvis_contracts.demo import DemoFixture
from jarvis_contracts.enums import RunCommandKind


class ProjectCreate(ContractModel):
    idempotency_key: IdempotencyKey
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,79}$")
    name: str = Field(min_length=1, max_length=160)


class ProjectView(ContractModel):
    id: UUID
    slug: str
    name: str


class ProjectPage(ContractModel):
    items: tuple[ProjectView, ...]
    next_after: UUID | None = None


class JobCreate(ContractModel):
    idempotency_key: IdempotencyKey
    workflow_version_id: UUID
    objective: str = Field(min_length=1, max_length=8000)
    priority: int = Field(default=0, ge=-100, le=100)
    mode: Literal["real", "demo"] = "demo"
    demo_fixture: DemoFixture | None = None

    @model_validator(mode="after")
    def demo_only(self) -> "JobCreate":
        if self.demo_fixture is not None and self.mode != "demo":
            raise ValueError("Demo fixture controls require demo mode")
        return self


class RunView(ContractModel):
    id: UUID
    job_id: UUID
    project_id: UUID
    workflow_version_id: UUID
    run_number: int
    retry_of_run_id: UUID | None
    thread_id: str
    status: str
    desired_state: str
    mode: str
    version: int
    recovering: bool
    current_node: str | None
    result_summary: str | None
    claimable_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    last_event_position: int
    last_run_sequence: int
    last_event_at: datetime | None


class CommandView(ContractModel):
    id: UUID
    sequence: int
    kind: str
    status: str
    applied_at: datetime | None


class CommandPage(ContractModel):
    items: tuple[CommandView, ...]
    next_after: int | None = None


class NodeView(ContractModel):
    id: UUID
    workflow_node_id: str
    execution_number: int
    status: str
    task_id: UUID | None
    task_attempt_id: UUID | None
    started_at: datetime | None
    completed_at: datetime | None


class NodePage(ContractModel):
    items: tuple[NodeView, ...]
    next_after: UUID | None = None


class RunPage(ContractModel):
    items: tuple[RunView, ...]
    next_after: UUID | None = None


class JobView(ContractModel):
    id: UUID
    project_id: UUID
    objective: str
    status: str


class JobPage(ContractModel):
    items: tuple[JobView, ...]
    next_after: UUID | None = None


class RunControl(ContractModel):
    idempotency_key: IdempotencyKey
    expected_run_version: int = Field(ge=0)
    kind: RunCommandKind
    instruction: str | None = Field(default=None, min_length=1, max_length=4000)

    @model_validator(mode="after")
    def instruction_shape(self) -> "RunControl":
        if (self.kind == RunCommandKind.INSTRUCTION) != (self.instruction is not None):
            raise ValueError("Only instruction commands require instruction text")
        return self
