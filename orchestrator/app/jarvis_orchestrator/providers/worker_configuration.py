"""Server-only future OpenHands deployment metadata; no SSH or secret resolution.

This model is intentionally outside jarvis_contracts and its browser schema generator.
Only the opaque deployment reference/configured status belongs in registry responses.
M7 must resolve the references and verify pinned host identity before any execution.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import ConfigDict, Field, field_validator

from jarvis_contracts.base import ContractModel
from jarvis_contracts.registry import OpaqueReference, TimeoutPolicy, ValidationReport, WorkerSpec


class OpenHandsDeployment(ContractModel):
    """Immutable deployment manifest; constructing it performs no I/O."""

    model_config = ConfigDict(
        extra="forbid", frozen=True, validate_default=True, hide_input_in_errors=True, strict=True
    )

    schema_version: Literal["1.0"] = "1.0"
    host_alias: str = Field(
        min_length=1, max_length=120, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$", repr=False
    )
    port: int = Field(default=22, ge=1, le=65535, repr=False)
    user: str = Field(min_length=1, max_length=64, pattern=r"^[a-z_][a-z0-9_-]*$", repr=False)
    ssh_key_ref: OpaqueReference = Field(repr=False)
    host_key_ref: OpaqueReference = Field(repr=False)
    strict_host_key_checking: Literal["yes"] = "yes"
    workspace_root: str = Field(min_length=2, max_length=1024, repr=False)
    runner_path: str = Field(min_length=2, max_length=1024, repr=False)
    venv_activate: str = Field(min_length=2, max_length=1024, repr=False)
    invocation_root: str = Field(min_length=2, max_length=1024, repr=False)
    timeouts: TimeoutPolicy = Field(default_factory=TimeoutPolicy)

    @field_validator("workspace_root", "runner_path", "venv_activate", "invocation_root")
    @classmethod
    def absolute_posix_path(cls, value: str) -> str:
        # Validate before normalization: normalizers silently erase traversal segments.
        if (
            not value.startswith("/")
            or value.startswith("//")
            or "\\" in value
            or any(ord(char) < 32 or ord(char) == 127 for char in value)
            or any(part in {"", ".", ".."} for part in value.split("/")[1:])
        ):
            raise ValueError("deployment paths must be canonical absolute POSIX paths")
        return value


def validate_model_binding(spec: WorkerSpec, profile_revision_id: UUID | None) -> ValidationReport:
    """Reject cosmetic model choices a worker cannot honor, without contacting it."""
    binding = spec.model_binding
    compatible = (
        profile_revision_id is None
        if binding.mode == "none"
        else profile_revision_id in binding.allowed_profile_revision_ids
    )
    demo = spec.adapter_kind == "demo"
    return ValidationReport(
        valid=compatible,
        health=("healthy" if demo else "unknown") if compatible else "misconfigured",
        issues=() if compatible else ("incompatible_model_binding",),
        network_checked=False,
        demo=demo,
    )
