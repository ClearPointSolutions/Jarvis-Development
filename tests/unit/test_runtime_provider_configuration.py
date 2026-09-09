"""Real provider construction and hostile/native boundary regression tests."""

import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from tests.unit.test_m3_providers import REQUEST, config

from jarvis_contracts.enums import FailureClass
from jarvis_orchestrator.providers.configuration import ProviderRuntimeConfig
from jarvis_orchestrator.providers.ollama import OllamaAdapter


def test_ollama_only_configuration_does_not_resolve_openai_keys(tmp_path: Path) -> None:
    provider, profile, provider_id, profile_id = config("ollama")
    configuration = ProviderRuntimeConfig(
        allowed_endpoints=("http://mock.test",),
        credential_files={uuid4(): tmp_path / "absent"},
    )
    adapter = configuration.adapter(provider, profile, provider_id, profile_id)
    assert isinstance(adapter, OllamaAdapter)
    assert adapter.profile_revision_id == profile_id
    assert adapter.provider_revision_id == provider_id
    with pytest.raises(ValueError, match="allowlist"):
        ProviderRuntimeConfig().adapter(provider, profile, provider_id, profile_id)
    with pytest.raises(ValueError, match="demo"):
        configuration.adapter(*config("demo"))


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://mock.test/",
        "http://user:password@mock.test",
        "file:///tmp/model",
        "http://mock.test?a=1",
    ],
)
def test_configuration_rejects_ambiguous_or_credentialed_endpoints(endpoint: str) -> None:
    with pytest.raises(ValueError):
        ProviderRuntimeConfig(allowed_endpoints=(endpoint,))


def test_bounded_configuration_and_private_paths(tmp_path: Path) -> None:
    path = tmp_path / "providers.json"
    path.write_text(json.dumps({"allowed_endpoints": ["http://localhost:11439"]}))
    assert ProviderRuntimeConfig.load(path).allowed_endpoints == ("http://localhost:11439",)
    path.write_bytes(b" " * 65537)
    with pytest.raises(ValueError, match="64 KiB"):
        ProviderRuntimeConfig.load(path)
    with pytest.raises(ValueError, match="absolute"):
        ProviderRuntimeConfig(credential_files={uuid4(): Path("relative")})
    for field in ("probe_seconds", "reviewer_seconds"):
        with pytest.raises(ValueError):
            ProviderRuntimeConfig.model_validate({field: 0})


async def test_ollama_rejects_a_different_actual_model() -> None:
    adapter = OllamaAdapter(
        *config("ollama"),
        allowed_endpoints=frozenset({"http://mock.test"}),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200, json={"done": True, "model": "other-model", "message": {"content": "ok"}}
            )
        ),
    )
    result = await adapter.invoke(REQUEST)
    assert result.failure is not None
    assert result.failure.failure_class == FailureClass.PROVIDER_CONTRACT_FAILURE
    assert result.failure.code == "model_identity_mismatch"


@pytest.mark.parametrize("count", [True, -1, "12", None])
async def test_invalid_ollama_usage_remains_unknown(count: object) -> None:
    adapter = OllamaAdapter(
        *config("ollama"),
        allowed_endpoints=frozenset({"http://mock.test"}),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "done": True,
                    "message": {"content": "ok"},
                    "prompt_eval_count": count,
                    "eval_count": 2,
                },
            )
        ),
    )
    result = await adapter.invoke(REQUEST)
    assert result.failure is None
    assert result.usage.provenance == "unknown"
    assert result.usage.total_tokens is None
