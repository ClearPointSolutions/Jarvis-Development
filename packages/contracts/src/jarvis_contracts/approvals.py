"""Production approval requests and authenticated decision contracts."""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, JsonValue

from jarvis_contracts.base import ContractModel


class ApprovalView(ContractModel):
    id: UUID
    run_id: UUID
    node_id: str
    action_type: str
    request_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    parameters: dict[str, JsonValue]
    created_at: AwareDatetime
    expires_at: AwareDatetime | None = None
    decision: Literal["pending", "approved", "rejected", "expired", "cancelled"] = "pending"
    actor_id: UUID | None = None
    decided_at: AwareDatetime | None = None


class ApprovalPage(ContractModel):
    items: tuple[ApprovalView, ...]


class ApprovalDecisionRequest(ContractModel):
    idempotency_key: str = Field(min_length=1, max_length=200)
    expected_run_version: int = Field(ge=1)
    request_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    decision: Literal["approved", "rejected"]
