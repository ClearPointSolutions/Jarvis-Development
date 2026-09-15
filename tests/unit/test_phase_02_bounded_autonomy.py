"""Pure guards for bounded automatic continuation."""

import pytest
from pydantic import ValidationError

from jarvis_contracts.missions import ManagerDecision, MissionControlRequest, MissionResourceLimits
from jarvis_contracts.registry import ProviderRequest
from jarvis_orchestrator.mission_resources import SHARED_RESOURCE_LIMITS
from jarvis_orchestrator.providers.budget import (
    PROVIDER_REQUEST_OVERHEAD_TOKENS,
    estimate_input_tokens,
)


def test_complete_wait_and_safe_point_are_unambiguous() -> None:
    complete = ManagerDecision(
        action="complete", message="Evidence supports completion", lifecycle="completed"
    )
    assert complete.work_items == ()
    with pytest.raises(ValidationError, match="completed lifecycle"):
        ManagerDecision(action="complete", message="not terminal")
    with pytest.raises(ValidationError, match="safe_point requires"):
        MissionControlRequest(
            action="safe_point", expected_version=1, idempotency_key="phase2-test"
        )


def test_resource_limits_use_explicit_utc_windows_and_currency() -> None:
    limits = MissionResourceLimits()
    assert limits.timezone == "UTC" and limits.window_seconds == 86_400
    assert SHARED_RESOURCE_LIMITS.max_active_jobs > limits.max_active_jobs
    with pytest.raises(ValidationError):
        MissionResourceLimits(currency="usd")


def test_provider_bound_reserves_every_byte_plus_envelope() -> None:
    request = ProviderRequest(
        purpose="mission_manager",
        text="évidence",
        output_tokens=10,
        correlation_id="phase-2-bound",
        structured_schema={"type": "object", "properties": {"answer": {"type": "string"}}},
    )
    serialized_bytes = len(request.text.encode()) + len(
        b'{"properties":{"answer":{"type":"string"}},"type":"object"}'
    )
    assert estimate_input_tokens(request) >= serialized_bytes + PROVIDER_REQUEST_OVERHEAD_TOKENS
