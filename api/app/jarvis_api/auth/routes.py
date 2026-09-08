"""Versioned authentication, session, and readiness routes."""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from jarvis_api.auth.dependencies import (
    CsrfPrincipal,
    CurrentPrincipal,
    auth_service,
    settings,
)
from jarvis_api.auth.service import AuthPrincipal, AuthService, ClientMetadata
from jarvis_api.config import Settings
from jarvis_api.errors import ApiProblemError, request_id
from jarvis_contracts.api import (
    ApiErrorResponse,
    LoginRequest,
    LogoutResponse,
    ReadinessResponse,
    SessionResponse,
    SessionUser,
)

router = APIRouter(prefix="/api/v1")


def _metadata(request: Request) -> ClientMetadata:
    return ClientMetadata(
        ip_address=request.client.host if request.client is not None else None,
        user_agent=request.headers.get("user-agent"),
    )


def _session_response(principal: AuthPrincipal) -> SessionResponse:
    return SessionResponse(
        user=SessionUser(
            id=principal.user_id,
            username=principal.username,
            role="owner",
        ),
        csrf_token=principal.csrf_token,
        idle_expires_at=principal.idle_expires_at,
        absolute_expires_at=principal.absolute_expires_at,
    )


@router.post(
    "/auth/login",
    response_model=SessionResponse,
    operation_id="login",
    responses={
        401: {"model": ApiErrorResponse},
        403: {"model": ApiErrorResponse},
        415: {"model": ApiErrorResponse},
        422: {"model": ApiErrorResponse},
        429: {"model": ApiErrorResponse},
    },
    tags=["authentication"],
)
async def login(
    request: Request,
    response: Response,
    body: LoginRequest,
    service: Annotated[AuthService, Depends(auth_service)],
    config: Annotated[Settings, Depends(settings)],
) -> SessionResponse:
    result = await service.login(
        username=body.username,
        password=body.password,
        metadata=_metadata(request),
        correlation_id=request_id(request),
        previous_session_token=request.cookies.get(config.session_cookie_name),
    )
    if result.principal is None:
        if result.retry_after_seconds > 0:
            raise ApiProblemError(
                429,
                "auth.rate_limited",
                "Authentication could not be completed",
                headers={"Retry-After": str(result.retry_after_seconds)},
            )
        raise ApiProblemError(
            401, "auth.invalid_credentials", "Authentication could not be completed"
        )

    response.set_cookie(
        key=config.session_cookie_name,
        value=result.principal.session_token,
        max_age=config.session_absolute_seconds,
        httponly=True,
        secure=config.cookie_secure,
        samesite="strict",
        path="/api/v1",
    )
    return _session_response(result.principal)


@router.get(
    "/session",
    response_model=SessionResponse,
    operation_id="get_session",
    responses={401: {"model": ApiErrorResponse}},
    tags=["authentication"],
)
async def session(principal: CurrentPrincipal) -> SessionResponse:
    return _session_response(principal)


@router.post(
    "/auth/logout",
    response_model=LogoutResponse,
    operation_id="logout",
    responses={
        401: {"model": ApiErrorResponse},
        403: {"model": ApiErrorResponse},
        415: {"model": ApiErrorResponse},
    },
    tags=["authentication"],
)
async def logout(
    request: Request,
    response: Response,
    principal: CsrfPrincipal,
    service: Annotated[AuthService, Depends(auth_service)],
    config: Annotated[Settings, Depends(settings)],
) -> LogoutResponse:
    revoked = await service.logout(principal, correlation_id=request_id(request))
    response.delete_cookie(
        key=config.session_cookie_name,
        httponly=True,
        secure=config.cookie_secure,
        samesite="strict",
        path="/api/v1",
    )
    return LogoutResponse(revoked=revoked)


@router.get(
    "/system/readiness",
    response_model=ReadinessResponse,
    operation_id="get_readiness",
    responses={401: {"model": ApiErrorResponse}, 503: {"model": ApiErrorResponse}},
    tags=["system"],
)
async def readiness(request: Request, _principal: CurrentPrincipal) -> ReadinessResponse:
    factory = cast(async_sessionmaker[AsyncSession], request.app.state.session_factory)
    try:
        async with factory() as database_session:
            await database_session.execute(text("SELECT 1"))
            revision = await database_session.scalar(
                text("SELECT version_num FROM alembic_version LIMIT 1")
            )
    except SQLAlchemyError as error:
        raise ApiProblemError(
            503,
            "system.not_ready",
            "The service is not ready",
            details={"database": "unavailable"},
        ) from error
    if revision != "0006":
        raise ApiProblemError(
            503,
            "system.not_ready",
            "The service is not ready",
            details={"database": "migration_required"},
        )
    return ReadinessResponse(status="ready", database="ready")
