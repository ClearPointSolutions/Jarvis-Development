"""Versioned browser/API boundary contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, JsonValue

from jarvis_contracts.base import ContractModel
from jarvis_contracts.events import NormalizedEvent
from jarvis_contracts.ids import UserId


class ApiErrorDetail(ContractModel):
    code: str = Field(min_length=1, max_length=120, pattern=r"^[a-z][a-z0-9_.-]*$")
    message: str = Field(min_length=1, max_length=1_024)
    request_id: str = Field(min_length=8, max_length=64)
    details: dict[str, JsonValue] = Field(default_factory=dict)


class ApiErrorResponse(ContractModel):
    error: ApiErrorDetail


class LoginRequest(ContractModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=1_024)


class SessionUser(ContractModel):
    id: UserId
    username: str = Field(min_length=3, max_length=64)
    role: Literal["owner"] = "owner"


class SessionResponse(ContractModel):
    user: SessionUser
    csrf_token: str = Field(min_length=32, max_length=256)
    idle_expires_at: datetime
    absolute_expires_at: datetime


class LogoutResponse(ContractModel):
    revoked: bool


class LivenessResponse(ContractModel):
    service: Literal["jarvis-api"] = "jarvis-api"
    status: Literal["ok"] = "ok"
    version: Literal["0.1.0"] = "0.1.0"


class ReadinessResponse(ContractModel):
    status: Literal["ready", "not_ready"]
    database: Literal["ready", "unavailable", "migration_required"]


class EventPage(ContractModel):
    items: tuple[NormalizedEvent, ...]
    after: Annotated[int, Field(ge=0)]
    high_watermark: Annotated[int, Field(ge=0)]
    next_after: Annotated[int, Field(ge=0)] | None = None


class EventStreamReset(ContractModel):
    reason: Literal["cursor_expired", "unsupported_schema", "run_sequence_gap"]
    earliest_position: Annotated[int, Field(ge=0)] | None = None
    latest_position: Annotated[int, Field(ge=0)] | None = None
