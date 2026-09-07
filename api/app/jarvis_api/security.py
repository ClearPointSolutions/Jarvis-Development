"""Same-origin request enforcement and API response hardening."""

from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from uuid6 import uuid7

from jarvis_api.config import Settings
from jarvis_api.errors import problem_response

STATE_CHANGING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _is_json(content_type: str | None) -> bool:
    return content_type is not None and content_type.partition(";")[0].strip().lower() == (
        "application/json"
    )


def _security_headers(response: Response, *, secure_transport: bool) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'"
    )
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    if secure_transport:
        response.headers["Strict-Transport-Security"] = "max-age=31536000"


class SecurityBoundaryMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: object, *, settings: Settings) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._settings = settings
        self._expected_origin = settings.public_origin.rstrip("/")
        self._expected_authority = urlsplit(self._expected_origin).netloc.lower()
        self._development_hosts = {"testserver"} if settings.env != "production" else set()

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request.state.request_id = str(uuid7())
        host = request.headers.get("host", "").lower()
        response: Response
        if host != self._expected_authority and host not in self._development_hosts:
            response = problem_response(
                status_code=400,
                code="request.host_rejected",
                message="The request host is not allowed",
                request_id_value=request.state.request_id,
            )
        elif request.method in STATE_CHANGING_METHODS and request.headers.get("origin") != (
            self._expected_origin
        ):
            response = problem_response(
                status_code=403,
                code="request.origin_rejected",
                message="The request origin is not allowed",
                request_id_value=request.state.request_id,
            )
        elif request.method in STATE_CHANGING_METHODS and not _is_json(
            request.headers.get("content-type")
        ):
            response = problem_response(
                status_code=415,
                code="request.json_required",
                message="State-changing requests require JSON",
                request_id_value=request.state.request_id,
            )
        else:
            response = await call_next(request)

        response.headers["X-Request-ID"] = request.state.request_id
        _security_headers(
            response,
            secure_transport=self._settings.cookie_secure
            or self._expected_origin.startswith("https://"),
        )
        return response


def install_security_middleware(app: FastAPI, settings: Settings) -> None:
    app.add_middleware(SecurityBoundaryMiddleware, settings=settings)
