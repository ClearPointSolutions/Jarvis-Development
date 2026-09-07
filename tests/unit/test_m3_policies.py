"""M3 deterministic decisions from exact revision snapshots."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from jarvis_api.routing.policies import (
    calculate_cost,
    evaluate_permission,
    evaluate_retry,
    evaluate_spend,
    resolve_route,
)
from jarvis_contracts.enums import FailureClass
from jarvis_contracts.failures import RetryPolicySpec, RetryRule
from jarvis_contracts.registry import (
    EgressPolicy,
    ModelProfileSpec,
    PermissionPolicySpec,
    Pricing,
    ProviderSpec,
    RegistryRecord,
    RegistrySpec,
    RouteCandidate,
    RoutePolicySpec,
    RoutePreviewRequest,
    RouteRequirements,
    SpendPolicy,
    Usage,
)


def record(spec: RegistrySpec, revision: UUID | None = None) -> RegistryRecord:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return RegistryRecord(
        id=uuid4(),
        revision_id=revision or uuid4(),
        revision=1,
        version=1,
        key="fixture",
        display_name="Fixture",
        description="",
        enabled=True,
        archived=False,
        spec=spec,
        content_hash="fixture",
        created_at=now,
        updated_at=now,
        health="healthy",
    )


def snapshot() -> tuple[RegistryRecord, dict[UUID, RegistryRecord], RoutePreviewRequest]:
    provider = record(ProviderSpec(provider_kind="demo"))
    spec = ModelProfileSpec(
        provider_revision_id=provider.revision_id,
        model_identifier="fixture",
        purposes=("utility",),
        context_limit=100,
        output_limit=20,
    )
    first, second = record(spec, UUID(int=1)), record(spec, UUID(int=2))
    route = record(
        RoutePolicySpec(
            candidates=(
                RouteCandidate(profile_revision_id=second.revision_id),
                RouteCandidate(profile_revision_id=first.revision_id),
            ),
            purposes=("utility",),
            failover_classes=(FailureClass.PROVIDER_TRANSIENT,),
        )
    )
    return (
        route,
        {r.revision_id: r for r in (provider, first, second)},
        RoutePreviewRequest(
            route_revision_id=route.revision_id,
            requirements=RouteRequirements(purpose="utility", input_tokens=5, output_tokens=5),
        ),
    )


def test_order_tie_break_snapshot_and_priority() -> None:
    route, records, request = snapshot()
    resolved = resolve_route(request, route, records)
    assert resolved.selected_profile_revision_id == UUID(int=1)
    assert resolved.demo and resolved.decision == "allow"
    assert resolved == resolve_route(request, route, dict(reversed(list(records.items()))))
    assert isinstance(route.spec, RoutePolicySpec)
    priority = route.model_copy(
        update={
            "spec": route.spec.model_copy(
                update={
                    "candidates": (
                        RouteCandidate(profile_revision_id=UUID(int=2), priority=0),
                        RouteCandidate(profile_revision_id=UUID(int=1), priority=1),
                    )
                }
            )
        }
    )
    assert resolve_route(request, priority, records).selected_profile_revision_id == UUID(int=2)
    assert resolve_route(request, priority, records).snapshot_hash != resolved.snapshot_hash
    changed = dict(records)
    changed[UUID(int=1)] = records[UUID(int=1)].model_copy(update={"enabled": False})
    assert resolve_route(
        request, changed.get(route.revision_id, route), changed
    ).selected_profile_revision_id == UUID(int=2)
    assert resolve_route(request, route, records) == resolved


@pytest.mark.parametrize(
    "field,value",
    [
        ("enabled", False),
        ("archived", True),
        ("health", "unavailable"),
        ("health", "misconfigured"),
        ("health", "unknown"),
        ("circuit_state", "open"),
        ("circuit_state", "half_open"),
        ("secret_status", "missing"),
    ],
)
def test_provider_eligibility(field: str, value: object) -> None:
    route, records, request = snapshot()
    provider = next(r for r in records.values() if isinstance(r.spec, ProviderSpec))
    records[provider.revision_id] = provider.model_copy(update={field: value})
    result = resolve_route(request, route, records)
    assert result.decision == "deny" and result.selected_profile_revision_id is None


@pytest.mark.parametrize(
    "requirements",
    [
        RouteRequirements(purpose="other"),
        RouteRequirements(purpose="utility", capabilities=("structured_json",)),
        RouteRequirements(purpose="utility", input_tokens=100, output_tokens=1),
        RouteRequirements(purpose="utility", output_tokens=21),
        RouteRequirements(purpose="utility", data_classification="restricted"),
    ],
)
def test_requirements_fail_closed(requirements: RouteRequirements) -> None:
    route, records, request = snapshot()
    assert (
        resolve_route(
            request.model_copy(update={"requirements": requirements}), route, records
        ).decision
        == "deny"
    )


def test_failover_must_be_declared_and_authorized() -> None:
    route, records, request = snapshot()
    failed = request.model_copy(update={"failed_profile_revision_ids": (UUID(int=1),)})
    assert resolve_route(failed, route, records).decision == "deny"
    valid = failed.model_copy(update={"failure_class": FailureClass.PROVIDER_TRANSIENT})
    assert resolve_route(valid, route, records).selected_profile_revision_id == UUID(int=2)
    for failure in (FailureClass.USER_CANCELLED, FailureClass.SECURITY_POLICY_DENIED):
        assert (
            resolve_route(
                valid.model_copy(update={"failure_class": failure}), route, records
            ).decision
            == "deny"
        )
    assert (
        resolve_route(
            valid.model_copy(update={"failed_profile_revision_ids": (uuid4(),)}), route, records
        ).decision
        == "deny"
    )
    assert (
        resolve_route(
            valid.model_copy(update={"failed_profile_revision_ids": (UUID(int=1), UUID(int=2))}),
            route,
            records,
        ).selected_profile_revision_id
        is None
    )


def test_revision_identity_cannot_be_forged_in_mapping() -> None:
    route, records, request = snapshot()
    records[UUID(int=1)] = records[UUID(int=1)].model_copy(update={"revision_id": uuid4()})
    result = resolve_route(request, route, records)
    assert result.selected_profile_revision_id == UUID(int=2)
    assert not result.candidates[0].eligible


def test_remote_locality_data_and_paid_policy() -> None:
    route, records, request = snapshot()
    provider = next(r for r in records.values() if isinstance(r.spec, ProviderSpec))
    remote = ProviderSpec(
        provider_kind="openai",
        base_url="https://example.test",
        locality="remote",
        egress=EgressPolicy(remote_allowed=True, paid=True),
    )
    records[provider.revision_id] = provider.model_copy(
        update={"spec": remote, "secret_status": "configured"}
    )
    for key in (UUID(int=1), UUID(int=2)):
        model = records[key]
        assert isinstance(model.spec, ModelProfileSpec)
        records[key] = model.model_copy(
            update={"spec": model.spec.model_copy(update={"locality": "remote"})}
        )
    assert resolve_route(request, route, records).decision == "deny"
    assert isinstance(route.spec, RoutePolicySpec)
    route = route.model_copy(update={"spec": route.spec.model_copy(update={"allow_remote": True})})
    result = resolve_route(request, route, records)
    assert result.decision == "deny" and "Paid" in result.reasons[0]


@pytest.mark.parametrize("provenance", ["exact", "estimated"])
def test_decimal_cached_pricing_and_snapshot(provenance: str) -> None:
    usage = Usage.model_validate(
        {
            "input_tokens": 1000,
            "cached_tokens": 200,
            "output_tokens": 100,
            "total_tokens": 1100,
            "provenance": provenance,
        }
    )
    price = Pricing(
        status="known",
        input_per_million=Decimal("2"),
        cached_per_million=Decimal("0.5"),
        output_per_million=Decimal("10"),
    )
    cost = calculate_cost(usage, price)
    assert cost.amount == Decimal("0.0027") and cost.status == provenance
    assert calculate_cost(
        usage, price.model_copy(update={"cached_per_million": None})
    ).amount == Decimal("0.003")
    assert calculate_cost(usage, price) == cost
    assert calculate_cost(usage, Pricing()).amount is None


def test_unknown_is_not_zero_and_spend_denial_approval() -> None:
    price = Pricing(status="known", input_per_million=Decimal(1), output_per_million=Decimal(1))
    assert calculate_cost(Usage(), price).amount is None
    assert calculate_cost(Usage(), Pricing(status="not_applicable")).status == "not_applicable"
    req = RouteRequirements(purpose="utility", input_tokens=10, output_tokens=10)
    decision, reasons = evaluate_spend(
        SpendPolicy(max_call_cost=Decimal(1), on_exceeded="require_approval"),
        req,
        Pricing(),
        paid=False,
    )
    assert decision == "require_approval" and reasons
    assert evaluate_spend(SpendPolicy(max_run_cost=Decimal(1)), req, price, paid=False)[0] == "deny"
    assert (
        evaluate_spend(SpendPolicy(max_call_cost=Decimal("0.00001")), req, price, paid=False)[0]
        == "deny"
    )
    assert evaluate_spend(SpendPolicy(max_input_tokens=1), req, price, paid=False)[0] == "deny"
    assert evaluate_spend(SpendPolicy(max_output_tokens=1), req, price, paid=False)[0] == "deny"
    assert evaluate_spend(SpendPolicy(), req, price, paid=False)[0] == "allow"


def test_retry_class_isolation_exhaustion_and_deterministic_backoff() -> None:
    failure = FailureClass.PROVIDER_TRANSIENT
    policy = RetryPolicySpec(
        rules=(
            RetryRule(
                failure_class=failure,
                max_retries=3,
                initial_delay_ms=100,
                multiplier=2,
                max_delay_ms=300,
                exhaustion_action="block",
                allow_failover=True,
            ),
            RetryRule(
                failure_class=FailureClass.CODE_TEST_FAILURE,
                max_retries=1,
                exhaustion_action="fail",
            ),
        )
    )
    counters = {failure: 2, FailureClass.CODE_TEST_FAILURE: 0}
    decision = evaluate_retry(policy, failure, counters)
    assert decision.retry and decision.delay_ms == 300 and decision.used_retries == 3
    assert not decision.consumes_semantic_attempt and decision.allow_failover
    assert counters[FailureClass.CODE_TEST_FAILURE] == 0
    assert evaluate_retry(
        policy, FailureClass.CODE_TEST_FAILURE, counters
    ).consumes_semantic_attempt
    exhausted = evaluate_retry(policy, failure, {failure: 3})
    assert not exhausted.retry and exhausted.exhaustion_action == "block"
    assert not evaluate_retry(policy, FailureClass.SECURITY_POLICY_DENIED, {}).retry
    with pytest.raises(ValueError):
        evaluate_retry(policy, failure, {failure: -1})
    jitter = policy.model_copy(
        update={"rules": (policy.rules[0].model_copy(update={"jitter": "deterministic"}),)}
    )
    first = evaluate_retry(jitter, failure, {}, jitter_key="fixed")
    assert 50 <= first.delay_ms <= 100 and first == evaluate_retry(
        jitter, failure, {}, jitter_key="fixed"
    )


def test_permissions_deny_precedence_and_scopes() -> None:
    policy = PermissionPolicySpec(
        shell="allow",
        git="allow",
        allowed_capabilities=("read",),
        denied_capabilities=("delete",),
        filesystem_scopes=("workspace",),
        approval_required_actions=("git",),
    )
    assert (
        evaluate_permission(policy, "shell", capabilities=("read",), filesystem_scope="workspace")
        == "allow"
    )
    assert evaluate_permission(policy, "git") == "require_approval"
    assert evaluate_permission(policy, "shell", capabilities=("delete",)) == "deny"
    assert evaluate_permission(policy, "shell", capabilities=("unknown",)) == "deny"
    assert evaluate_permission(policy, "shell", filesystem_scope="outside") == "deny"
    assert evaluate_permission(policy, "unknown") == "deny"
    assert evaluate_permission(policy, "shell", sensitive=True) == "require_approval"
    assert evaluate_permission(policy, "shell", destructive=True) == "deny"
    assert evaluate_permission(PermissionPolicySpec(), "shell", sensitive=True) == "deny"
