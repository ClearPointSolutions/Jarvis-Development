"""Owner-only operational state from durable runtime records."""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Query, Request
from sqlalchemy import func, select

from jarvis_api.auth.dependencies import CurrentPrincipal
from jarvis_api.runtime import sessions
from jarvis_contracts.operations import SystemHealth
from jarvis_persistence.models import (
    JobModel,
    OrchestratorInstanceModel,
    ProjectModel,
    RunLeaseModel,
    RunModel,
)

router = APIRouter(prefix="/api/v1", tags=["operations"])


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
