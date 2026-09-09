"""Native Ollama protocol; no assumptions about OpenAI-compatible behavior."""

from __future__ import annotations

import asyncio
import json
import time
from uuid import UUID

import httpx
from pydantic import JsonValue

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

from .base import MAX_BYTES, BaseAdapter, BoundaryError, endpoint


class OllamaAdapter(BaseAdapter):
    def __init__(
        self,
        provider: ProviderSpec,
        profile: ModelProfileSpec,
        provider_revision_id: UUID,
        profile_revision_id: UUID,
        *,
        allowed_endpoints: frozenset[str],
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(provider, profile, provider_revision_id, profile_revision_id)
        if provider.provider_kind != "ollama":
            raise ValueError("Ollama adapter requires Ollama configuration")
        self._endpoint = endpoint(provider, allowed_endpoints)
        self._transport = transport

    async def _request(
        self, path: str, body: dict[str, JsonValue] | None = None
    ) -> tuple[bytes, str | None]:
        async with (
            httpx.AsyncClient(
                transport=self._transport,
                trust_env=False,
                follow_redirects=False,
                timeout=httpx.Timeout(
                    self.provider.timeouts.run_seconds,
                    connect=self.provider.timeouts.connect_seconds,
                ),
            ) as client,
            client.stream(
                "POST" if body is not None else "GET", self._endpoint + path, json=body
            ) as response,
        ):
            response.raise_for_status()
            data = bytearray()
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data) > MAX_BYTES:
                    raise BoundaryError("response_too_large")
            return bytes(data), response.headers.get("x-request-id")

    async def list_models(self) -> tuple[str, ...]:
        try:
            async with asyncio.timeout(self.provider.timeouts.run_seconds):
                return await self._list_models()
        except (Exception, asyncio.CancelledError) as exc:
            failure = self.normalize_error(exc)
            raise BoundaryError(failure.code, failure.failure_class) from None

    async def _list_models(self) -> tuple[str, ...]:
        raw, _ = await self._request("/api/tags")
        value = json.loads(raw)
        return tuple(
            sorted(self._redactor.redact_text(model["name"])[0] for model in value["models"])
        )

    async def validate_connection(self) -> ValidationReport:
        try:
            self.check_profile()
            async with asyncio.timeout(self.provider.timeouts.run_seconds):
                models = await self.list_models()
                if self.profile.model_identifier not in models:
                    return ValidationReport(
                        valid=False,
                        health="misconfigured",
                        issues=("model_unavailable",),
                        network_checked=True,
                    )
                raw, _ = await self._request("/api/ps")
                loaded = {model["name"] for model in json.loads(raw)["models"]}
                warm = self.profile.model_identifier in loaded
                return ValidationReport(
                    valid=True,
                    health="healthy" if warm else "degraded",
                    issues=() if warm else ("model_warming",),
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
                network_checked=failure.code != "unsupported_provider_parameter",
            )

    async def _invoke(self, request: ProviderRequest, *, streaming: bool) -> ProviderResult:
        started = time.monotonic()
        try:
            self.check_request(request)
            if streaming and not self.profile.streaming:
                raise BoundaryError("streaming_unsupported", FailureClass.CONFIGURATION_INVALID)
            options: dict[str, JsonValue] = {"num_predict": request.output_tokens}
            for key in ("temperature", "top_p", "seed"):
                if key in self.profile.parameters:
                    options[key] = self.profile.parameters[key]
            body: dict[str, JsonValue] = {
                "model": self.profile.model_identifier,
                "messages": [{"role": "user", "content": request.text}],
                "stream": streaming,
                "options": options,
            }
            if request.tools:
                body["tools"] = [
                    {
                        "type": "function",
                        "function": {
                            "name": tool.name,
                            "description": tool.description,
                            "parameters": tool.parameters,
                        },
                    }
                    for tool in request.tools
                ]
            if request.structured_schema is not None:
                body["format"] = request.structured_schema
            if "keep_alive" in self.profile.parameters:
                body["keep_alive"] = self.profile.parameters["keep_alive"]
            async with asyncio.timeout(self.provider.timeouts.run_seconds):
                raw, request_id = await self._request("/api/chat", body)
            parts = (
                [json.loads(line) for line in raw.splitlines() if line]
                if streaming
                else [json.loads(raw)]
            )
            if not parts or parts[-1].get("done") is not True:
                raise BoundaryError("missing_final_response")
            texts: list[str] = []
            calls: list[ProviderToolCall] = []
            for part in parts:
                if "model" in part and part["model"] != self.profile.model_identifier:
                    raise BoundaryError("model_identity_mismatch")
                if "error" in part:
                    raise BoundaryError("provider_reported_error")
                message = part["message"]
                native_calls = message.get("tool_calls", [])
                if not isinstance(native_calls, list):
                    raise BoundaryError("invalid_tool_calls")
                for call in native_calls:
                    if call.get("type", "function") != "function":
                        raise BoundaryError("unsupported_native_output")
                    function = call["function"]
                    calls.append(
                        ProviderToolCall(
                            id=call.get("id", f"ollama-call-{len(calls)}"),
                            name=function["name"],
                            arguments=function["arguments"],
                        )
                    )
                content = message.get("content", "") if native_calls else message["content"]
                if not isinstance(content, str):
                    raise BoundaryError("invalid_content")
                texts.append(content)
            final = parts[-1]
            usage = Usage()
            if (
                type(final.get("prompt_eval_count")) is int
                and type(final.get("eval_count")) is int
                and final["prompt_eval_count"] >= 0
                and final["eval_count"] >= 0
            ):
                usage = Usage(
                    input_tokens=final["prompt_eval_count"],
                    output_tokens=final["eval_count"],
                    total_tokens=final["prompt_eval_count"] + final["eval_count"],
                    provenance="exact",
                )
            return self.result(
                text="".join(texts),
                tool_calls=tuple(calls),
                request=request,
                usage=usage,
                request_id=request_id,
                started=started,
            )
        except (Exception, asyncio.CancelledError) as exc:
            return self.result(failure=self.normalize_error(exc), started=started)
