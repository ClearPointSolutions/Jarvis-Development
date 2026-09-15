"""Truthful read-only operational projections."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from jarvis_contracts.base import ContractModel


class CurrencyUsage(ContractModel):
    currency: str
    known_subtotal: Decimal
    total: Decimal | None
    status: Literal["exact", "estimated", "unknown", "not_applicable"]
    unknown_calls: int


class RunUsage(ContractModel):
    calls: int
    total_tokens: int | None
    known_tokens: int
    unknown_usage_calls: int
    provenance: Literal["exact", "estimated", "unknown"]
    currencies: tuple[CurrencyUsage, ...]
    worker_usage: Literal["unavailable"] = "unavailable"


class SystemHealth(ContractModel):
    observed_at: datetime
    database: Literal["healthy"] = "healthy"
    orchestrator: Literal["healthy", "stale", "unknown"]
    last_heartbeat_at: datetime | None
    heartbeat_stale_after_seconds: int
    accepting_instances: int
    run_counts: dict[str, int]
    expired_active_leases: int
    control_plane: Literal["healthy"] = "healthy"
    execution: Literal["ready", "configured_unverified", "not_ready", "unconfigured"]
    execution_reasons: tuple[str, ...]
    runtime_mode: Literal["real", "demo", "unknown"]
    runtime_manifest_sha256: str | None = None
    runtime_manifest: Literal["configured", "missing", "stale", "demo_only"]
    worker: Literal["configured_unverified", "missing", "stale", "demo_only"]
    provider: Literal["configured_unverified", "missing", "stale", "demo_only"]
    repository_binding: Literal["configured", "missing", "stale", "demo_only"]
    verification_broker: Literal["configured_unverified", "missing", "stale", "demo_only"]


class OperationalSignal(ContractModel):
    """One evidence-backed signal; unknown is intentionally not healthy."""

    key: str
    status: Literal["healthy", "warning", "critical", "unknown"]
    observed_at: datetime
    last_progress_at: datetime | None = None
    age_seconds: int | None = None
    uncertainty: str | None = None
    reason: str
    action: str | None = None
    count: int = 0
    bytes: int | None = None


class OperationalDiagnostics(ContractModel):
    observed_at: datetime
    runtime_mode: Literal["real", "demo", "unknown"]
    instance_id: str | None = None
    signals: tuple[OperationalSignal, ...]
    active_alerts: int
    correlation_coverage: Literal["complete", "partial", "none"]
    correlation_reason: str


class AlertView(ContractModel):
    id: UUID
    deduplication_key: str
    kind: str
    severity: Literal["warning", "critical"]
    status: Literal["active", "recovered"]
    scope_type: str
    scope_id: str
    reason: str
    occurrences: int
    first_seen_at: datetime
    last_seen_at: datetime
    recovered_at: datetime | None = None


class AlertPage(ContractModel):
    items: tuple[AlertView, ...]


class AlertEvaluationRequest(ContractModel):
    idempotency_key: str
    stale_after_seconds: int = 60
    queue_stall_seconds: int = 900
    approval_overdue_seconds: int = 86400
    storage_warning_bytes: int = 10_737_418_240


class AlertEvaluationResult(ContractModel):
    observed_at: datetime
    opened: int
    refreshed: int
    recovered: int
    active: int


class RetentionPolicy(ContractModel):
    logs_days: int = 30
    temporary_workspaces_days: int = 7
    receipts_days: int = 365
    source_snapshots_days: int = 365
    messages_days: int = 365
    artifacts_days: int = 90


class RetentionPreviewRequest(ContractModel):
    policy: RetentionPolicy
    scope: Literal["owner", "mission", "run"] = "owner"
    scope_id: UUID | None = None


class RetentionCandidate(ContractModel):
    identity: str
    kind: str
    created_at: datetime
    size_bytes: int
    protected: bool
    reason: str


class RetentionPreview(ContractModel):
    generated_at: datetime
    candidates: tuple[RetentionCandidate, ...]
    deletable_count: int
    protected_count: int
    reclaimable_bytes: int
    execution_supported: Literal["preview_only"] = "preview_only"


class BackupManifestRecord(ContractModel):
    id: UUID
    backup_id: str
    status: Literal["building", "complete", "invalid", "restored", "blocked"]
    recovery_generation: int
    created_at: datetime
    manifest_sha256: str | None = None
    manifest: dict[str, Any]


class RecoveryControlRequest(ContractModel):
    action: Literal["begin_restore", "resume_dispatch"]
    reason: str
    expected_generation: int


class RecoveryControlResult(ContractModel):
    generation: int
    automatic_dispatch_enabled: bool
    reason: str
    ambiguous_effects: int


class EmergencyStopRequest(ContractModel):
    confirmation: Literal["STOP ALL NEW AND ACTIVE WORK"]
    expected_recovery_generation: int
    reason: str
    idempotency_key: str


class EmergencyStopResult(ContractModel):
    recovery_generation: int
    automatic_dispatch_enabled: Literal[False] = False
    affected_runs: int
    affected_missions: int
    remote_outcomes: Literal["pending_evidence"] = "pending_evidence"


class QualificationStart(ContractModel):
    profile: Literal["24h", "72h", "7d"]
    environment_identity: str
    release_identity: str
    notes: str = ""


class QualificationObservation(ContractModel):
    failure_injection: str | None = None
    external_effect_identity: str | None = None
    outcome: str
    cost: str | None = None
    storage_bytes: int | None = None


class QualificationRecord(ContractModel):
    id: UUID
    profile: Literal["24h", "72h", "7d"]
    environment_identity: str
    release_identity: str
    status: Literal["running", "passed", "failed", "cancelled"]
    started_at: datetime
    ended_at: datetime | None = None
    observed_seconds: int
    required_seconds: int
    wall_clock_complete: bool
    observations: tuple[QualificationObservation, ...]


class QualificationUpdate(ContractModel):
    action: Literal["observe", "complete", "fail", "cancel"]
    observation: QualificationObservation | None = None
