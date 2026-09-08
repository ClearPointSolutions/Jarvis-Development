"""M3 versioned registry and normalized provider contracts. No credential values."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import Field, JsonValue, TypeAdapter, field_validator, model_validator

from jarvis_contracts.base import ContractModel
from jarvis_contracts.enums import FailureClass
from jarvis_contracts.failures import RetryPolicySpec

RegistryKind = Literal[
    "worker",
    "provider_connection",
    "model_profile",
    "route_policy",
    "retry_policy",
    "permission_policy",
]
ProviderKind = Literal["openai", "ollama", "demo"]
Locality = Literal["local", "local_lan", "remote"]
DataClassification = Literal["public", "internal", "confidential", "restricted"]
HealthStatus = Literal["healthy", "degraded", "unavailable", "misconfigured", "unknown"]
Decision = Literal["allow", "deny", "require_approval"]
Capability = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_.-]{0,63}$")]
OpaqueReference = Annotated[
    str,
    Field(
        pattern=r"^(secret:[a-zA-Z0-9_-]{1,100}|file:[a-zA-Z0-9_-]+\.env#[A-Z][A-Z0-9_]{0,99})$",
        max_length=220,
    ),
]


class TimeoutPolicy(ContractModel):
    connect_seconds: int = Field(default=10, ge=1, le=120)
    run_seconds: int = Field(default=300, ge=1, le=86_400)
    heartbeat_seconds: int = Field(default=10, ge=1, le=300)


class ModelBinding(ContractModel):
    mode: Literal["none", "control_plane", "worker_managed"] = "none"
    allowed_profile_revision_ids: tuple[UUID, ...] = Field(default=(), max_length=100)

    @model_validator(mode="after")
    def compatible(self) -> ModelBinding:
        if self.mode == "worker_managed" and len(self.allowed_profile_revision_ids) != 1:
            raise ValueError("worker-managed binding requires exactly one declared profile")
        if self.mode == "none" and self.allowed_profile_revision_ids:
            raise ValueError("no-model binding cannot declare profiles")
        return self


class WorkerSpec(ContractModel):
    kind: Literal["worker"] = "worker"
    adapter_kind: Literal["demo", "openhands_ssh_v1"] = "demo"
    execution_host_label: str = Field(default="Local demo", min_length=1, max_length=120)
    capabilities: tuple[Capability, ...] = Field(default=(), max_length=64)
    max_concurrency: int = Field(default=1, ge=1, le=128)
    labels: dict[Capability, str] = Field(default_factory=dict, max_length=32)
    timeouts: TimeoutPolicy = Field(default_factory=TimeoutPolicy)
    model_binding: ModelBinding = Field(default_factory=ModelBinding)
    # Opaque deployment manifest; paths/host credentials are server-managed, never echoed.
    deployment_configured: bool = False

    @model_validator(mode="after")
    def adapter_binding(self) -> WorkerSpec:
        if self.adapter_kind == "openhands_ssh_v1" and (
            self.model_binding.mode != "worker_managed" or self.max_concurrency != 1
        ):
            raise ValueError("legacy SSH requires worker-managed binding and concurrency one")
        if len(set(self.capabilities)) != len(self.capabilities):
            raise ValueError("capabilities must be unique")
        return self


class EgressPolicy(ContractModel):
    allowed_data: tuple[DataClassification, ...] = ("public",)
    remote_allowed: bool = False
    paid: bool = False


class CircuitPolicy(ContractModel):
    failure_threshold: int = Field(default=3, ge=1, le=100)
    cooldown_seconds: int = Field(default=30, ge=1, le=3600)
    failure_window_seconds: int = Field(default=60, ge=1, le=3600)


class ProviderSpec(ContractModel):
    kind: Literal["provider_connection"] = "provider_connection"
    provider_kind: ProviderKind
    base_url: str | None = Field(default=None, max_length=500)
    locality: Locality = "local"
    egress: EgressPolicy = Field(default_factory=EgressPolicy)
    timeouts: TimeoutPolicy = Field(default_factory=TimeoutPolicy)
    retry_policy_revision_id: UUID | None = None
    circuit: CircuitPolicy = Field(default_factory=CircuitPolicy)

    @field_validator("base_url")
    @classmethod
    def safe_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or "\\" in value
            or any(ord(c) < 33 for c in value)
        ):
            raise ValueError("endpoint must be an uncredentialed HTTP(S) URL without query")
        try:
            _ = parsed.port
        except ValueError as exc:
            raise ValueError("invalid endpoint port") from exc
        return value.rstrip("/")

    @model_validator(mode="after")
    def compatible(self) -> ProviderSpec:
        if self.provider_kind == "demo" and (self.base_url or self.locality != "local"):
            raise ValueError("DEMO has no network endpoint and must be local")
        if self.provider_kind != "demo" and not self.base_url:
            raise ValueError("network providers require an endpoint")
        if self.locality == "remote" and self.base_url and not self.base_url.startswith("https://"):
            raise ValueError("remote providers require HTTPS")
        return self


class Pricing(ContractModel):
    status: Literal["known", "unknown", "not_applicable"] = "unknown"
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    input_per_million: Decimal | None = Field(default=None, ge=0, le=1_000_000)
    cached_per_million: Decimal | None = Field(default=None, ge=0, le=1_000_000)
    output_per_million: Decimal | None = Field(default=None, ge=0, le=1_000_000)
    source: str = Field(default="Unspecified", max_length=200)
    effective_at: datetime | None = None

    @model_validator(mode="after")
    def complete(self) -> Pricing:
        prices = (self.input_per_million, self.output_per_million)
        if self.status == "known" and any(v is None for v in prices):
            raise ValueError("known pricing requires input and output unit prices")
        if self.status != "known" and any(
            v is not None for v in (*prices, self.cached_per_million)
        ):
            raise ValueError("unknown/not-applicable pricing cannot declare amounts")
        return self


class ModelProfileSpec(ContractModel):
    kind: Literal["model_profile"] = "model_profile"
    provider_revision_id: UUID
    model_identifier: str = Field(min_length=1, max_length=160)
    purposes: tuple[Capability, ...] = Field(min_length=1, max_length=32)
    capabilities: tuple[Capability, ...] = Field(default=("chat",), max_length=64)
    context_limit: int = Field(ge=1, le=10_000_000)
    output_limit: int = Field(ge=1, le=1_000_000)
    structured_json: bool = False
    tool_calls: bool = False
    streaming: bool = False
    locality: Locality = "local"
    parameters: dict[str, JsonValue] = Field(default_factory=dict, max_length=32)
    usage_reporting: Literal["exact", "partial", "none"] = "none"
    pricing: Pricing = Field(default_factory=Pricing)

    @model_validator(mode="after")
    def limits(self) -> ModelProfileSpec:
        if self.output_limit > self.context_limit:
            raise ValueError("output limit exceeds context limit")
        for capability, supported in (
            ("structured_json", self.structured_json),
            ("streaming", self.streaming),
            ("tool_calls", self.tool_calls),
        ):
            if capability in self.capabilities and not supported:
                raise ValueError("reserved capabilities must agree with support flags")
        allowed = {"temperature", "top_p", "reasoning_effort", "seed", "keep_alive"}
        if set(self.parameters) - allowed:
            raise ValueError("unsupported model parameter")
        for key, value in self.parameters.items():
            if key in {"temperature", "top_p"}:
                ceiling = 2 if key == "temperature" else 1
                if (
                    not isinstance(value, (int, float))
                    or isinstance(value, bool)
                    or not 0 <= value <= ceiling
                ):
                    raise ValueError("sampling parameters must be bounded numbers")
            elif key == "reasoning_effort":
                if not isinstance(value, str) or value not in {
                    "none",
                    "minimal",
                    "low",
                    "medium",
                    "high",
                    "xhigh",
                }:
                    raise ValueError("unsupported reasoning effort")
            elif key in {"seed", "keep_alive"}:
                ceiling = 2**31 - 1 if key == "seed" else 3600
                if type(value) is not int or not 0 <= value <= ceiling:
                    raise ValueError("seed and keep-alive must be bounded integers")
        return self


class RouteCandidate(ContractModel):
    profile_revision_id: UUID
    priority: int = Field(default=0, ge=0, le=10_000)


class SpendPolicy(ContractModel):
    allow_paid: bool = False
    max_input_tokens: int = Field(default=32_000, ge=1, le=10_000_000)
    max_output_tokens: int = Field(default=4096, ge=1, le=1_000_000)
    max_call_cost: Decimal | None = Field(default=None, ge=0, le=1_000_000)
    max_run_cost: Decimal | None = Field(default=None, ge=0, le=1_000_000)
    on_exceeded: Literal["deny", "require_approval"] = "deny"


class RoutePolicySpec(ContractModel):
    kind: Literal["route_policy"] = "route_policy"
    candidates: tuple[RouteCandidate, ...] = Field(min_length=1, max_length=32)
    required_capabilities: tuple[Capability, ...] = ()
    purposes: tuple[Capability, ...] = Field(min_length=1, max_length=32)
    allowed_data: tuple[DataClassification, ...] = ("public",)
    allow_remote: bool = False
    allow_unknown_health: bool = False
    failover_classes: tuple[FailureClass, ...] = ()
    spend: SpendPolicy = Field(default_factory=SpendPolicy)

    @model_validator(mode="after")
    def unique_candidates(self) -> RoutePolicySpec:
        if len({x.profile_revision_id for x in self.candidates}) != len(self.candidates):
            raise ValueError("candidate revisions must be unique")
        return self


class RetryRegistrySpec(RetryPolicySpec):
    kind: Literal["retry_policy"] = "retry_policy"


class PermissionPolicySpec(ContractModel):
    kind: Literal["permission_policy"] = "permission_policy"
    allowed_capabilities: tuple[Capability, ...] = ()
    denied_capabilities: tuple[Capability, ...] = ()
    approval_required_actions: tuple[Capability, ...] = ()
    filesystem_scopes: tuple[Capability, ...] = ()
    shell: Decision = "deny"
    git: Decision = "deny"
    docker: Decision = "deny"
    browser: Decision = "deny"
    network: Decision = "deny"
    remote_provider: Decision = "deny"
    sensitive_action: Literal["deny", "require_approval"] = "require_approval"
    destructive_action: Literal["deny", "require_approval"] = "deny"
    unknown_action: Literal["deny", "require_approval"] = "deny"


RegistrySpec = Annotated[
    WorkerSpec
    | ProviderSpec
    | ModelProfileSpec
    | RoutePolicySpec
    | RetryRegistrySpec
    | PermissionPolicySpec,
    Field(discriminator="kind"),
]
REGISTRY_SPEC_ADAPTER: TypeAdapter[RegistrySpec] = TypeAdapter(RegistrySpec)


class RegistryWrite(ContractModel):
    key: str = Field(min_length=1, max_length=120, pattern=r"^[a-z][a-z0-9_-]*$")
    display_name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=2000)
    enabled: bool = True
    archived: bool = False
    expected_version: int = Field(default=0, ge=0)
    idempotency_key: str = Field(min_length=8, max_length=120)
    spec: RegistrySpec
    secret_ref: OpaqueReference | None = Field(default=None, repr=False)
    deployment_ref: OpaqueReference | None = Field(default=None, repr=False)
    clear_secret: bool = False


class WorkerRuntimeFacts(ContractModel):
    slots_in_use: int = Field(default=0, ge=0, le=128)
    last_heartbeat_at: datetime | None = None
    possibly_stalled: bool = False
    validation_issues: tuple[str, ...] = ()
    validated_at: datetime | None = None
    exclusive_workspace: bool = True


class RegistryRecord(ContractModel):
    id: UUID
    revision_id: UUID
    revision: int
    version: int
    key: str
    display_name: str
    description: str
    enabled: bool
    archived: bool
    spec: RegistrySpec
    content_hash: str
    created_at: datetime
    updated_at: datetime
    created_by: UUID | None = None
    secret_status: Literal["configured", "missing", "not_required"] = "not_required"
    secret_label: str | None = None
    health: HealthStatus = "unknown"
    circuit_state: Literal["closed", "open", "half_open"] = "closed"
    worker_runtime: WorkerRuntimeFacts | None = None


class RegistryPage(ContractModel):
    items: tuple[RegistryRecord, ...]
    next_after: UUID | None = None


class ValidationReport(ContractModel):
    valid: bool
    health: HealthStatus = "unknown"
    issues: tuple[str, ...] = ()
    network_checked: bool = False
    demo: bool = False


class RegistryValidationRequest(ContractModel):
    idempotency_key: str = Field(min_length=8, max_length=120)


class RegistryAuditData(ContractModel):
    configuration_id: UUID
    revision_id: UUID
    kind: RegistryKind
    actor_id: UUID
    action: str = Field(max_length=100)


class ProviderHealthData(ContractModel):
    provider_revision_id: UUID
    status: HealthStatus
    circuit_state: Literal["closed", "open", "half_open"]
    failure_count: int = Field(ge=0)
    version: int = Field(ge=0)


class RouteRequirements(ContractModel):
    purpose: Capability
    capabilities: tuple[Capability, ...] = ()
    input_tokens: int = Field(default=0, ge=0, le=10_000_000)
    output_tokens: int = Field(default=1, ge=1, le=1_000_000)
    data_classification: DataClassification = "public"
    run_spend: Decimal | None = Field(default=None, ge=0)


class RoutePreviewRequest(ContractModel):
    route_revision_id: UUID
    requirements: RouteRequirements
    failed_profile_revision_ids: tuple[UUID, ...] = ()
    failure_class: FailureClass | None = None


class CandidateDecision(ContractModel):
    profile_revision_id: UUID
    eligible: bool
    reasons: tuple[str, ...] = ()


class RouteResolution(ContractModel):
    route_revision_id: UUID
    selected_profile_revision_id: UUID | None = None
    selected_provider_revision_id: UUID | None = None
    decision: Decision = "deny"
    reasons: tuple[str, ...] = ()
    candidates: tuple[CandidateDecision, ...] = ()
    snapshot_hash: str
    demo: bool = False


class RouteEligibilityState(ContractModel):
    revision_id: UUID
    enabled: bool
    archived: bool
    health: HealthStatus
    circuit_state: Literal["closed", "open", "half_open"]
    credential_status: Literal["configured", "missing", "not_required"]


class RouteEvaluationData(RouteResolution):
    request: RoutePreviewRequest
    observed_state: tuple[RouteEligibilityState, ...]


class Usage(ContractModel):
    input_tokens: int | None = Field(default=None, ge=0)
    cached_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    provenance: Literal["exact", "estimated", "unknown"] = "unknown"

    @model_validator(mode="after")
    def consistent_usage(self) -> Usage:
        if (
            self.cached_tokens is not None
            and self.input_tokens is not None
            and self.cached_tokens > self.input_tokens
        ):
            raise ValueError("cached token count exceeds input count")
        if (
            self.total_tokens is not None
            and self.input_tokens is not None
            and self.output_tokens is not None
            and self.total_tokens != self.input_tokens + self.output_tokens
        ):
            raise ValueError("total token count is inconsistent")
        return self


class Cost(ContractModel):
    amount: Decimal | None = Field(default=None, ge=0)
    currency: str = "USD"
    status: Literal["exact", "estimated", "unknown", "not_applicable"] = "unknown"


class ProviderTool(ContractModel):
    name: str = Field(pattern=r"^[a-zA-Z_][a-zA-Z0-9_]{0,63}$")
    description: str = Field(default="", max_length=1024)
    parameters: dict[str, JsonValue]


class ProviderToolCall(ContractModel):
    id: str = Field(min_length=1, max_length=200)
    name: str = Field(pattern=r"^[a-zA-Z_][a-zA-Z0-9_]{0,63}$")
    arguments: dict[str, JsonValue]


class ProviderRequest(ContractModel):
    purpose: Capability
    text: str = Field(max_length=262_144, repr=False)
    output_tokens: int = Field(ge=1, le=1_000_000)
    structured_schema: dict[str, JsonValue] | None = None
    tools: tuple[ProviderTool, ...] = Field(default=(), max_length=32)
    correlation_id: str = Field(min_length=1, max_length=200)
    run_id: UUID | None = None
    project_id: UUID | None = None
    task_id: UUID | None = None
    node_id: str | None = Field(default=None, max_length=120)
    data_classification: DataClassification = "public"


class ProviderFailure(ContractModel):
    failure_class: FailureClass
    code: str = Field(max_length=120)
    message: str = Field(max_length=1024)
    retryable: bool
    retry_after_seconds: float | None = Field(default=None, ge=0, le=3600)
    request_id: str | None = Field(default=None, max_length=200)


class ProviderResult(ContractModel):
    provider_kind: ProviderKind
    profile_revision_id: UUID
    provider_revision_id: UUID
    model_identifier: str
    text: str = Field(default="", max_length=262_144, repr=False)
    structured: dict[str, JsonValue] | None = None
    tool_calls: tuple[ProviderToolCall, ...] = ()
    request_id: str | None = Field(default=None, max_length=200)
    latency_ms: int = Field(default=0, ge=0)
    usage: Usage = Field(default_factory=Usage)
    failure: ProviderFailure | None = None
    finish_reason: Literal["stop", "length", "tool_calls", "cancelled", "failed"] = "stop"
    demo: bool = False


class ProviderChunk(ContractModel):
    index: int = Field(ge=0)
    text: str = Field(default="", max_length=262_144, repr=False)
    result: ProviderResult | None = None
    demo: bool = False


class AccountingRecord(ContractModel):
    id: UUID
    profile_revision_id: UUID
    provider_revision_id: UUID
    route_revision_id: UUID | None = None
    correlation_id: str
    run_id: UUID | None = None
    project_id: UUID | None = None
    task_id: UUID | None = None
    node_id: str | None = None
    request_id: str | None = None
    latency_ms: int
    usage: Usage
    pricing: Pricing
    cost: Cost
    outcome: Literal["completed", "failed", "unknown", "denied", "require_approval"]
    created_at: datetime
    demo: bool = False


class AccountingPage(ContractModel):
    items: tuple[AccountingRecord, ...]
    next_after: UUID | None = None
