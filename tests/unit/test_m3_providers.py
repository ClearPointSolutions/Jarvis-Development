"""Local-only provider protocol and failure contract acceptance."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from uuid import uuid4

import httpx
import httpx2
import pytest

from jarvis_contracts.enums import FailureClass
from jarvis_contracts.registry import (
    ModelProfileSpec,
    ProviderRequest,
    ProviderSpec,
    Usage,
    WorkerSpec,
)
from jarvis_orchestrator.providers import (
    DemoAdapter,
    DemoScenario,
    DemoWorker,
    OllamaAdapter,
    OpenAIAdapter,
)

REQUEST = ProviderRequest(purpose="utility", text="hello", output_tokens=20, correlation_id="test")
SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}


def config(kind: str) -> tuple[Any, ...]:
    revision = uuid4()
    provider = ProviderSpec(
        provider_kind=kind, base_url=None if kind == "demo" else "http://mock.test"
    )
    profile = ModelProfileSpec(
        provider_revision_id=revision,
        model_identifier="configured-model",
        purposes=("utility",),
        context_limit=10000,
        output_limit=200,
        streaming=True,
        structured_json=True,
    )
    return provider, profile, revision, uuid4()


def native(text: str = "hello") -> dict[str, Any]:
    return {
        "id": "resp_fixture",
        "object": "response",
        "created_at": 0,
        "status": "completed",
        "model": "configured-model",
        "output": [
            {
                "type": "message",
                "id": "msg_fixture",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": text, "annotations": []}],
            }
        ],
        "usage": {
            "input_tokens": 5,
            "output_tokens": 2,
            "total_tokens": 7,
            "input_tokens_details": {"cached_tokens": 1},
            "output_tokens_details": {"reasoning_tokens": 0},
        },
    }


def openai_adapter(handler: Any, *, credential: bool = True) -> OpenAIAdapter:
    return OpenAIAdapter(
        *config("openai"),
        allowed_endpoints=frozenset({"http://mock.test"}),
        transport=httpx2.MockTransport(handler),
        secret_ref="secret:fixture" if credential else None,
        secret_resolver=lambda _: "synthetic-credential-value",
    )


async def test_openai_normal_structured_stream_and_inventory() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("models"):
            return httpx2.Response(
                200,
                json={
                    "object": "list",
                    "data": [
                        {
                            "id": "configured-model",
                            "object": "model",
                            "created": 0,
                            "owned_by": "fixture",
                        }
                    ],
                },
            )
        body = json.loads(request.content)
        seen.append(body)
        response = native('{"answer":"yes"}')
        if body.get("stream"):
            payload = (
                "data: "
                + json.dumps(
                    {"type": "response.completed", "sequence_number": 0, "response": response}
                )
                + "\n\ndata: [DONE]\n\n"
            )
            return httpx2.Response(200, text=payload, headers={"content-type": "text/event-stream"})
        return httpx2.Response(200, json=response, headers={"x-request-id": "request_fixture"})

    adapter = openai_adapter(handler)
    assert (await adapter.health()).valid
    request = REQUEST.model_copy(update={"structured_schema": SCHEMA})
    result = await adapter.invoke(request)
    assert result.failure is None
    assert result.structured == {"answer": "yes"}
    assert result.usage.provenance == "exact" and result.usage.cached_tokens == 1
    assert result.request_id == "request_fixture"
    chunks = [chunk async for chunk in adapter.stream(request)]
    assert chunks[-1].result and chunks[-1].result.failure is None
    assert seen[0]["store"] is False and seen[0]["text"]["format"]["type"] == "json_schema"


@pytest.mark.parametrize(
    ("status", "kind", "retry"),
    [
        (429, FailureClass.PROVIDER_RATE_LIMITED, True),
        (503, FailureClass.PROVIDER_TRANSIENT, True),
        (401, FailureClass.CONFIGURATION_INVALID, False),
        (404, FailureClass.CONFIGURATION_INVALID, False),
        (302, FailureClass.PROVIDER_CONTRACT_FAILURE, False),
    ],
)
async def test_openai_http_errors(status: int, kind: FailureClass, retry: bool) -> None:
    calls = 0

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal calls
        calls += 1
        return httpx2.Response(
            status,
            json={"error": {"message": "synthetic-credential-value", "type": "fixture"}},
            headers={
                "retry-after": "99999",
                "x-request-id": "safe-id",
                "location": "http://forbidden.test",
            },
        )

    result = await openai_adapter(handler).invoke(REQUEST)
    assert (
        result.failure
        and result.failure.failure_class == kind
        and result.failure.retryable == retry
    )
    assert "synthetic-credential-value" not in result.model_dump_json()
    assert calls == 1
    if status == 429:
        assert result.failure.retry_after_seconds == 3600


@pytest.mark.parametrize(
    "case", ["timeout", "transport", "invalid", "huge", "missing", "schema", "cancel"]
)
async def test_openai_contract_failures(case: str) -> None:
    async def handler(request: httpx2.Request) -> httpx2.Response:
        if case == "timeout":
            raise httpx2.ReadTimeout("sensitive", request=request)
        if case == "transport":
            raise httpx2.ConnectError("sensitive", request=request)
        if case == "cancel":
            raise asyncio.CancelledError
        if case == "huge":
            return httpx2.Response(200, content=b"x" * 2_097_153)
        if case == "invalid":
            return httpx2.Response(200, json={"wrong": True})
        return httpx2.Response(200, json=native("not JSON"))

    adapter = openai_adapter(handler, credential=case != "missing")
    result = await adapter.invoke(
        REQUEST.model_copy(update={"structured_schema": SCHEMA}) if case == "schema" else REQUEST
    )
    assert result.failure
    assert "sensitive" not in result.model_dump_json()
    if case == "cancel":
        assert result.finish_reason == "cancelled"
    if case == "missing":
        assert (await adapter.health()).health == "misconfigured"


async def test_openai_redacts_output_and_rejects_external_schema() -> None:
    adapter = openai_adapter(
        lambda _: httpx2.Response(200, json=native("synthetic-credential-value"))
    )
    assert "synthetic-credential-value" not in (await adapter.invoke(REQUEST)).text
    result = await adapter.invoke(
        REQUEST.model_copy(update={"structured_schema": {"$ref": "https://forbidden.test/schema"}})
    )
    assert result.failure and result.failure.code == "schema_references_not_supported"


def ollama_adapter(handler: Any) -> OllamaAdapter:
    return OllamaAdapter(
        *config("ollama"),
        allowed_endpoints=frozenset({"http://mock.test"}),
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.parametrize("loaded", [True, False])
async def test_ollama_inventory_warming_and_native_output(loaded: bool) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "authorization" not in request.headers
        if request.url.path in ("/api/tags", "/api/ps"):
            return httpx.Response(
                200,
                json={
                    "models": [{"name": "configured-model"}]
                    if loaded or request.url.path == "/api/tags"
                    else []
                },
            )
        body = json.loads(request.content)
        assert body["options"]["num_predict"] == 20
        payload = {
            "message": {"content": '{"answer":"yes"}'},
            "done": True,
            "prompt_eval_count": 4,
            "eval_count": 3,
        }
        return httpx.Response(
            200, text=json.dumps(payload), headers={"x-request-id": "ollama-fixture"}
        )

    adapter = ollama_adapter(handler)
    report = await adapter.health()
    assert report.valid and report.health == ("healthy" if loaded else "degraded")
    result = await adapter.invoke(REQUEST.model_copy(update={"structured_schema": SCHEMA}))
    assert result.failure is None and result.structured == {"answer": "yes"}
    assert result.usage.total_tokens == 7 and result.request_id == "ollama-fixture"
    chunks = [chunk async for chunk in adapter.stream(REQUEST)]
    assert chunks[-1].result and chunks[-1].result.failure is None


@pytest.mark.parametrize(
    "case", ["missing", "timeout", "unavailable", "malformed", "unknown", "incomplete", "huge"]
)
async def test_ollama_contract_cases(case: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if case == "timeout":
            raise httpx.ReadTimeout("secret", request=request)
        if case == "unavailable":
            raise httpx.ConnectError("secret", request=request)
        if case == "missing":
            return httpx.Response(200, json={"models": []})
        if case == "malformed":
            return httpx.Response(200, text="not JSON")
        if case == "huge":
            return httpx.Response(200, content=b"x" * 2_097_153)
        return httpx.Response(
            200, json={"message": {"content": "hello"}, "done": case != "incomplete"}
        )

    adapter = ollama_adapter(handler)
    if case == "missing":
        assert (await adapter.health()).health == "misconfigured"
        return
    result = await adapter.invoke(REQUEST)
    if case == "unknown":
        assert result.failure is None and result.usage.provenance == "unknown"
        assert result.usage.total_tokens is None
        assert adapter.estimate_usage(REQUEST, "hello").provenance == "estimated"
    else:
        assert result.failure


async def test_demo_controls_worker_and_cancellation() -> None:
    adapter = DemoAdapter(
        *config("demo"),
        scenario=DemoScenario(
            chunks=("DE", "MO"),
            usage=Usage(input_tokens=1, output_tokens=1, total_tokens=2, provenance="exact"),
        ),
    )
    assert (await adapter.health()).demo
    chunks = [chunk async for chunk in adapter.stream(REQUEST)]
    assert chunks[0].text == "DEMO" and chunks[-1].result and chunks[-1].result.demo
    slow = DemoAdapter(*config("demo"), scenario=DemoScenario(latency_seconds=10))
    task = asyncio.create_task(slow.invoke(REQUEST))
    await asyncio.sleep(0)
    task.cancel()
    assert (await task).finish_reason == "cancelled"
    assert DemoWorker(WorkerSpec()).validate().valid
    assert not DemoWorker(WorkerSpec()).validate(uuid4()).valid
    unavailable = DemoAdapter(*config("demo"), scenario=DemoScenario(available=False))
    assert not (await unavailable.health()).valid
    assert (await unavailable.invoke(REQUEST)).failure


def test_exact_egress_allowlist_and_demo_constructor() -> None:
    with pytest.raises(ValueError, match="allowlist"):
        OpenAIAdapter(*config("openai"), allowed_endpoints=frozenset({"http://other.test"}))
    with pytest.raises(ValueError, match="network"):
        DemoAdapter(*config("openai"))


async def test_sdk_ambient_headers_cannot_escape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "OPENAI_CUSTOM_HEADERS", "X-Other-Secret: ambient-canary\nAuthorization: ambient-canary"
    )
    monkeypatch.setenv("OPENAI_ORG_ID", "ambient-canary")

    def handler(request: httpx2.Request) -> httpx2.Response:
        assert "ambient-canary" not in str(request.headers)
        assert request.headers["authorization"] == "Bearer synthetic-credential-value"
        return httpx2.Response(200, json=native())

    assert (await openai_adapter(handler).invoke(REQUEST)).failure is None


async def test_demo_retry_sequence_and_secret_split() -> None:
    from jarvis_contracts.registry import ProviderFailure

    failure = ProviderFailure(
        failure_class=FailureClass.PROVIDER_RATE_LIMITED,
        code="rate_limited",
        message="token=synthetic-canary",
        retryable=True,
        retry_after_seconds=1,
    )
    adapter = DemoAdapter(
        *config("demo"),
        scenario=DemoScenario(failures=(failure,), chunks=("token=synthetic", "-canary")),
    )
    first = await adapter.invoke(REQUEST)
    assert first.failure and first.failure.retryable
    assert "synthetic-canary" not in first.model_dump_json()
    chunks = [chunk async for chunk in adapter.stream(REQUEST)]
    assert "synthetic-canary" not in "".join(chunk.model_dump_json() for chunk in chunks)
    assert adapter.attempts == 2


@pytest.mark.parametrize(
    "update",
    [
        {"purpose": "other"},
        {"output_tokens": 201},
        {"text": "x" * 10000},
        {"data_classification": "restricted"},
    ],
)
async def test_preflight_policy_denies_without_network(update: dict[str, Any]) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        pytest.fail("Rejected call must not contact provider")

    result = await openai_adapter(handler).invoke(REQUEST.model_copy(update=update))
    assert result.failure


async def test_ollama_cancel_and_native_stream_redaction() -> None:
    async def cancelled(request: httpx.Request) -> httpx.Response:
        raise asyncio.CancelledError

    assert (await ollama_adapter(cancelled).invoke(REQUEST)).finish_reason == "cancelled"

    def streamed(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text='{"message":{"content":"token=synthetic"},"done":false}\n{"message":{"content":"-canary"},"done":true}\n',
        )

    chunks = [chunk async for chunk in ollama_adapter(streamed).stream(REQUEST)]
    assert chunks[-1].result and chunks[-1].result.failure is None
    assert "synthetic-canary" not in "".join(chunk.model_dump_json() for chunk in chunks)


def deployment_values() -> dict[str, object]:
    return {
        "host_alias": "future-worker",
        "user": "jarvis",
        "ssh_key_ref": "secret:worker-key",
        "host_key_ref": "secret:pinned-host-key",
        "workspace_root": "/srv/worker/workspaces",
        "runner_path": "/srv/worker/runner.py",
        "venv_activate": "/srv/worker/venv/bin/activate",
        "invocation_root": "/srv/worker/invocations",
    }


def test_server_only_deployment_and_fixed_worker_binding() -> None:
    from jarvis_contracts.registry import ModelBinding
    from jarvis_orchestrator.providers.worker_configuration import (
        OpenHandsDeployment,
        validate_model_binding,
    )

    manifest = OpenHandsDeployment.model_validate(deployment_values())
    assert manifest.strict_host_key_checking == "yes"
    assert manifest.port == 22
    assert "/srv/worker" not in repr(manifest)
    assert "secret:worker-key" not in repr(manifest)
    assert "future-worker" not in repr(manifest)
    revision = uuid4()
    worker = WorkerSpec(
        adapter_kind="openhands_ssh_v1",
        max_concurrency=1,
        model_binding=ModelBinding(mode="worker_managed", allowed_profile_revision_ids=(revision,)),
        deployment_configured=True,
    )
    report = validate_model_binding(worker, revision)
    assert report.valid and not report.network_checked and report.health == "unknown"
    assert not validate_model_binding(worker, uuid4()).valid
    assert not validate_model_binding(worker, None).valid
    assert validate_model_binding(WorkerSpec(), None).valid
    with pytest.raises(ValueError):
        ModelBinding(mode="worker_managed", allowed_profile_revision_ids=(revision, uuid4()))
    with pytest.raises(ValueError):
        WorkerSpec(
            adapter_kind="openhands_ssh_v1",
            model_binding=ModelBinding(
                mode="control_plane", allowed_profile_revision_ids=(revision,)
            ),
        )


@pytest.mark.parametrize(
    "path",
    [
        "relative/path",
        "/",
        "//host/share",
        "/srv/../private",
        "/srv/./runner",
        "/srv//runner",
        "/srv/runner/",
        "C:\\runner",
        "/srv/runner\nnext",
        "/srv/runner\x00",
        "/srv/runner\x7f",
        "/srv/\\runner",
    ],
)
@pytest.mark.parametrize(
    "field", ["workspace_root", "runner_path", "venv_activate", "invocation_root"]
)
def test_server_deployment_rejects_noncanonical_paths(path: str, field: str) -> None:
    from jarvis_orchestrator.providers.worker_configuration import OpenHandsDeployment

    with pytest.raises(ValueError):
        OpenHandsDeployment.model_validate({**deployment_values(), field: path})


@pytest.mark.parametrize(
    "update",
    [
        {"host_key_ref": None},
        {"strict_host_key_checking": "accept-new"},
        {"strict_host_key_checking": "no"},
        {"ssh_key_ref": "file:../../private.env#KEY"},
        {"ssh_key_ref": "synthetic-raw-private-key-material"},
        {"host_key_ref": "ssh-ed25519 AAAA-real-key-material"},
        {"host_alias": "worker;command"},
        {"user": "root -oProxyCommand=bad"},
        {"port": 0},
        {"port": 65536},
        {"port": True},
        {"port": "22"},
        {"password": "synthetic-secret"},
    ],
)
def test_server_deployment_requires_opaque_refs_and_strict_host_key(
    update: dict[str, object],
) -> None:
    from jarvis_orchestrator.providers.worker_configuration import OpenHandsDeployment

    with pytest.raises(ValueError):
        OpenHandsDeployment.model_validate({**deployment_values(), **update})


def tool_request() -> ProviderRequest:
    from jarvis_contracts.registry import ProviderTool

    return REQUEST.model_copy(
        update={
            "tools": (ProviderTool(name="lookup", description="Read a fixture", parameters=SCHEMA),)
        }
    )


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("with_text", [False, True])
async def test_openai_normalizes_native_tools_and_timeouts(
    streaming: bool, with_text: bool
) -> None:
    from jarvis_contracts.registry import TimeoutPolicy

    def handler(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        assert body["tools"][0] == {
            "type": "function",
            "name": "lookup",
            "description": "Read a fixture",
            "parameters": SCHEMA,
            "strict": True,
        }
        assert request.extensions["timeout"]["connect"] == 2
        assert request.extensions["timeout"]["read"] == 9
        result = native("Tool proposed")
        if not with_text:
            result["output"] = []
        result["output"].append(
            {
                "type": "function_call",
                "id": "fc_fixture",
                "call_id": "call_fixture",
                "name": "lookup",
                "arguments": '{"answer":"yes"}',
                "status": "completed",
            }
        )
        if streaming:
            return httpx2.Response(
                200,
                text="data: "
                + json.dumps(
                    {"type": "response.completed", "sequence_number": 0, "response": result}
                )
                + "\n\ndata: [DONE]\n\n",
                headers={"content-type": "text/event-stream"},
            )
        return httpx2.Response(200, json=result)

    adapter = openai_adapter(handler)
    adapter.profile = adapter.profile.model_copy(update={"tool_calls": True})
    adapter.provider = adapter.provider.model_copy(
        update={"timeouts": TimeoutPolicy(connect_seconds=2, run_seconds=9)}
    )
    if streaming:
        chunks = [chunk async for chunk in adapter.stream(tool_request())]
        result = chunks[-1].result
    else:
        result = await adapter.invoke(tool_request())
    assert result and result.failure is None and result.finish_reason == "tool_calls"
    assert result.tool_calls[0].id == "call_fixture" and result.tool_calls[0].arguments == {
        "answer": "yes"
    }
    assert result.text == ("Tool proposed" if with_text else "")


@pytest.mark.parametrize("streaming", [False, True])
async def test_ollama_normalizes_native_tool_only_and_text(streaming: bool) -> None:
    from jarvis_contracts.registry import TimeoutPolicy

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["tools"][0]["function"]["parameters"] == SCHEMA
        assert request.extensions["timeout"]["connect"] == 2
        assert request.extensions["timeout"]["read"] == 9
        call = {"function": {"name": "lookup", "arguments": {"answer": "yes"}}}
        if streaming:
            parts = [
                {"message": {"content": "Proposed ", "tool_calls": [call]}, "done": False},
                {"message": {"content": "tool"}, "done": True},
            ]
            return httpx.Response(200, text="\n".join(json.dumps(part) for part in parts))
        return httpx.Response(200, json={"message": {"tool_calls": [call]}, "done": True})

    adapter = ollama_adapter(handler)
    adapter.profile = adapter.profile.model_copy(update={"tool_calls": True})
    adapter.provider = adapter.provider.model_copy(
        update={"timeouts": TimeoutPolicy(connect_seconds=2, run_seconds=9)}
    )
    if streaming:
        result = [chunk async for chunk in adapter.stream(tool_request())][-1].result
    else:
        result = await adapter.invoke(tool_request())
    assert result and result.failure is None and result.finish_reason == "tool_calls"
    assert result.tool_calls[0].name == "lookup" and result.tool_calls[0].arguments == {
        "answer": "yes"
    }
    assert result.tool_calls[0].id == "ollama-call-0"


@pytest.mark.parametrize("provider", ["openai", "ollama"])
@pytest.mark.parametrize(
    "case",
    [
        "unknown",
        "malformed",
        "wrong_type",
        "secret",
        "unsolicited",
        "duplicate_id",
        "too_many",
        "unsupported_output",
    ],
)
async def test_native_tool_contract_fail_closed(provider: str, case: str) -> None:
    name = "undeclared" if case == "unknown" else "lookup"
    args: object = {"answer": "token=synthetic-tool-canary" if case == "secret" else "yes"}
    if case == "wrong_type":
        args = {"answer": 3}
    if case == "malformed":
        args = "broken-json"

    def handler_openai(request: httpx2.Request) -> httpx2.Response:
        result = native("text must not hide bad tool")
        call = {
            "type": "function_call",
            "id": "fc_fixture",
            "call_id": "fixed_id",
            "name": name,
            "arguments": args if case == "malformed" else json.dumps(args),
            "status": "completed",
        }
        if case == "unsupported_output":
            result["output"].append({"type": "future_unsupported_output"})
        else:
            result["output"] += [call] * (
                33 if case == "too_many" else 2 if case == "duplicate_id" else 1
            )
        return httpx2.Response(200, json=result)

    def handler_ollama(request: httpx.Request) -> httpx.Response:
        call = {
            "id": "fixed_id",
            "type": "unsupported" if case == "unsupported_output" else "function",
            "function": {"name": name, "arguments": args},
        }
        return httpx.Response(
            200,
            json={
                "message": {
                    "content": "text must not hide bad tool",
                    "tool_calls": [call]
                    * (33 if case == "too_many" else 2 if case == "duplicate_id" else 1),
                },
                "done": True,
            },
        )

    adapter = (
        openai_adapter(handler_openai) if provider == "openai" else ollama_adapter(handler_ollama)
    )
    adapter.profile = adapter.profile.model_copy(update={"tool_calls": True})
    result = await adapter.invoke(REQUEST if case == "unsolicited" else tool_request())
    assert result.failure and not result.tool_calls
    assert "synthetic-tool-canary" not in result.model_dump_json()


async def test_demo_normalized_tools_and_schema_preflight() -> None:
    from jarvis_contracts.registry import ProviderTool, ProviderToolCall

    adapter = DemoAdapter(
        *config("demo"),
        scenario=DemoScenario(
            text="",
            tool_calls=(
                ProviderToolCall(id="DEMO-call", name="lookup", arguments={"answer": "yes"}),
            ),
        ),
    )
    adapter.profile = adapter.profile.model_copy(update={"tool_calls": True})
    result = await adapter.invoke(tool_request())
    assert (
        result.finish_reason == "tool_calls"
        and result.demo
        and result.tool_calls[0].name == "lookup"
    )
    streamed = [chunk async for chunk in adapter.stream(tool_request())][-1].result
    assert streamed and streamed.tool_calls == result.tool_calls and streamed.demo
    unsafe = tool_request().model_copy(
        update={
            "tools": (
                ProviderTool(name="lookup", parameters={"$ref": "https://forbidden.test/schema"}),
            )
        }
    )
    assert (await adapter.invoke(unsafe)).failure
    duplicate = tool_request().model_copy(update={"tools": tool_request().tools * 2})
    assert (await adapter.invoke(duplicate)).failure
    adapter.profile = adapter.profile.model_copy(update={"tool_calls": False})
    assert (await adapter.invoke(tool_request())).failure


@pytest.mark.parametrize(
    "provider,parameters",
    [
        ("openai", {"seed": 1}),
        ("openai", {"keep_alive": 1}),
        ("ollama", {"reasoning_effort": "low"}),
        ("demo", {"temperature": 1}),
    ],
)
async def test_provider_specific_parameters_do_not_silently_disappear(
    provider: str, parameters: dict[str, object]
) -> None:
    def openai_handler(request: httpx2.Request) -> httpx2.Response:
        pytest.fail("Unsupported parameters must fail before network")

    def ollama_handler(request: httpx.Request) -> httpx.Response:
        pytest.fail("Unsupported parameters must fail before network")

    adapter = (
        openai_adapter(openai_handler)
        if provider == "openai"
        else ollama_adapter(ollama_handler)
        if provider == "ollama"
        else DemoAdapter(*config("demo"))
    )
    adapter.profile = adapter.profile.model_copy(update={"parameters": parameters})
    result = await adapter.invoke(REQUEST)
    assert result.failure and result.failure.code == "unsupported_provider_parameter"
    if provider != "demo":
        assert not (await adapter.validate_connection()).valid
