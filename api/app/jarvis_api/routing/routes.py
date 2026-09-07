"""Owner-only route preview and immutable usage query API."""

from __future__ import annotations

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from jarvis_api.auth.dependencies import CsrfPrincipal, CurrentPrincipal
from jarvis_api.errors import ApiProblemError, request_id
from jarvis_api.events.normalizer import EventIntent
from jarvis_api.registry.service import RegistryService
from jarvis_api.routing.observability import event_writer, lock_events
from jarvis_api.routing.policies import resolve_route
from jarvis_contracts.enums import EventMode, EventSeverity, EventVisibility
from jarvis_contracts.events import EventSource
from jarvis_contracts.registry import (
    AccountingPage,
    AccountingRecord,
    ModelProfileSpec,
    RegistryRecord,
    RouteEligibilityState,
    RouteEvaluationData,
    RoutePolicySpec,
    RoutePreviewRequest,
    RouteResolution,
)
from jarvis_persistence.models import ModelCallModel
from jarvis_persistence.testing import SystemClock

router = APIRouter(prefix="/api/v1", tags=["routing"])


@router.post("/routing/preview", response_model=RouteResolution, operation_id="preview_route")
async def preview_route(
    request: Request,
    body: RoutePreviewRequest,
    principal: CsrfPrincipal,
) -> RouteResolution:
    if principal.role != "owner":
        raise ApiProblemError(403, "routing.forbidden", "Owner access is required")
    service = cast(RegistryService, request.app.state.registry_service)
    factory = cast(async_sessionmaker[AsyncSession], request.app.state.session_factory)
    async with factory() as session, session.begin():
        await lock_events(session)
        result = await _resolve_snapshot(service, body)
        await event_writer().append(
            session,
            EventIntent(
                occurred_at=SystemClock().now(),
                type="model.route_selected",
                severity=EventSeverity.INFO,
                mode=EventMode.DEMO if result.demo else EventMode.REAL,
                visibility=EventVisibility.OWNER,
                source=EventSource(kind="api", name="route_preview", instance_id="m3"),
                correlation_id=request_id(request),
                data=result.model_dump(mode="json"),
            ),
        )
    return result


async def _resolve_snapshot(service: RegistryService, body: RoutePreviewRequest) -> RouteResolution:
    route = await service.get_revision(body.route_revision_id)
    if not isinstance(route.spec, RoutePolicySpec):
        raise ApiProblemError(422, "routing.invalid", "A route policy revision is required")
    records: dict[UUID, RegistryRecord] = {}
    for candidate in route.spec.candidates:
        try:
            profile = await service.get_revision(candidate.profile_revision_id)
            current = await service.get(profile.spec.kind, profile.id)
            if not current.enabled or current.archived:
                profile = profile.model_copy(update={"enabled": False})
            records[profile.revision_id] = profile
            if isinstance(profile.spec, ModelProfileSpec):
                provider = await service.get_revision(profile.spec.provider_revision_id)
                current_provider = await service.get(provider.spec.kind, provider.id)
                if not current_provider.enabled or current_provider.archived:
                    provider = provider.model_copy(update={"enabled": False})
                records[provider.revision_id] = provider
        except ApiProblemError as exc:
            if exc.status_code not in {404, 422}:
                raise
    current_route = await service.get("route_policy", route.id)
    if not current_route.enabled or current_route.archived:
        route = route.model_copy(update={"enabled": False})
    result = resolve_route(body, route, records)
    return RouteEvaluationData(
        **result.model_dump(),
        request=body,
        observed_state=tuple(
            RouteEligibilityState(
                revision_id=row.revision_id,
                enabled=row.enabled,
                archived=row.archived,
                health=row.health,
                circuit_state=row.circuit_state,
                credential_status=row.secret_status,
            )
            for row in (route, *[records[key] for key in sorted(records)])
        ),
    )


@router.get("/accounting", response_model=AccountingPage, operation_id="list_accounting")
async def list_accounting(
    request: Request,
    principal: CurrentPrincipal,
    after: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> AccountingPage:
    if principal.role != "owner":
        raise ApiProblemError(403, "accounting.forbidden", "Owner access is required")
    factory = cast(async_sessionmaker[AsyncSession], request.app.state.session_factory)
    async with factory() as session:
        statement = select(ModelCallModel).order_by(ModelCallModel.id).limit(limit + 1)
        if after:
            statement = statement.where(ModelCallModel.id > after)
        rows = list((await session.scalars(statement)).all())
    return AccountingPage(
        items=tuple(AccountingRecord.model_validate(row.record_json) for row in rows[:limit]),
        next_after=rows[limit - 1].id if len(rows) > limit else None,
    )
