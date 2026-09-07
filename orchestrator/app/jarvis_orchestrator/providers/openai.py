"""OpenAI Responses API adapter tested against the pinned SDK, without SDK retries."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any
from uuid import UUID

import httpx2
from openai import AsyncOpenAI

from jarvis_api.events.redaction import RecursiveRedactor
from jarvis_contracts.enums import FailureClass
from jarvis_contracts.registry import (
    ModelProfileSpec,
    ProviderRequest,
    ProviderResult,
    ProviderSpec,
    ProviderToolCall,
    Usage,
    ValidationReport,
)

from .base import MAX_BYTES, BaseAdapter, BoundaryError, SecretResolver, endpoint


class OpenAIAdapter(BaseAdapter):
    def __init__(
        self,
        provider: ProviderSpec,
        profile: ModelProfileSpec,
        provider_revision_id: UUID,
        profile_revision_id: UUID,
        *,
        allowed_endpoints: frozenset[str],
        transport: httpx2.AsyncBaseTransport | None = None,
        secret_ref: str | None = None,
        secret_resolver: SecretResolver | None = None,
    ) -> None:
        super().__init__(provider, profile, provider_revision_id, profile_revision_id)
        if provider.provider_kind != "openai":
            raise ValueError("OpenAI adapter requires OpenAI configuration")
        self._endpoint = endpoint(provider, allowed_endpoints)
        self._transport = transport
        self._secret_ref = secret_ref
        self._resolver = secret_resolver

    def _client(self) -> AsyncOpenAI:
        key = self._resolver(self._secret_ref) if self._resolver and self._secret_ref else None
        if not key:
            raise BoundaryError("missing_credential", FailureClass.CONFIGURATION_INVALID)
        self._redactor = RecursiveRedactor((key,))

        async def outgoing(request: httpx2.Request) -> None:
            if str(request.url) not in {self._endpoint + "/models", self._endpoint + "/responses"}:
                raise BoundaryError("endpoint_denied", FailureClass.SECURITY_POLICY_DENIED)
            # SDK ambient custom headers must never import unrelated credential values.
            for name in tuple(request.headers):
                if name not in {"host", "content-length", "content-type", "accept"}:
                    del request.headers[name]
            request.headers["authorization"] = "Bearer " + key

        async def bound(response: httpx2.Response) -> None:
            data = bytearray()
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data) > MAX_BYTES:
                    await response.aclose()
                    raise BoundaryError("response_too_large")
            # Public response.read caches content; use stream replacement to retain that behavior.
            response.stream = httpx2.ByteStream(bytes(data))
            response.is_stream_consumed = False
            await response.aread()

        timeout = httpx2.Timeout(
            self.provider.timeouts.run_seconds, connect=self.provider.timeouts.connect_seconds
        )
        client = httpx2.AsyncClient(
            transport=self._transport,
            trust_env=False,
            follow_redirects=False,
            timeout=timeout,
            event_hooks={"response": [bound], "request": [outgoing]},
        )
        return AsyncOpenAI(
            api_key=key,
            admin_api_key="",
            organization="",
            project="",
            webhook_secret="",
            base_url=self._endpoint,
            http_client=client,
            max_retries=0,
            timeout=timeout,
        )

    async def list_models(self) -> tuple[str, ...]:
        try:
            return await self._list_models()
        except (Exception, asyncio.CancelledError) as exc:
            failure = self.normalize_error(exc)
            raise BoundaryError(failure.code, failure.failure_class) from None

    async def _list_models(self) -> tuple[str, ...]:
        async with asyncio.timeout(self.provider.timeouts.run_seconds), self._client() as client:
            page = await client.models.list()
            return tuple(sorted(self._redactor.redact_text(model.id)[0] for model in page.data))

    async def validate_connection(self) -> ValidationReport:
        try:
            self.check_profile()
            models = await self.list_models()
            available = self.profile.model_identifier in models
            return ValidationReport(
                valid=available,
                health="healthy" if available else "misconfigured",
                issues=() if available else ("model_unavailable",),
                network_checked=True,
            )
        except (Exception, asyncio.CancelledError) as exc:
            failure = self.normalize_error(exc)
            return ValidationReport(
                valid=False,
                health="misconfigured"
                if failure.failure_class == FailureClass.CONFIGURATION_INVALID
                else "unavailable",
                issues=(failure.code,),
                network_checked=failure.code
                not in {"missing_credential", "unsupported_provider_parameter"},
            )

    async def _invoke(self, request: ProviderRequest, *, streaming: bool) -> ProviderResult:
        started = time.monotonic()
        try:
            self.check_request(request)
            if streaming and not self.profile.streaming:
                raise BoundaryError("streaming_unsupported", FailureClass.CONFIGURATION_INVALID)
            params: dict[str, Any] = {
                "model": self.profile.model_identifier,
                "input": request.text,
                "max_output_tokens": request.output_tokens,
                "store": False,
            }
            for key in ("temperature", "top_p"):
                if key in self.profile.parameters:
                    params[key] = self.profile.parameters[key]
            if "reasoning_effort" in self.profile.parameters:
                params["reasoning"] = {"effort": self.profile.parameters["reasoning_effort"]}
            if request.tools:
                params["tools"] = [
                    {
                        "type": "function",
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters,
                        "strict": True,
                    }
                    for tool in request.tools
                ]
            if request.structured_schema is not None:
                params["text"] = {
                    "format": {
                        "type": "json_schema",
                        "name": "jarvis_result",
                        "strict": True,
                        "schema": request.structured_schema,
                    }
                }
            async with (
                asyncio.timeout(self.provider.timeouts.run_seconds),
                self._client() as client,
            ):
                if streaming:
                    response = None
                    native_request_id = None
                    async with await client.responses.create(**params, stream=True) as events:
                        native_request_id = events.response.headers.get("x-request-id")
                        async for event in events:
                            if event.type == "response.completed":
                                response = event.response
                            elif event.type in ("response.failed", "error", "response.incomplete"):
                                raise BoundaryError("incomplete_stream")
                    if response is None:
                        raise BoundaryError("missing_final_response")
                else:
                    response = await client.responses.create(**params)
                    native_request_id = getattr(response, "_request_id", None)
                if response.status != "completed":
                    raise BoundaryError("invalid_response")
                calls: list[ProviderToolCall] = []
                for output in response.output:
                    if output.type == "function_call":
                        calls.append(
                            ProviderToolCall(
                                id=output.call_id,
                                name=output.name,
                                arguments=json.loads(output.arguments),
                            )
                        )
                    elif output.type not in {"message", "reasoning"}:
                        raise BoundaryError("unsupported_native_output")
                if not response.output_text and not calls:
                    raise BoundaryError("invalid_response")
                usage = Usage()
                if response.usage is not None:
                    native = response.usage
                    usage = Usage(
                        input_tokens=native.input_tokens,
                        output_tokens=native.output_tokens,
                        cached_tokens=native.input_tokens_details.cached_tokens,
                        total_tokens=native.total_tokens,
                        provenance="exact",
                    )
                return self.result(
                    text=response.output_text,
                    tool_calls=tuple(calls),
                    request=request,
                    usage=usage,
                    request_id=native_request_id or response.id,
                    started=started,
                )
        except (Exception, asyncio.CancelledError) as exc:
            return self.result(failure=self.normalize_error(exc), started=started)
