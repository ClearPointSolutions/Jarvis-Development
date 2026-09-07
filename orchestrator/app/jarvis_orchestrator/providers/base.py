"""Shared, credential-safe provider boundary; native objects never leave adapters."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Callable
from typing import Protocol
from uuid import UUID

import httpx
import httpx2
import jsonschema
import openai
from pydantic import JsonValue

from jarvis_api.events.redaction import RecursiveRedactor
from jarvis_contracts.enums import FailureClass
from jarvis_contracts.registry import (
    ModelProfileSpec,
    ProviderChunk,
    ProviderFailure,
    ProviderRequest,
    ProviderResult,
    ProviderSpec,
    ProviderToolCall,
    Usage,
    ValidationReport,
)

MAX_BYTES = 2_097_152
MAX_TEXT = 262_144
SecretResolver = Callable[[str], str | None]


class ProviderAdapter(Protocol):
    async def validate_connection(self) -> ValidationReport: ...
    async def health(self) -> ValidationReport: ...
    async def invoke(self, request: ProviderRequest) -> ProviderResult: ...
    def stream(self, request: ProviderRequest) -> AsyncIterator[ProviderChunk]: ...
    def normalize_error(self, error: BaseException) -> ProviderFailure: ...
    def estimate_usage(self, request: ProviderRequest, output: str = "") -> Usage: ...


class BoundaryError(Exception):
    """Static adapter-owned failure code, never a native error message."""

    def __init__(
        self, code: str, failure_class: FailureClass = FailureClass.PROVIDER_CONTRACT_FAILURE
    ) -> None:
        self.code = code
        self.failure_class = failure_class
        super().__init__(code)


class BaseAdapter:
    def __init__(
        self,
        provider: ProviderSpec,
        profile: ModelProfileSpec,
        provider_revision_id: UUID,
        profile_revision_id: UUID,
    ) -> None:
        if (
            profile.provider_revision_id != provider_revision_id
            or profile.locality != provider.locality
        ):
            raise ValueError("Provider/profile revision or locality mismatch")
        self.provider = provider
        self.profile = profile
        self.provider_revision_id = provider_revision_id
        self.profile_revision_id = profile_revision_id
        self._redactor = RecursiveRedactor()

    def check_profile(self) -> None:
        supported = {
            "openai": {"temperature", "top_p", "reasoning_effort"},
            "ollama": {"temperature", "top_p", "seed", "keep_alive"},
            "demo": set(),
        }
        if set(self.profile.parameters) - supported[self.provider.provider_kind]:
            raise BoundaryError(
                "unsupported_provider_parameter", FailureClass.CONFIGURATION_INVALID
            )

    @staticmethod
    def check_schema(schema: dict[str, JsonValue]) -> None:
        if len(json.dumps(schema)) > 65536:
            raise BoundaryError("schema_limit", FailureClass.CONFIGURATION_INVALID)

        # A closed schema registry: no external or recursive references can be resolved.
        def refs(value: JsonValue) -> bool:
            if isinstance(value, dict):
                return (
                    "$ref" in value
                    or "$dynamicRef" in value
                    or any(refs(v) for v in value.values())
                )
            return isinstance(value, list) and any(refs(v) for v in value)

        if refs(schema):
            raise BoundaryError(
                "schema_references_not_supported", FailureClass.CONFIGURATION_INVALID
            )
        jsonschema.Draft202012Validator.check_schema(schema)

    def check_request(self, request: ProviderRequest) -> None:
        self.check_profile()
        if request.purpose not in self.profile.purposes:
            raise BoundaryError("purpose_not_supported", FailureClass.CONFIGURATION_INVALID)
        if request.output_tokens > self.profile.output_limit:
            raise BoundaryError("output_limit", FailureClass.CONFIGURATION_INVALID)
        tool_size = (
            len(json.dumps([tool.model_dump(mode="json") for tool in request.tools]))
            if request.tools
            else 0
        )
        if tool_size > 65536:
            raise BoundaryError("tools_limit", FailureClass.CONFIGURATION_INVALID)
        if len(request.text) + tool_size + request.output_tokens > self.profile.context_limit:
            raise BoundaryError("context_limit", FailureClass.CONFIGURATION_INVALID)
        if request.data_classification not in self.provider.egress.allowed_data:
            raise BoundaryError("data_policy_denied", FailureClass.SECURITY_POLICY_DENIED)
        if self.provider.locality == "remote" and not self.provider.egress.remote_allowed:
            raise BoundaryError("remote_policy_denied", FailureClass.SECURITY_POLICY_DENIED)
        if request.structured_schema is not None:
            if not self.profile.structured_json:
                raise BoundaryError(
                    "structured_output_unsupported", FailureClass.CONFIGURATION_INVALID
                )
            self.check_schema(request.structured_schema)
        if request.tools:
            if not self.profile.tool_calls:
                raise BoundaryError("tool_calls_unsupported", FailureClass.CONFIGURATION_INVALID)
            if len({tool.name for tool in request.tools}) != len(request.tools):
                raise BoundaryError("duplicate_tool_names", FailureClass.CONFIGURATION_INVALID)
            for tool in request.tools:
                self.check_schema(tool.parameters)

    def validate_tool_calls(
        self, request: ProviderRequest | None, calls: tuple[ProviderToolCall, ...]
    ) -> tuple[ProviderToolCall, ...]:
        if not calls:
            return ()
        if request is None or not request.tools or not self.profile.tool_calls:
            raise BoundaryError("unsolicited_tool_call")
        if len(calls) > 32 or len({call.id for call in calls}) != len(calls):
            raise BoundaryError("invalid_tool_call_count_or_ids")
        tools = {tool.name: tool for tool in request.tools}
        for call in calls:
            if call.name not in tools:
                raise BoundaryError("unknown_tool_call")
            if len(json.dumps(call.arguments)) > 65536:
                raise BoundaryError("tool_arguments_limit")
            jsonschema.Draft202012Validator(tools[call.name].parameters).validate(call.arguments)
            # Never silently rewrite arguments into a different operation after validation.
            if self._redactor.redact(call.model_dump(mode="json")).value != call.model_dump(
                mode="json"
            ):
                raise BoundaryError("sensitive_tool_call", FailureClass.SECURITY_POLICY_DENIED)
        return calls

    def estimate_usage(self, request: ProviderRequest, output: str = "") -> Usage:
        incoming = (len(request.text) + 3) // 4
        outgoing = (len(output) + 3) // 4
        return Usage(
            input_tokens=incoming,
            output_tokens=outgoing,
            total_tokens=incoming + outgoing,
            provenance="estimated",
        )

    def result(
        self,
        *,
        text: str = "",
        request: ProviderRequest | None = None,
        usage: Usage | None = None,
        request_id: str | None = None,
        started: float | None = None,
        failure: ProviderFailure | None = None,
        tool_calls: tuple[ProviderToolCall, ...] = (),
    ) -> ProviderResult:
        if len(text) > MAX_TEXT:
            raise BoundaryError("response_too_large")
        tool_calls = self.validate_tool_calls(request, tool_calls)
        structured: dict[str, JsonValue] | None = None
        if request and request.structured_schema is not None and not tool_calls:
            parsed: JsonValue = json.loads(text)
            jsonschema.Draft202012Validator(request.structured_schema).validate(parsed)
            if not isinstance(parsed, dict):
                raise BoundaryError("structured_output_must_be_object")
            clean = self._redactor.redact(parsed).value
            if not isinstance(clean, dict):
                raise BoundaryError("invalid_redacted_output")
            # Redaction must not turn a validated result into invalid workflow input.
            jsonschema.Draft202012Validator(request.structured_schema).validate(clean)
            structured = clean
            text = json.dumps(clean, separators=(",", ":"))
        else:
            text = self._redactor.redact_text(text)[0]
        if failure is not None:
            failure = failure.model_copy(
                update={
                    "message": self._redactor.redact_text(failure.message)[0][:1024],
                    "code": self._redactor.redact_text(failure.code)[0][:120],
                    "request_id": self.safe_id(failure.request_id),
                }
            )
        return ProviderResult(
            provider_kind=self.provider.provider_kind,
            profile_revision_id=self.profile_revision_id,
            provider_revision_id=self.provider_revision_id,
            model_identifier=self._redactor.redact_text(self.profile.model_identifier)[0],
            text=text,
            structured=structured,
            tool_calls=tool_calls,
            usage=usage or Usage(),
            request_id=self.safe_id(request_id),
            latency_ms=max(0, int((time.monotonic() - started) * 1000)) if started else 0,
            failure=failure,
            finish_reason="cancelled"
            if failure and failure.failure_class == FailureClass.USER_CANCELLED
            else "failed"
            if failure
            else "tool_calls"
            if tool_calls
            else "stop",
            demo=self.provider.provider_kind == "demo",
        )

    def safe_id(self, value: str | None) -> str | None:
        if not value:
            return None
        clean = self._redactor.redact_text(value)[0]
        return clean[:200] if clean == value else None

    def normalize_error(self, error: BaseException) -> ProviderFailure:
        code, kind, retry = "invalid_response", FailureClass.PROVIDER_CONTRACT_FAILURE, False
        request_id: str | None = None
        retry_after: float | None = None
        if isinstance(error, asyncio.CancelledError):
            code, kind = "cancelled", FailureClass.USER_CANCELLED
        elif isinstance(error, BoundaryError):
            code, kind = error.code, error.failure_class
        elif isinstance(
            error,
            (TimeoutError, httpx.TimeoutException, httpx2.TimeoutException, openai.APITimeoutError),
        ):
            code, kind, retry = "timeout", FailureClass.INFRASTRUCTURE_TIMEOUT, True
        elif isinstance(
            error, (httpx.TransportError, httpx2.TransportError, openai.APIConnectionError)
        ):
            code, kind, retry = (
                "connection_unavailable",
                FailureClass.INFRASTRUCTURE_SERVICE_UNAVAILABLE,
                True,
            )
        elif isinstance(
            error, (openai.APIStatusError, httpx.HTTPStatusError, httpx2.HTTPStatusError)
        ):
            status = (
                error.status_code
                if isinstance(error, openai.APIStatusError)
                else error.response.status_code
            )
            request_id = self.safe_id(error.response.headers.get("x-request-id"))
            if status == 429:
                code, kind, retry = "rate_limited", FailureClass.PROVIDER_RATE_LIMITED, True
                try:
                    retry_after = min(
                        3600.0, max(0.0, float(error.response.headers.get("retry-after", "0")))
                    )
                except ValueError:
                    retry_after = None
            elif status >= 500:
                code, kind, retry = "provider_unavailable", FailureClass.PROVIDER_TRANSIENT, True
            elif status in (400, 401, 403, 404):
                code, kind = "provider_misconfigured", FailureClass.CONFIGURATION_INVALID
        return ProviderFailure(
            failure_class=kind,
            code=code,
            message="Provider request " + code.replace("_", " ") + ".",
            retryable=retry,
            retry_after_seconds=retry_after,
            request_id=request_id,
        )

    async def stream(self, request: ProviderRequest) -> AsyncIterator[ProviderChunk]:
        # Buffer through validation/redaction so secrets split across native deltas cannot escape.
        result = await self._invoke(request, streaming=True)
        if not result.failure:
            yield ProviderChunk(index=0, text=result.text, demo=result.demo)
        yield ProviderChunk(index=1 if not result.failure else 0, result=result, demo=result.demo)

    async def invoke(self, request: ProviderRequest) -> ProviderResult:
        return await self._invoke(request, streaming=False)

    async def _invoke(self, request: ProviderRequest, *, streaming: bool) -> ProviderResult:
        raise NotImplementedError

    async def health(self) -> ValidationReport:
        return await self.validate_connection()

    async def validate_connection(self) -> ValidationReport:
        raise NotImplementedError


def endpoint(provider: ProviderSpec, allowed_endpoints: frozenset[str]) -> str:
    value = provider.base_url
    if not value or value not in allowed_endpoints:
        raise ValueError("Provider endpoint is not in the server-managed exact allowlist")
    return value
