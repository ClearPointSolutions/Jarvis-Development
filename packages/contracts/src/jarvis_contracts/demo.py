"""M6 fixture controls; no endpoints, credentials or executable text."""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from jarvis_contracts.base import ContractModel


class DemoFixture(ContractModel):
    seed: int = Field(default=6, ge=0, le=1_000_000)
    clock: datetime = datetime(2026, 1, 1, tzinfo=UTC)
    scenario: Literal["canonical", "infrastructure", "review", "provider"] = "canonical"
    delay_seconds: float = Field(default=0.15, ge=0, le=5)
    health: Literal["healthy", "degraded", "unavailable", "unknown"] = "healthy"
    ci: Literal["success", "failure"] = "success"


class DemoDecision(ContractModel):
    decision_id: str = Field(min_length=1, max_length=160)
    decision: Literal["approved", "rejected"]
    expected_run_version: int = Field(ge=0)
    idempotency_key: str = Field(min_length=8, max_length=120)


class AttemptView(ContractModel):
    id: UUID
    number: int
    status: str
    snapshot_digest: str | None


class TaskView(ContractModel):
    id: UUID
    key: str
    title: str
    status: str
    weight: int
    dependencies: tuple[UUID, ...]
    attempts: tuple[AttemptView, ...]


class TaskPage(ContractModel):
    items: tuple[TaskView, ...]
    next_after: UUID | None = None


class DemoDecisionView(ContractModel):
    id: str
    decision: str
