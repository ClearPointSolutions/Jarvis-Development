"""Same-origin request enforcement and API response hardening."""

from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from uuid6 import uuid7

from jarvis_api.config import Settings
from jarvis_api.errors import audit_denial, problem_response, request_id, unexpected_response

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
            await audit_denial(request, "invalid_host")
            response = problem_response(
                status_code=400,
                code="request.host_rejected",
                message="The request host is not allowed",
                request_id_value=request.state.request_id,
            )
        elif request.method in STATE_CHANGING_METHODS and request.headers.get("origin") != (
            self._expected_origin
        ):
            await audit_denial(request, "invalid_origin")
            response = problem_response(
                status_code=403,
                code="request.origin_rejected",
                message="The request origin is not allowed",
                request_id_value=request.state.request_id,
            )
        elif request.method in STATE_CHANGING_METHODS and not _is_json(
            request.headers.get("content-type")
        ):
            await audit_denial(request, "invalid_content_type")
            response = problem_response(
                status_code=415,
                code="request.json_required",
                message="State-changing requests require JSON",
                request_id_value=request.state.request_id,
            )
        else:
            try:
                response = await call_next(request)
            except Exception as error:
                # Handle before ServerErrorMiddleware re-raises to the ASGI logger,
                # and keep security/cache headers on unexpected error responses.
                response = unexpected_response(request, error)

        response.headers["X-Request-ID"] = request.state.request_id
        _security_headers(
            response,
            secure_transport=self._settings.cookie_secure
            or self._expected_origin.startswith("https://"),
        )
        return response


class BoundedRequestBodyMiddleware:
    """Bound JSON before parsing, including streams without Content-Length."""

    def __init__(self, app: ASGIApp, *, maximum: int) -> None:
        self._app = app
        self._maximum = maximum

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in STATE_CHANGING_METHODS:
            await self._app(scope, receive, send)
            return
        request = Request(scope)
        content_length = request.headers.get("content-length")
        if content_length is not None and (
            not content_length.isdecimal() or len(content_length) > 10
        ):
            response = problem_response(
                status_code=400,
                code="request.invalid_length",
                message="The request length is invalid",
                request_id_value=request_id(request),
            )
            await response(scope, receive, send)
            return
        too_large = content_length is not None and int(content_length) > self._maximum
        body = bytearray()
        while not too_large:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > self._maximum:
                too_large = True
                break
            body.extend(chunk)
            if not message.get("more_body", False):
                break
        if too_large:
            await audit_denial(request, "request_too_large")
            response = problem_response(
                status_code=413,
                code="request.too_large",
                message="The request body exceeds the allowed size",
                request_id_value=request_id(request),
            )
            await response(scope, receive, send)
            return
        delivered = False

        async def replay() -> Message:
            nonlocal delivered
            if delivered:
                return await receive()
            delivered = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        await self._app(scope, replay, send)


def install_security_middleware(app: FastAPI, settings: Settings) -> None:
    app.add_middleware(BoundedRequestBodyMiddleware, maximum=settings.max_request_body_bytes)
    app.add_middleware(SecurityBoundaryMiddleware, settings=settings)
