"""Stable, non-disclosing API error responses."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from jarvis_contracts.api import ApiErrorDetail, ApiErrorResponse

LOGGER = logging.getLogger("jarvis_api.errors")


class ApiProblemError(Exception):
    """An expected request failure safe to return to a browser."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        headers: dict[str, str] | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.headers = headers or {}
        self.details = details or {}


def request_id(request: Request) -> str:
    value = getattr(request.state, "request_id", None)
    return value if isinstance(value, str) else "request-unknown"


def problem_response(
    *,
    status_code: int,
    code: str,
    message: str,
    request_id_value: str,
    headers: dict[str, str] | None = None,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    payload = ApiErrorResponse(
        error=ApiErrorDetail(
            code=code,
            message=message,
            request_id=request_id_value,
            details=details or {},
        )
    )
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(mode="json"),
        headers=headers,
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiProblemError)
    async def handle_problem(request: Request, error: ApiProblemError) -> JSONResponse:
        return problem_response(
            status_code=error.status_code,
            code=error.code,
            message=error.message,
            request_id_value=request_id(request),
            headers=error.headers,
            details=error.details,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation(request: Request, _error: RequestValidationError) -> JSONResponse:
        # FastAPI's default validation body can echo the rejected input, including passwords.
        return problem_response(
            status_code=422,
            code="request.validation_failed",
            message="The request did not match the required format",
            request_id_value=request_id(request),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http(request: Request, error: StarletteHTTPException) -> JSONResponse:
        if error.status_code == 404:
            code, message = "resource.not_found", "The requested resource was not found"
        elif error.status_code == 405:
            code, message = "request.method_not_allowed", "The request method is not allowed"
        else:
            code, message = "request.rejected", "The request could not be completed"
        return problem_response(
            status_code=error.status_code,
            code=code,
            message=message,
            request_id_value=request_id(request),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, error: Exception) -> JSONResponse:
        # Deliberately omit exception text: adapter/database errors can carry secrets.
        LOGGER.error(
            "Unhandled API exception request_id=%s exception_type=%s",
            request_id(request),
            type(error).__name__,
        )
        return problem_response(
            status_code=500,
            code="internal.error",
            message="An internal error occurred",
            request_id_value=request_id(request),
        )
