"""Explicit server-side provider probe using immutable registry revisions.

Run with the orchestrator identity. No endpoint or credential is accepted from
an HTTP caller; the server-owned exact allowlist remains authoritative.
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from uuid import UUID

from jarvis_contracts.registry import ModelProfileSpec, ProviderRequest, ProviderSpec
from jarvis_orchestrator.providers.configuration import ProviderRuntimeConfig
from jarvis_persistence.database import create_async_database_engine, create_async_session_factory
from jarvis_persistence.models import ConfigurationRevisionModel


async def probe(configuration: Path, profile_id: UUID, inference: bool) -> bool:
    settings = ProviderRuntimeConfig.load(configuration)
    engine = create_async_database_engine(os.environ["DATABASE_URL"])
    try:
        async with create_async_session_factory(engine)() as session:
            row = await session.get(ConfigurationRevisionModel, profile_id)
            if row is None:
                raise ValueError("model revision is absent")
            profile = ModelProfileSpec.model_validate(row.spec_json["spec"])
            provider_row = await session.get(
                ConfigurationRevisionModel, profile.provider_revision_id
            )
            if provider_row is None:
                raise ValueError("provider revision is absent")
            provider = ProviderSpec.model_validate(provider_row.spec_json["spec"])
        adapter = settings.adapter(provider, profile, provider_row.id, profile_id)
        async with asyncio.timeout(settings.probe_seconds):
            report = await adapter.validate_connection()
        print(json.dumps({"check": "connection_and_inventory", **report.model_dump(mode="json")}))
        if not report.valid or not inference:
            return report.valid
        request = ProviderRequest(
            purpose=profile.purposes[0],
            text='Return JSON with answer equal to "ready". /no_think',
            output_tokens=min(1024, profile.output_limit),
            structured_schema={
                "type": "object",
                "properties": {"answer": {"type": "string", "enum": ["ready"]}},
                "required": ["answer"],
                "additionalProperties": False,
            },
            correlation_id="explicit-server-inference-probe",
        )
        # Inference is explicit; inventory checks never load a model or bill a call.
        result = await adapter.invoke(request)
        print(
            json.dumps(
                {
                    "check": "inference",
                    "valid": result.failure is None,
                    "profile_revision_id": str(profile_id),
                    "model_identifier": result.model_identifier,
                    "latency_ms": result.latency_ms,
                    "usage": result.usage.model_dump(mode="json"),
                    "failure_code": result.failure.code if result.failure else None,
                }
            )
        )
        return result.failure is None
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--configuration", type=Path, required=True)
    parser.add_argument("--profile-revision", type=UUID, required=True)
    parser.add_argument("--inference", action="store_true")
    args = parser.parse_args()
    try:
        if sys.platform == "win32":
            with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
                valid = runner.run(probe(args.configuration, args.profile_revision, args.inference))
        else:
            valid = asyncio.run(probe(args.configuration, args.profile_revision, args.inference))
    except Exception:
        # Never print DB URLs, credential paths, native HTTP exceptions or model text.
        print(
            '{"check":"probe","valid":false,"failure_code":"probe_configuration_or_dependency_unavailable"}'
        )
        valid = False
    raise SystemExit(0 if valid else 2)


if __name__ == "__main__":
    main()
