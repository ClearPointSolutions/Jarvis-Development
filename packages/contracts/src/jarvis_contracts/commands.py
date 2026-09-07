"""Durable run command and HTTP idempotency contracts."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, JsonValue

from jarvis_contracts.base import ContractModel, sha256_digest
from jarvis_contracts.enums import CommandStatus, RunCommandKind
from jarvis_contracts.ids import CommandId, RunId

IdempotencyKey = Annotated[
    str,
    Field(min_length=8, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]+$"),
]


class RunCommandRequest(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    run_id: RunId
    kind: RunCommandKind
    idempotency_key: IdempotencyKey
    payload: dict[str, JsonValue] = Field(default_factory=dict)
    expected_run_version: Annotated[int, Field(ge=0)] | None = None

    @property
    def request_digest(self) -> str:
        return sha256_digest(
            {
                "schema_version": self.schema_version,
                "run_id": str(self.run_id),
                "kind": self.kind.value,
                "payload": self.payload,
                "expected_run_version": self.expected_run_version,
            }
        )


class RunCommandReceipt(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    command_id: CommandId
    run_id: RunId
    sequence: Annotated[int, Field(gt=0)]
    status: CommandStatus
    request_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    duplicate: bool = False


class IdempotencyContract(ContractModel):
    scope: str = Field(min_length=1, max_length=120)
    key: IdempotencyKey
    request_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    response_status: Annotated[int, Field(ge=100, le=599)] | None = None
    state: Literal["started", "completed", "failed"]
