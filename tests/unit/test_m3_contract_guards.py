"""Adversarial configuration constraints and combined permission decisions."""

from uuid import UUID

import pytest
from pydantic import ValidationError

from jarvis_api.routing.policies import evaluate_permission
from jarvis_contracts.registry import ModelProfileSpec, PermissionPolicySpec, Usage


@pytest.mark.parametrize(
    "parameters",
    [
        {"temperature": "credential-like-value"},
        {"top_p": True},
        {"temperature": 3},
        {"seed": -1},
        {"keep_alive": 3601},
        {"reasoning_effort": "unknown-effort"},
        {"temperature": {"api_key": "untrusted-value"}},
    ],
)
def test_model_parameters_cannot_smuggle_arbitrary_objects(parameters: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ModelProfileSpec.model_validate(
            {
                "provider_revision_id": UUID(int=1),
                "model_identifier": "configured-model",
                "purposes": ["utility"],
                "context_limit": 1000,
                "output_limit": 100,
                "parameters": parameters,
            }
        )


def test_usage_counts_and_permission_denial_precedence() -> None:
    with pytest.raises(ValidationError):
        Usage(input_tokens=10, cached_tokens=11)
    with pytest.raises(ValidationError):
        Usage(input_tokens=10, output_tokens=2, total_tokens=10)
    policy = PermissionPolicySpec(
        shell="allow",
        sensitive_action="deny",
        destructive_action="require_approval",
        approval_required_actions=("git.push",),
    )
    assert evaluate_permission(policy, "shell", sensitive=True, destructive=True) == "deny"
    assert evaluate_permission(policy, "git.push") == "require_approval"
    assert evaluate_permission(policy, "unrecognized.privileged") == "deny"
