"""Pure deterministic routing, retry, permission and decimal spend evaluation."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from jarvis_contracts.base import sha256_digest
from jarvis_contracts.enums import FailureClass
from jarvis_contracts.failures import RetryPolicySpec
from jarvis_contracts.registry import (
    CandidateDecision,
    Cost,
    Decision,
    ModelProfileSpec,
    PermissionPolicySpec,
    Pricing,
    ProviderSpec,
    RegistryRecord,
    RoutePolicySpec,
    RoutePreviewRequest,
    RouteRequirements,
    RouteResolution,
    SpendPolicy,
    Usage,
)


def calculate_cost(usage: Usage, pricing: Pricing) -> Cost:
    if pricing.status == "not_applicable":
        return Cost(status="not_applicable", currency=pricing.currency)
    if (
        pricing.status != "known"
        or usage.provenance == "unknown"
        or usage.input_tokens is None
        or usage.output_tokens is None
    ):
        return Cost(currency=pricing.currency)
    if pricing.input_per_million is None or pricing.output_per_million is None:
        return Cost(currency=pricing.currency)
    cached = usage.cached_tokens or 0
    if cached > usage.input_tokens:
        return Cost(currency=pricing.currency)
    cached_price = pricing.cached_per_million
    # No assumed discounted rate: absent cached pricing conservatively uses input rate.
    if cached_price is None:
        cached_price = pricing.input_per_million
    amount = (
        Decimal(usage.input_tokens - cached) * pricing.input_per_million
        + Decimal(cached) * cached_price
        + Decimal(usage.output_tokens) * pricing.output_per_million
    ) / Decimal(1_000_000)
    return Cost(amount=amount, currency=pricing.currency, status=usage.provenance)


def evaluate_spend(
    policy: SpendPolicy,
    requirements: RouteRequirements,
    pricing: Pricing,
    *,
    paid: bool,
) -> tuple[Decision, tuple[str, ...]]:
    reasons: list[str] = []
    if paid and not policy.allow_paid:
        reasons.append("Paid provider use is disabled")
    if requirements.input_tokens > policy.max_input_tokens:
        reasons.append("Per-call input token ceiling exceeded")
    if requirements.output_tokens > policy.max_output_tokens:
        reasons.append("Per-call output token ceiling exceeded")
    estimate = calculate_cost(
        Usage(
            input_tokens=requirements.input_tokens,
            output_tokens=requirements.output_tokens,
            provenance="estimated",
        ),
        pricing,
    )
    if policy.max_call_cost is not None and (
        estimate.amount is None or estimate.amount > policy.max_call_cost
    ):
        reasons.append("Per-call cost ceiling cannot be satisfied")
    if policy.max_run_cost is not None and (
        estimate.amount is None
        or requirements.run_spend is None
        or requirements.run_spend + estimate.amount > policy.max_run_cost
    ):
        reasons.append("Per-run cost ceiling cannot be satisfied")
    return (policy.on_exceeded if reasons else "allow", tuple(reasons))


def resolve_route(
    request: RoutePreviewRequest,
    route: RegistryRecord,
    records: Mapping[UUID, RegistryRecord],
) -> RouteResolution:
    """Resolve only declared exact revisions; no caller-supplied alternative provider."""
    digest = sha256_digest(
        {
            "request": request.model_dump(mode="json"),
            "route": route.model_dump(mode="json"),
            "records": {str(k): v.model_dump(mode="json") for k, v in sorted(records.items())},
        }
    )
    base = {"route_revision_id": request.route_revision_id, "snapshot_hash": digest}
    spec = route.spec
    req = request.requirements
    if not isinstance(spec, RoutePolicySpec) or route.revision_id != request.route_revision_id:
        return RouteResolution(**base, reasons=("Invalid route revision",))
    if not route.enabled or route.archived:
        return RouteResolution(**base, reasons=("Route is disabled or archived",))
    if req.purpose not in spec.purposes or req.data_classification not in spec.allowed_data:
        return RouteResolution(**base, reasons=("Route purpose or data policy denied",))
    declared = {c.profile_revision_id for c in spec.candidates}
    if set(request.failed_profile_revision_ids) - declared:
        return RouteResolution(**base, reasons=("Failover references an undeclared profile",))
    if request.failed_profile_revision_ids and (
        request.failure_class is None
        or request.failure_class not in spec.failover_classes
        or request.failure_class
        in {FailureClass.SECURITY_POLICY_DENIED, FailureClass.USER_CANCELLED}
    ):
        return RouteResolution(**base, reasons=("Failover is not permitted for this failure",))
    required = set(req.capabilities) | set(spec.required_capabilities)
    decisions: list[CandidateDecision] = []
    selected: RegistryRecord | None = None
    selected_provider: RegistryRecord | None = None
    for candidate in sorted(
        spec.candidates, key=lambda c: (c.priority, str(c.profile_revision_id))
    ):
        reasons: list[str] = []
        record = records.get(candidate.profile_revision_id)
        profile = record.spec if record else None
        provider_record: RegistryRecord | None = None
        if candidate.profile_revision_id in request.failed_profile_revision_ids:
            reasons.append("Candidate already failed")
        if (
            record is None
            or record.revision_id != candidate.profile_revision_id
            or not isinstance(profile, ModelProfileSpec)
        ):
            reasons.append("Profile revision is missing")
        else:
            if not record.enabled or record.archived:
                reasons.append("Profile is disabled or archived")
            capabilities = set(profile.capabilities)
            capabilities.update(
                name
                for name, enabled in (
                    ("structured_json", profile.structured_json),
                    ("tool_calls", profile.tool_calls),
                    ("streaming", profile.streaming),
                )
                if enabled
            )
            if not required <= capabilities:
                reasons.append("Required capabilities are unavailable")
            if req.purpose not in profile.purposes:
                reasons.append("Profile purpose is incompatible")
            if req.input_tokens + req.output_tokens > profile.context_limit:
                reasons.append("Context requirement exceeds profile limit")
            if req.output_tokens > profile.output_limit:
                reasons.append("Output requirement exceeds profile limit")
            provider_record = records.get(profile.provider_revision_id)
            provider = provider_record.spec if provider_record else None
            if (
                provider_record is None
                or provider_record.revision_id != profile.provider_revision_id
                or not isinstance(provider, ProviderSpec)
            ):
                reasons.append("Provider revision is missing")
            else:
                if not provider_record.enabled or provider_record.archived:
                    reasons.append("Provider is disabled or archived")
                if provider_record.secret_status == "missing":
                    reasons.append("Provider credential reference is missing")
                if provider.locality != profile.locality:
                    reasons.append("Provider/profile locality mismatch")
                if req.data_classification not in provider.egress.allowed_data:
                    reasons.append("Provider data policy denied")
                if provider.locality == "remote" and not (
                    spec.allow_remote and provider.egress.remote_allowed
                ):
                    reasons.append("Remote provider use is denied")
                if provider_record.health in {"unavailable", "misconfigured"} or (
                    provider_record.health == "unknown" and not spec.allow_unknown_health
                ):
                    reasons.append("Provider health is ineligible")
                if provider_record.circuit_state != "closed":
                    reasons.append("Provider circuit requires recovery probe")
        decisions.append(
            CandidateDecision(
                profile_revision_id=candidate.profile_revision_id,
                eligible=not reasons,
                reasons=tuple(reasons),
            )
        )
        if not reasons and selected is None:
            selected, selected_provider = record, provider_record
    if selected is None or selected_provider is None:
        return RouteResolution(
            **base, reasons=("No eligible declared candidate",), candidates=tuple(decisions)
        )
    assert isinstance(selected.spec, ModelProfileSpec)
    assert isinstance(selected_provider.spec, ProviderSpec)
    decision, reasons_tuple = evaluate_spend(
        spec.spend,
        req,
        selected.spec.pricing,
        paid=selected_provider.spec.egress.paid,
    )
    return RouteResolution(
        **base,
        selected_profile_revision_id=selected.revision_id,
        selected_provider_revision_id=selected_provider.revision_id,
        decision=decision,
        reasons=reasons_tuple,
        candidates=tuple(decisions),
        demo=selected_provider.spec.provider_kind == "demo",
    )


@dataclass(frozen=True)
class RetryDecision:
    failure_class: FailureClass
    retry: bool
    used_retries: int
    delay_ms: int
    exhaustion_action: str
    allow_failover: bool
    consumes_semantic_attempt: bool


def evaluate_retry(
    policy: RetryPolicySpec,
    failure: FailureClass,
    counters: Mapping[FailureClass, int],
    *,
    jitter_key: str = "",
) -> RetryDecision:
    used = counters.get(failure, 0)
    if used < 0:
        raise ValueError("retry counters cannot be negative")
    rule = next((item for item in policy.rules if item.failure_class == failure), None)
    blocked = failure in {
        FailureClass.SECURITY_POLICY_DENIED,
        FailureClass.CONFIGURATION_INVALID,
        FailureClass.USER_CANCELLED,
        FailureClass.APPROVAL_REJECTED,
    }
    if rule is None or blocked or used >= rule.max_retries:
        return RetryDecision(
            failure, False, used, 0, rule.exhaustion_action if rule else "block", False, False
        )
    delay = min(rule.max_delay_ms, int(rule.initial_delay_ms * rule.multiplier ** min(used, 100)))
    if rule.jitter == "deterministic" and delay:
        fraction = int.from_bytes(
            hashlib.sha256(f"{jitter_key}:{failure}:{used}".encode()).digest()[:4]
        ) / (2**32 - 1)
        delay = max(rule.initial_delay_ms, int(delay * (0.5 + 0.5 * fraction)))
    return RetryDecision(
        failure,
        True,
        used + 1,
        delay,
        rule.exhaustion_action,
        rule.allow_failover,
        failure.value.startswith("code."),
    )


def evaluate_permission(
    policy: PermissionPolicySpec,
    action: str,
    *,
    capabilities: tuple[str, ...] = (),
    filesystem_scope: str | None = None,
    sensitive: bool = False,
    destructive: bool = False,
) -> Decision:
    if set(capabilities) & set(policy.denied_capabilities):
        return "deny"
    if not set(capabilities) <= set(policy.allowed_capabilities):
        return "deny"
    if filesystem_scope is not None and filesystem_scope not in policy.filesystem_scopes:
        return "deny"
    actions: dict[str, Decision] = {
        "shell": policy.shell,
        "git": policy.git,
        "docker": policy.docker,
        "browser": policy.browser,
        "network": policy.network,
        "remote_provider": policy.remote_provider,
    }
    result = actions.get(action, policy.unknown_action)
    if action in policy.approval_required_actions and action not in actions:
        result = "require_approval"
    decisions = [result]
    if destructive:
        decisions.append(policy.destructive_action)
    if sensitive:
        decisions.append(policy.sensitive_action)
    if action in policy.approval_required_actions:
        decisions.append("require_approval")
    if "deny" in decisions:
        return "deny"
    return "require_approval" if "require_approval" in decisions else "allow"
