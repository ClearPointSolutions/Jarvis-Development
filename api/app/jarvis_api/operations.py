"""Owner-only operational state from durable runtime records."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Query, Request
from sqlalchemy import func, or_, select
from uuid6 import uuid7

from jarvis_api.auth.dependencies import CsrfPrincipal, CurrentPrincipal
from jarvis_api.errors import ApiProblemError
from jarvis_api.runtime import sessions
from jarvis_contracts.base import sha256_digest
from jarvis_contracts.operations import (
    AlertEvaluationRequest,
    AlertEvaluationResult,
    AlertPage,
    AlertView,
    EmergencyStopRequest,
    EmergencyStopResult,
    OperationalDiagnostics,
    OperationalSignal,
    QualificationRecord,
    QualificationStart,
    QualificationUpdate,
    RecoveryControlRequest,
    RecoveryControlResult,
    RetentionCandidate,
    RetentionPreview,
    RetentionPreviewRequest,
    SystemHealth,
)
from jarvis_persistence.models import (
    ArtifactModel,
    EffectModel,
    JobModel,
    MergeCandidateModel,
    MissionAdmissionControlModel,
    MissionModel,
    MissionResourceReservationModel,
    OperationalAlertModel,
    OrchestratorInstanceModel,
    ProjectModel,
    ProviderHealthModel,
    QualificationRunModel,
    RecoveryGenerationModel,
    RunLeaseModel,
    RunModel,
    WorkerAssignmentModel,
    WorkerInvocationModel,
)
from jarvis_persistence.repositories import IdempotencyConflictError, IdempotencyRepository

router = APIRouter(prefix="/api/v1", tags=["operations"])

_ACTIVE_RUNS = {
    "queued",
    "claiming",
    "running",
    "pause_requested",
    "paused",
    "approval_required",
    "cancel_requested",
}
_AMBIGUOUS_EFFECTS = {"dispatched", "running", "cancel_requested", "unknown"}
_QUALIFICATION_SECONDS = {"24h": 86_400, "72h": 259_200, "7d": 604_800}


def _age(now: datetime, value: datetime | None) -> int | None:
    return None if value is None else max(0, int((now - value).total_seconds()))


def _signal(
    *,
    key: str,
    count: int,
    observed_at: datetime,
    last_progress_at: datetime | None,
    warning_after: int,
    critical_after: int,
    healthy_reason: str,
    unhealthy_reason: str,
    action: str,
    bytes_value: int | None = None,
) -> OperationalSignal:
    age = _age(observed_at, last_progress_at)
    if count == 0:
        return OperationalSignal(
            key=key,
            status="healthy",
            observed_at=observed_at,
            last_progress_at=last_progress_at,
            age_seconds=age,
            reason=healthy_reason,
            action=None,
            count=0,
            bytes=bytes_value,
        )
    status = "critical" if age is None or age >= critical_after else "warning"
    if age is not None and age < warning_after:
        status = "healthy"
    return OperationalSignal(
        key=key,
        status=status,
        observed_at=observed_at,
        last_progress_at=last_progress_at,
        age_seconds=age,
        uncertainty=("The stored heartbeat proves liveness only, not productive work."),
        reason=unhealthy_reason,
        action=action if status != "healthy" else None,
        count=count,
        bytes=bytes_value,
    )


@router.get("/system/health", response_model=SystemHealth)
async def system_health(
    request: Request,
    principal: CurrentPrincipal,
    stale_after_seconds: int = Query(default=60, ge=10, le=3600),
) -> SystemHealth:
    now = datetime.now(UTC)
    cutoff = now - timedelta(seconds=stale_after_seconds)
    async with sessions(request, principal)() as session:
        real_instance = await session.scalar(
            select(OrchestratorInstanceModel)
            .where(OrchestratorInstanceModel.runtime_mode == "real")
            .order_by(OrchestratorInstanceModel.heartbeat_at.desc())
            .limit(1)
        )
        instance = real_instance or await session.scalar(
            select(OrchestratorInstanceModel)
            .order_by(OrchestratorInstanceModel.heartbeat_at.desc())
            .limit(1)
        )
        heartbeat = instance.heartbeat_at if instance is not None else None
        accepting = await session.scalar(
            select(func.count())
            .select_from(OrchestratorInstanceModel)
            .where(
                OrchestratorInstanceModel.heartbeat_at >= cutoff,
                OrchestratorInstanceModel.draining.is_(False),
                OrchestratorInstanceModel.runtime_mode == "real",
            )
        )
        owned = (
            select(RunModel.id)
            .join(JobModel, JobModel.id == RunModel.job_id)
            .join(ProjectModel, ProjectModel.id == JobModel.project_id)
            .where(ProjectModel.owner_user_id == principal.user_id)
        )
        counts = (
            await session.execute(
                select(RunModel.status, func.count())
                .where(RunModel.id.in_(owned))
                .group_by(RunModel.status)
            )
        ).all()
        expired = await session.scalar(
            select(func.count())
            .select_from(RunLeaseModel)
            .where(
                RunLeaseModel.run_id.in_(owned),
                RunLeaseModel.released_at.is_(None),
                RunLeaseModel.expires_at < now,
            )
        )
    summary = instance.runtime_summary_json if instance is not None else {}
    fresh = heartbeat is not None and heartbeat >= cutoff
    real = instance is not None and instance.runtime_mode == "real"
    demo_only = fresh and not real and instance is not None and instance.runtime_mode == "demo"
    if demo_only:
        component = "demo_only"
        execution = "unconfigured"
        reasons = ("Only a demo orchestrator heartbeat is fresh.",)
    elif fresh and not real:
        component = "missing"
        execution = "unconfigured"
        reasons = ("The fresh orchestrator did not report a real runtime identity.",)
    elif not fresh and instance is not None:
        component = "stale"
        execution = "not_ready"
        reasons = ("The latest orchestrator heartbeat is stale.",)
    elif instance is None:
        component = "missing"
        execution = "unconfigured"
        reasons = ("No orchestrator runtime has registered.",)
    else:
        missing: list[str] = []
        if not instance.runtime_manifest_sha256 or not summary.get("configured"):
            missing.append("runtime manifest")
        if not summary.get("worker_revision_ids"):
            missing.append("selected worker")
        if not summary.get("provider_endpoint_count"):
            missing.append("provider endpoint")
        if not summary.get("repository_binding_count"):
            missing.append("repository binding")
        if not summary.get("verification_broker_configured"):
            missing.append("verification broker")
        if missing:
            component = "missing"
            execution = "not_ready"
            reasons = ("Missing real execution configuration: " + ", ".join(missing) + ".",)
        else:
            component = "configured_unverified"
            execution = "configured_unverified"
            reasons = (
                "Runtime configuration is structurally valid; worker, provider, and verifier "
                "capability still require freshness-bounded acceptance evidence.",
            )

    configured = component == "configured_unverified"
    return SystemHealth(
        observed_at=now,
        orchestrator="unknown"
        if heartbeat is None
        else "healthy"
        if heartbeat >= cutoff
        else "stale",
        last_heartbeat_at=heartbeat,
        heartbeat_stale_after_seconds=stale_after_seconds,
        accepting_instances=accepting or 0,
        run_counts={state: count for state, count in counts},
        expired_active_leases=expired or 0,
        execution=execution,
        execution_reasons=reasons,
        runtime_mode=instance.runtime_mode if instance is not None else "unknown",
        runtime_manifest_sha256=(
            instance.runtime_manifest_sha256 if instance is not None else None
        ),
        runtime_manifest="configured" if configured else component,
        worker=component,
        provider=component,
        repository_binding="configured" if configured else component,
        verification_broker=component,
    )


async def _diagnostics(
    request: Request,
    principal: CurrentPrincipal,
    *,
    stale_after_seconds: int,
    queue_stall_seconds: int,
    approval_overdue_seconds: int,
    storage_warning_bytes: int,
) -> OperationalDiagnostics:
    now = datetime.now(UTC)
    async with sessions(request, principal)() as session:
        instance = await session.scalar(
            select(OrchestratorInstanceModel)
            .order_by(OrchestratorInstanceModel.heartbeat_at.desc())
            .limit(1)
        )
        run_rows = (
            await session.scalars(
                select(RunModel)
                .join(JobModel)
                .join(ProjectModel)
                .where(ProjectModel.owner_user_id == principal.user_id)
            )
        ).all()
        run_ids = [row.id for row in run_rows]
        queued = [row for row in run_rows if row.status in {"queued", "claiming"}]
        active = [row for row in run_rows if row.status in _ACTIVE_RUNS]
        stalled_assignments = (
            (
                await session.scalars(
                    select(WorkerAssignmentModel).where(
                        WorkerAssignmentModel.run_id.in_(run_ids),
                        WorkerAssignmentModel.status.in_(("queued", "reserved", "running")),
                        WorkerAssignmentModel.created_at
                        < now - timedelta(seconds=queue_stall_seconds),
                    )
                )
            ).all()
            if run_ids
            else []
        )
        ambiguous_effects = (
            (
                await session.scalars(
                    select(EffectModel).where(
                        EffectModel.run_id.in_(run_ids), EffectModel.status.in_(_AMBIGUOUS_EFFECTS)
                    )
                )
            ).all()
            if run_ids
            else []
        )
        stalled_invocations = (
            (
                await session.execute(
                    select(
                        WorkerInvocationModel.last_activity_at,
                        WorkerInvocationModel.created_at,
                    )
                    .join(EffectModel, EffectModel.id == WorkerInvocationModel.effect_id)
                    .where(
                        EffectModel.run_id.in_(run_ids),
                        WorkerInvocationModel.possibly_stalled.is_(True),
                    )
                )
            ).all()
            if run_ids
            else []
        )
        liabilities = (
            await session.scalars(
                select(MissionResourceReservationModel)
                .join(MissionModel, MissionModel.id == MissionResourceReservationModel.mission_id)
                .join(ProjectModel, ProjectModel.id == MissionModel.project_id)
                .where(
                    ProjectModel.owner_user_id == principal.user_id,
                    MissionResourceReservationModel.status.in_(("reserved", "unknown")),
                )
            )
        ).all()
        # Provider health has no owner-scoped secret data; only aggregate status is exposed.
        providers_unhealthy = await session.scalar(
            select(func.count())
            .select_from(ProviderHealthModel)
            .where(
                or_(
                    ProviderHealthModel.status != "healthy",
                    ProviderHealthModel.observed_at.is_(None),
                    ProviderHealthModel.observed_at < now - timedelta(seconds=stale_after_seconds),
                )
            )
        )
        merge_backlog = (
            await session.scalar(
                select(func.count())
                .select_from(MergeCandidateModel)
                .where(
                    MergeCandidateModel.run_id.in_(run_ids),
                    MergeCandidateModel.status.in_(("queued", "integrating", "blocked")),
                )
            )
            if run_ids
            else 0
        )
        artifact_bytes = (
            await session.scalar(
                select(func.coalesce(func.sum(ArtifactModel.size_bytes), 0)).where(
                    ArtifactModel.run_id.in_(run_ids)
                )
            )
            if run_ids
            else 0
        )
        active_alerts = await session.scalar(
            select(func.count())
            .select_from(OperationalAlertModel)
            .where(
                OperationalAlertModel.owner_user_id == principal.user_id,
                OperationalAlertModel.status == "active",
            )
        )

    latest_queue = min((row.created_at for row in queued), default=None)
    latest_progress = max(
        (row.last_event_at for row in active if row.last_event_at is not None), default=None
    )
    latest_assignment = min((row.created_at for row in stalled_assignments), default=None)
    latest_invocation = min(
        (row.last_activity_at or row.created_at for row in stalled_invocations), default=None
    )
    heartbeat = instance.heartbeat_at if instance else None
    heartbeat_age = _age(now, heartbeat)
    heartbeat_count = int(heartbeat_age is None or heartbeat_age >= stale_after_seconds)
    approval_rows = [row for row in active if row.status == "approval_required"]
    overdue_approvals = []
    for row in approval_rows:
        approval_age = _age(now, row.last_event_at or row.started_at or row.claimable_at)
        if approval_age is not None and approval_age >= approval_overdue_seconds:
            overdue_approvals.append(row)
    oldest_approval = min(
        (row.last_event_at or row.started_at or row.claimable_at for row in overdue_approvals),
        default=None,
    )
    signals = (
        _signal(
            key="manager_freshness",
            count=heartbeat_count,
            observed_at=now,
            last_progress_at=heartbeat,
            warning_after=stale_after_seconds,
            critical_after=stale_after_seconds * 3,
            healthy_reason="The latest orchestrator heartbeat is fresh.",
            unhealthy_reason="No freshness-bounded orchestrator heartbeat is available.",
            action="Inspect the orchestrator service before admitting work.",
        ),
        _signal(
            key="useful_progress",
            count=len(active),
            observed_at=now,
            last_progress_at=latest_progress,
            warning_after=queue_stall_seconds,
            critical_after=queue_stall_seconds * 2,
            healthy_reason="No active run currently requires progress.",
            unhealthy_reason="Active work has no recent accepted progress event.",
            action="Inspect the run correlation and reconcile external effects.",
        ),
        _signal(
            key="queue_age",
            count=len(queued),
            observed_at=now,
            last_progress_at=latest_queue,
            warning_after=queue_stall_seconds,
            critical_after=queue_stall_seconds * 2,
            healthy_reason="No queued run is overdue.",
            unhealthy_reason="Queued work exceeds the configured age threshold.",
            action="Check admission controls, capacity, and runtime readiness.",
        ),
        _signal(
            key="stalled_assignments",
            count=len(stalled_assignments),
            observed_at=now,
            last_progress_at=latest_assignment,
            warning_after=queue_stall_seconds,
            critical_after=queue_stall_seconds * 2,
            healthy_reason="No assignment is classified as stalled.",
            unhealthy_reason="Assignments remain queued/reserved/running beyond the threshold.",
            action="Inspect worker health and lease identity; do not assume cancellation.",
        ),
        _signal(
            key="worker_activity",
            count=len(stalled_invocations),
            observed_at=now,
            last_progress_at=latest_invocation,
            warning_after=stale_after_seconds,
            critical_after=queue_stall_seconds,
            healthy_reason="No worker invocation is marked possibly stalled.",
            unhealthy_reason="A worker invocation is marked possibly stalled.",
            action="Reconcile the existing invocation identity before retrying.",
        ),
        OperationalSignal(
            key="lease_ambiguity",
            status="critical" if ambiguous_effects else "healthy",
            observed_at=now,
            reason=(
                "External effects have outcomes that are not yet durable."
                if ambiguous_effects
                else "No external effect currently has an ambiguous outcome."
            ),
            action=(
                "Reconcile existing effect identities; never launch replacements."
                if ambiguous_effects
                else None
            ),
            count=len(ambiguous_effects),
        ),
        OperationalSignal(
            key="provider_health",
            status="warning" if providers_unhealthy else "healthy",
            observed_at=now,
            reason=(
                "Provider health is degraded, stale, or unknown."
                if providers_unhealthy
                else "All recorded provider health observations are fresh and healthy."
            ),
            action=(
                "Inspect provider circuits; controls remain available without inference."
                if providers_unhealthy
                else None
            ),
            count=int(providers_unhealthy or 0),
        ),
        OperationalSignal(
            key="budget_liability",
            status="critical" if liabilities else "healthy",
            observed_at=now,
            reason=(
                "Maximum liability is retained for unreconciled resource use."
                if liabilities
                else "No unreconciled maximum-liability reservation is recorded."
            ),
            action=(
                "Reconcile receipts; unknown use must not be represented as zero."
                if liabilities
                else None
            ),
            count=len(liabilities),
        ),
        _signal(
            key="approval_age",
            count=len(overdue_approvals),
            observed_at=now,
            last_progress_at=oldest_approval,
            warning_after=approval_overdue_seconds,
            critical_after=approval_overdue_seconds * 2,
            healthy_reason="No approval is overdue.",
            unhealthy_reason="An approval wait exceeds the configured threshold.",
            action="Review or reject the approval; expiry does not imply authorization.",
        ),
        OperationalSignal(
            key="integration_backlog",
            status="warning" if merge_backlog else "healthy",
            observed_at=now,
            reason=(
                "Accepted candidates are waiting for serialized integration."
                if merge_backlog
                else "No candidate is waiting for integration."
            ),
            action=(
                "Inspect the accepted target head and integration lease." if merge_backlog else None
            ),
            count=int(merge_backlog or 0),
        ),
        OperationalSignal(
            key="artifact_storage",
            status="critical" if int(artifact_bytes or 0) >= storage_warning_bytes else "healthy",
            observed_at=now,
            reason=(
                "Owned artifact bytes exceed the configured pressure threshold."
                if int(artifact_bytes or 0) >= storage_warning_bytes
                else "Owned artifact bytes are below the configured pressure threshold."
            ),
            action=(
                "Generate a retention preview; protected evidence must remain."
                if int(artifact_bytes or 0) >= storage_warning_bytes
                else None
            ),
            count=1 if int(artifact_bytes or 0) >= storage_warning_bytes else 0,
            bytes=int(artifact_bytes or 0),
        ),
    )
    correlated = sum(
        1
        for row in run_rows
        if row.job_id is not None
        and (row.status in {"queued", "claiming"} or row.last_event_position > 0)
    )
    coverage = "none" if not run_rows else "complete" if correlated == len(run_rows) else "partial"
    return OperationalDiagnostics(
        observed_at=now,
        runtime_mode=instance.runtime_mode if instance else "unknown",
        instance_id=instance.id if instance else None,
        signals=signals,
        active_alerts=int(active_alerts or 0),
        correlation_coverage=coverage,
        correlation_reason=(
            "Every owned run has a durable job link and either a queue identity or event cursor."
            if coverage == "complete"
            else "One or more runs lack enough durable event evidence for a complete correlation."
        ),
    )


@router.get("/operations/diagnostics", response_model=OperationalDiagnostics)
async def operational_diagnostics(
    request: Request,
    principal: CurrentPrincipal,
    stale_after_seconds: int = Query(default=60, ge=10, le=3600),
    queue_stall_seconds: int = Query(default=900, ge=60, le=86400),
    approval_overdue_seconds: int = Query(default=86400, ge=60, le=2_592_000),
    storage_warning_bytes: int = Query(default=10_737_418_240, ge=1),
) -> OperationalDiagnostics:
    return await _diagnostics(
        request,
        principal,
        stale_after_seconds=stale_after_seconds,
        queue_stall_seconds=queue_stall_seconds,
        approval_overdue_seconds=approval_overdue_seconds,
        storage_warning_bytes=storage_warning_bytes,
    )


def _alert_view(row: OperationalAlertModel) -> AlertView:
    return AlertView(
        id=row.id,
        deduplication_key=row.deduplication_key,
        kind=row.kind,
        severity=row.severity,
        status=row.status,
        scope_type=row.scope_type,
        scope_id=row.scope_id,
        reason=row.reason,
        occurrences=row.occurrences,
        first_seen_at=row.first_seen_at,
        last_seen_at=row.last_seen_at,
        recovered_at=row.recovered_at,
    )


@router.get("/operations/alerts", response_model=AlertPage)
async def operational_alerts(request: Request, principal: CurrentPrincipal) -> AlertPage:
    async with sessions(request, principal)() as session:
        rows = (
            await session.scalars(
                select(OperationalAlertModel)
                .where(OperationalAlertModel.owner_user_id == principal.user_id)
                .order_by(OperationalAlertModel.last_seen_at.desc())
                .limit(500)
            )
        ).all()
    return AlertPage(items=tuple(_alert_view(row) for row in rows))


@router.post("/operations/alerts/evaluate", response_model=AlertEvaluationResult)
async def evaluate_alerts(
    request: Request, body: AlertEvaluationRequest, principal: CsrfPrincipal
) -> AlertEvaluationResult:
    diagnostics = await _diagnostics(
        request,
        principal,
        stale_after_seconds=body.stale_after_seconds,
        queue_stall_seconds=body.queue_stall_seconds,
        approval_overdue_seconds=body.approval_overdue_seconds,
        storage_warning_bytes=body.storage_warning_bytes,
    )
    active_signals = {
        signal.key: signal
        for signal in diagnostics.signals
        if signal.status in {"warning", "critical"}
    }
    opened = refreshed = recovered = 0
    async with sessions(request, principal).begin() as session:
        rows = (
            await session.scalars(
                select(OperationalAlertModel)
                .where(OperationalAlertModel.owner_user_id == principal.user_id)
                .with_for_update()
            )
        ).all()
        existing = {row.deduplication_key: row for row in rows}
        for key, signal in active_signals.items():
            dedup = f"owner:{principal.user_id}:{key}"
            row = existing.get(dedup)
            severity = "critical" if signal.status == "critical" else "warning"
            if row is None:
                session.add(
                    OperationalAlertModel(
                        id=uuid7(),
                        owner_user_id=principal.user_id,
                        deduplication_key=dedup,
                        kind=key,
                        severity=severity,
                        status="active",
                        scope_type="owner",
                        scope_id=str(principal.user_id),
                        reason=signal.reason,
                        details_json=signal.model_dump(mode="json"),
                        occurrences=1,
                        first_seen_at=diagnostics.observed_at,
                        last_seen_at=diagnostics.observed_at,
                    )
                )
                opened += 1
            else:
                if row.status == "recovered":
                    opened += 1
                    row.first_seen_at = diagnostics.observed_at
                    row.occurrences = 1
                else:
                    refreshed += 1
                    row.occurrences += 1
                row.status, row.severity, row.reason = "active", severity, signal.reason
                row.details_json = signal.model_dump(mode="json")
                row.last_seen_at, row.recovered_at = diagnostics.observed_at, None
        for row in rows:
            if row.status == "active" and row.kind not in active_signals:
                row.status = "recovered"
                row.recovered_at = diagnostics.observed_at
                row.last_seen_at = diagnostics.observed_at
                recovered += 1
    return AlertEvaluationResult(
        observed_at=diagnostics.observed_at,
        opened=opened,
        refreshed=refreshed,
        recovered=recovered,
        active=len(active_signals),
    )


@router.post("/operations/retention/preview", response_model=RetentionPreview)
async def retention_preview(
    request: Request, body: RetentionPreviewRequest, principal: CsrfPrincipal
) -> RetentionPreview:
    now = datetime.now(UTC)
    if body.scope != "owner" and body.scope_id is None:
        raise ApiProblemError(422, "retention.scope_id_required", "This scope needs an identity")
    async with sessions(request, principal)() as session:
        query = (
            select(ArtifactModel, RunModel)
            .join(RunModel, RunModel.id == ArtifactModel.run_id)
            .join(JobModel, JobModel.id == RunModel.job_id)
            .join(ProjectModel, ProjectModel.id == JobModel.project_id)
            .where(
                ProjectModel.owner_user_id == principal.user_id,
                ArtifactModel.created_at < now - timedelta(days=body.policy.artifacts_days),
            )
        )
        if body.scope == "run":
            query = query.where(RunModel.id == body.scope_id)
        rows = (await session.execute(query.order_by(ArtifactModel.created_at).limit(5000))).all()
        ambiguous_runs = (
            set(
                (
                    await session.scalars(
                        select(EffectModel.run_id).where(
                            EffectModel.run_id.in_([run.id for _, run in rows]),
                            EffectModel.status.in_(_AMBIGUOUS_EFFECTS),
                        )
                    )
                ).all()
            )
            if rows
            else set()
        )
    candidates = []
    protected_kinds = {"source_snapshot", "candidate_snapshot", "verification", "review", "receipt"}
    for artifact, run in rows:
        protected = (
            run.status in _ACTIVE_RUNS
            or run.id in ambiguous_runs
            or artifact.kind in protected_kinds
        )
        reason = (
            "active or ambiguous execution evidence"
            if run.status in _ACTIVE_RUNS or run.id in ambiguous_runs
            else "accepted-result/recovery provenance"
            if artifact.kind in protected_kinds
            else "older than the configured artifact retention window"
        )
        candidates.append(
            RetentionCandidate(
                identity=str(artifact.id),
                kind=artifact.kind,
                created_at=artifact.created_at,
                size_bytes=artifact.size_bytes,
                protected=protected,
                reason=reason,
            )
        )
    deletable = [item for item in candidates if not item.protected]
    return RetentionPreview(
        generated_at=now,
        candidates=tuple(candidates),
        deletable_count=len(deletable),
        protected_count=len(candidates) - len(deletable),
        reclaimable_bytes=sum(item.size_bytes for item in deletable),
    )


def _qualification_view(row: QualificationRunModel, now: datetime) -> QualificationRecord:
    end = row.ended_at or now
    observed = max(0, int((end - row.started_at).total_seconds()))
    required = _QUALIFICATION_SECONDS[row.profile]
    from jarvis_contracts.operations import QualificationObservation

    return QualificationRecord(
        id=row.id,
        profile=row.profile,
        environment_identity=row.environment_identity,
        release_identity=row.release_identity,
        status=row.status,
        started_at=row.started_at,
        ended_at=row.ended_at,
        observed_seconds=observed,
        required_seconds=required,
        wall_clock_complete=observed >= required,
        observations=tuple(
            QualificationObservation.model_validate(item) for item in row.observations_json
        ),
    )


@router.post("/operations/qualifications", response_model=QualificationRecord, status_code=201)
async def start_qualification(
    request: Request, body: QualificationStart, principal: CsrfPrincipal
) -> QualificationRecord:
    now = datetime.now(UTC)
    row = QualificationRunModel(
        id=uuid7(),
        owner_user_id=principal.user_id,
        profile=body.profile,
        environment_identity=body.environment_identity,
        release_identity=body.release_identity,
        status="running",
        started_at=now,
        observations_json=[],
        notes=body.notes,
    )
    async with sessions(request, principal).begin() as session:
        session.add(row)
    return _qualification_view(row, now)


@router.get("/operations/qualifications/{qualification_id}", response_model=QualificationRecord)
async def get_qualification(
    request: Request, qualification_id: UUID, principal: CurrentPrincipal
) -> QualificationRecord:
    now = datetime.now(UTC)
    async with sessions(request, principal)() as session:
        row = await session.scalar(
            select(QualificationRunModel).where(
                QualificationRunModel.id == qualification_id,
                QualificationRunModel.owner_user_id == principal.user_id,
            )
        )
    if row is None:
        raise ApiProblemError(404, "qualification.not_found", "Qualification was not found")
    return _qualification_view(row, now)


@router.post("/operations/qualifications/{qualification_id}", response_model=QualificationRecord)
async def update_qualification(
    request: Request,
    qualification_id: UUID,
    body: QualificationUpdate,
    principal: CsrfPrincipal,
) -> QualificationRecord:
    now = datetime.now(UTC)
    async with sessions(request, principal).begin() as session:
        row = await session.scalar(
            select(QualificationRunModel)
            .where(
                QualificationRunModel.id == qualification_id,
                QualificationRunModel.owner_user_id == principal.user_id,
            )
            .with_for_update()
        )
        if row is None:
            raise ApiProblemError(404, "qualification.not_found", "Qualification was not found")
        if row.status != "running":
            raise ApiProblemError(
                409, "qualification.terminal", "Qualification is already terminal"
            )
        if body.action == "observe":
            if body.observation is None:
                raise ApiProblemError(
                    422, "qualification.observation_required", "An observation is required"
                )
            row.observations_json = [
                *row.observations_json,
                body.observation.model_dump(mode="json"),
            ]
        elif body.action == "complete":
            elapsed = int((now - row.started_at).total_seconds())
            if elapsed < _QUALIFICATION_SECONDS[row.profile]:
                raise ApiProblemError(
                    409,
                    "qualification.duration_incomplete",
                    "Actual wall-clock duration has not reached the selected profile",
                )
            row.status, row.ended_at = "passed", now
        elif body.action == "fail":
            row.status, row.ended_at = "failed", now
        else:
            row.status, row.ended_at = "cancelled", now
        await session.flush()
        return _qualification_view(row, now)


@router.post("/operations/recovery", response_model=RecoveryControlResult)
async def recovery_control(
    request: Request, body: RecoveryControlRequest, principal: CsrfPrincipal
) -> RecoveryControlResult:
    now = datetime.now(UTC)
    async with sessions(request, principal).begin() as session:
        row = await session.scalar(
            select(RecoveryGenerationModel).where(RecoveryGenerationModel.id == 1).with_for_update()
        )
        if row is None:
            raise ApiProblemError(503, "recovery.unavailable", "Recovery ledger is unavailable")
        if row.generation != body.expected_generation:
            raise ApiProblemError(
                409, "recovery.generation_conflict", "Recovery generation changed"
            )
        ambiguous = await session.scalar(
            select(func.count())
            .select_from(EffectModel)
            .where(EffectModel.status.in_(_AMBIGUOUS_EFFECTS))
        )
        if body.action == "begin_restore":
            row.generation += 1
            row.automatic_dispatch_enabled = False
        elif ambiguous:
            raise ApiProblemError(
                409,
                "recovery.effects_ambiguous",
                "Dispatch cannot resume while external effects remain ambiguous",
            )
        else:
            row.automatic_dispatch_enabled = True
        row.reason = body.reason
        row.updated_at = now
        return RecoveryControlResult(
            generation=row.generation,
            automatic_dispatch_enabled=row.automatic_dispatch_enabled,
            reason=row.reason,
            ambiguous_effects=int(ambiguous or 0),
        )


@router.post("/operations/emergency-stop", response_model=EmergencyStopResult)
async def emergency_stop(
    request: Request, body: EmergencyStopRequest, principal: CsrfPrincipal
) -> EmergencyStopResult:
    """Fail closed globally; remote cancellation remains pending until observed."""

    now = datetime.now(UTC)
    async with sessions(request, principal).begin() as session:
        try:
            idem, fresh = await IdempotencyRepository().begin(
                session,
                scope=f"emergency-stop:{principal.user_id}",
                key=body.idempotency_key,
                request_digest=sha256_digest(body.model_dump(mode="json")),
            )
        except IdempotencyConflictError:
            raise ApiProblemError(
                409, "emergency_stop.idempotency_conflict", "Emergency-stop input changed"
            ) from None
        if not fresh:
            return EmergencyStopResult.model_validate(idem.response_json)
        recovery = await session.scalar(
            select(RecoveryGenerationModel).where(RecoveryGenerationModel.id == 1).with_for_update()
        )
        if recovery is None or recovery.generation != body.expected_recovery_generation:
            raise ApiProblemError(
                409, "emergency_stop.generation_conflict", "Recovery generation changed"
            )
        owned_missions = (
            select(MissionModel.id)
            .join(ProjectModel)
            .where(
                ProjectModel.owner_user_id == principal.user_id,
                MissionModel.lifecycle.not_in(("cancelled", "completed", "archived")),
            )
        )
        missions = (await session.scalars(owned_missions.with_for_update())).all()
        owned_runs = (
            select(RunModel)
            .join(JobModel)
            .join(ProjectModel)
            .where(
                ProjectModel.owner_user_id == principal.user_id,
                RunModel.status.in_(_ACTIVE_RUNS),
            )
            .with_for_update()
        )
        runs = (await session.scalars(owned_runs)).all()
        for mission_id in missions:
            mission = await session.get(MissionModel, mission_id)
            assert mission is not None
            mission.lifecycle = "cancelling"
            mission.waiting_reason = "emergency_stop_pending_remote_evidence"
            mission.version += 1
        for run in runs:
            run.desired_state = "cancelled"
            run.status = "cancel_requested"
            run.version += 1
        control = await session.scalar(
            select(MissionAdmissionControlModel)
            .where(MissionAdmissionControlModel.scope_key == "global")
            .with_for_update()
        )
        if control is None:
            control = MissionAdmissionControlModel(
                id=uuid7(),
                scope="global",
                scope_key="global",
                state="cancelling",
                resource_limits_json={},
            )
            session.add(control)
        else:
            control.state = "cancelling"
            control.version += 1
        recovery.generation += 1
        recovery.automatic_dispatch_enabled = False
        recovery.reason = body.reason
        recovery.updated_at = now
        result = EmergencyStopResult(
            recovery_generation=recovery.generation,
            affected_runs=len(runs),
            affected_missions=len(missions),
        )
        idem.state, idem.response_status, idem.response_json = (
            "completed",
            200,
            result.model_dump(mode="json"),
        )
        return result
