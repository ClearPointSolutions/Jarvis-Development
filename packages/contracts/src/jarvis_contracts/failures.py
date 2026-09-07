"""Failure classification and retry-policy contracts."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from jarvis_contracts.base import ContractModel
from jarvis_contracts.enums import FailureClass
from jarvis_contracts.ids import ArtifactId, FailureId


class FailureEvidence(ContractModel):
    security_policy_denied: bool = False
    user_cancelled: bool = False
    explicit_class: FailureClass | None = None
    verifier_failed: bool = False
    provider_rate_limited: bool = False
    provider_transient: bool = False
    worker_transport_failed: bool = False
    code: str = Field(default="unknown", min_length=1, max_length=120)
    summary: str = Field(default="Failure requires classification", max_length=1_024)


class FailureClassification(ContractModel):
    failure_class: FailureClass = Field(alias="class")
    code: str = Field(min_length=1, max_length=120)
    retryable: bool
    budget_scope: str = Field(min_length=1, max_length=120)
    consumes_semantic_attempt: bool
    summary: str = Field(max_length=1_024)


def classify_failure(evidence: FailureEvidence) -> FailureClassification:
    """Apply the architecture's deterministic classification precedence."""

    if evidence.security_policy_denied:
        selected = FailureClass.SECURITY_POLICY_DENIED
    elif evidence.user_cancelled:
        selected = FailureClass.USER_CANCELLED
    elif evidence.explicit_class is not None:
        selected = evidence.explicit_class
    elif evidence.verifier_failed:
        selected = FailureClass.CODE_TEST_FAILURE
    elif evidence.provider_rate_limited:
        selected = FailureClass.PROVIDER_RATE_LIMITED
    elif evidence.provider_transient:
        selected = FailureClass.PROVIDER_TRANSIENT
    elif evidence.worker_transport_failed:
        selected = FailureClass.INFRASTRUCTURE_WORKER_TRANSPORT
    else:
        selected = FailureClass.ORCHESTRATION_RUNTIME_ERROR

    non_retryable = {
        FailureClass.CONFIGURATION_INVALID,
        FailureClass.SECURITY_POLICY_DENIED,
        FailureClass.APPROVAL_REJECTED,
        FailureClass.USER_CANCELLED,
    }
    semantic = selected.value.startswith("code.")
    return FailureClassification(
        **{
            "class": selected,
            "code": evidence.code,
            "retryable": selected not in non_retryable,
            "budget_scope": selected.value,
            "consumes_semantic_attempt": semantic,
            "summary": evidence.summary,
        }
    )


class RetryRule(ContractModel):
    failure_class: FailureClass
    max_retries: Annotated[int, Field(ge=0, le=100)]
    initial_delay_ms: Annotated[int, Field(ge=0, le=86_400_000)] = 0
    multiplier: Annotated[float, Field(ge=1, le=100)] = 1
    exhaustion_action: Literal["fail", "block", "approval"]


class RetryPolicySpec(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    rules: tuple[RetryRule, ...]


class FailureRecord(ContractModel):
    id: FailureId
    classification: FailureClassification
    detail_artifact_id: ArtifactId | None = None
