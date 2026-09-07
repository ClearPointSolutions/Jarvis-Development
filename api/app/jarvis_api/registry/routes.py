"""Authenticated, CSRF-protected M3 registry operations."""

from __future__ import annotations

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Query, Request

from jarvis_api.auth.dependencies import CsrfPrincipal, CurrentPrincipal
from jarvis_api.auth.service import AuthPrincipal
from jarvis_api.errors import ApiProblemError, request_id
from jarvis_api.registry.service import RegistryService
from jarvis_contracts.registry import (
    RegistryKind,
    RegistryPage,
    RegistryRecord,
    RegistryValidationRequest,
    RegistryWrite,
    ValidationReport,
)

router = APIRouter(prefix="/api/v1/registry", tags=["registry"])


def _service(request: Request, principal: AuthPrincipal) -> RegistryService:
    if principal.role != "owner":
        raise ApiProblemError(403, "registry.forbidden", "Owner access is required")
    return cast(RegistryService, request.app.state.registry_service)


@router.get("/{kind}", response_model=RegistryPage, operation_id="list_registry")
async def list_registry(
    request: Request,
    kind: RegistryKind,
    principal: CurrentPrincipal,
    after: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> RegistryPage:
    return await _service(request, principal).list(kind, after, limit)


@router.post("/{kind}", response_model=RegistryRecord, operation_id="create_registry")
async def create_registry(
    request: Request,
    kind: RegistryKind,
    body: RegistryWrite,
    principal: CsrfPrincipal,
) -> RegistryRecord:
    return await _service(request, principal).write(
        kind, body, actor_id=principal.user_id, correlation_id=request_id(request)
    )


@router.get("/{kind}/{id}", response_model=RegistryRecord, operation_id="get_registry")
async def get_registry(
    request: Request,
    kind: RegistryKind,
    id: UUID,
    principal: CurrentPrincipal,
) -> RegistryRecord:
    return await _service(request, principal).get(kind, id)


@router.put("/{kind}/{id}", response_model=RegistryRecord, operation_id="update_registry")
async def update_registry(
    request: Request,
    kind: RegistryKind,
    id: UUID,
    body: RegistryWrite,
    principal: CsrfPrincipal,
) -> RegistryRecord:
    return await _service(request, principal).write(
        kind,
        body,
        actor_id=principal.user_id,
        correlation_id=request_id(request),
        configuration_id=id,
    )


@router.get(
    "/{kind}/{id}/revisions",
    response_model=RegistryPage,
    operation_id="list_registry_revisions",
)
async def list_registry_revisions(
    request: Request,
    kind: RegistryKind,
    id: UUID,
    principal: CurrentPrincipal,
    after: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> RegistryPage:
    return await _service(request, principal).revisions(kind, id, after, limit)


@router.post(
    "/{kind}/{id}/validate", response_model=ValidationReport, operation_id="validate_registry"
)
async def validate_registry(
    request: Request,
    kind: RegistryKind,
    id: UUID,
    body: RegistryValidationRequest,
    principal: CsrfPrincipal,
) -> ValidationReport:
    return await _service(request, principal).validate(
        kind,
        id,
        idempotency_key=body.idempotency_key,
        actor_id=principal.user_id,
        correlation_id=request_id(request),
    )
