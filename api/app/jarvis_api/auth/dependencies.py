"""FastAPI dependencies for session authentication and CSRF validation."""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import Depends, Request

from jarvis_api.auth.service import AuthPrincipal, AuthService
from jarvis_api.config import Settings
from jarvis_api.errors import ApiProblemError, request_id


def auth_service(request: Request) -> AuthService:
    return cast(AuthService, request.app.state.auth_service)


def settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


async def current_principal(
    request: Request,
    service: Annotated[AuthService, Depends(auth_service)],
    config: Annotated[Settings, Depends(settings)],
) -> AuthPrincipal:
    token = request.cookies.get(config.session_cookie_name)
    if not token:
        raise ApiProblemError(401, "auth.required", "Authentication is required")
    principal = await service.authenticate(session_token=token, correlation_id=request_id(request))
    if principal is None:
        raise ApiProblemError(401, "auth.required", "Authentication is required")
    return principal


async def csrf_principal(
    request: Request,
    principal: Annotated[AuthPrincipal, Depends(current_principal)],
    service: Annotated[AuthService, Depends(auth_service)],
) -> AuthPrincipal:
    if not service.valid_csrf(principal, request.headers.get("x-csrf-token")):
        raise ApiProblemError(403, "auth.csrf_rejected", "The request could not be authorized")
    return principal


CurrentPrincipal = Annotated[AuthPrincipal, Depends(current_principal)]
CsrfPrincipal = Annotated[AuthPrincipal, Depends(csrf_principal)]
