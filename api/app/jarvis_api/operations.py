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
        heartbeat = await session.scalar(select(func.max(OrchestratorInstanceModel.heartbeat_at)))
        accepting = await session.scalar(
            select(func.count())
            .select_from(OrchestratorInstanceModel)
            .where(
                OrchestratorInstanceModel.heartbeat_at >= cutoff,
                OrchestratorInstanceModel.draining.is_(False),
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
    )
