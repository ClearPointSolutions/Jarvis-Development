"""Dedicated durable orchestrator entrypoint; no public listener or shell."""

import asyncio
import hashlib
import logging
import signal
import sys
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

from pydantic import Field, JsonValue, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from uuid6 import uuid7

from jarvis_orchestrator.runtime.ownership import RunOwnership
from jarvis_orchestrator.runtime.service import OrchestratorService
from jarvis_persistence.database import create_async_database_engine, create_async_session_factory

if TYPE_CHECKING:
    from jarvis_orchestrator.runtime.composition import RealComposition


class OrchestratorSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="JARVIS_ORCHESTRATOR_")
    database_url: str = Field(validation_alias="DATABASE_URL")
    max_concurrency: int = Field(default=2, ge=1, le=64)
    global_concurrency: int = Field(default=2, ge=1, le=256)
    lease_seconds: int = Field(default=30, ge=5, le=600)
    poll_seconds: float = Field(default=0.2, ge=0.01, le=1)
    grace_seconds: float = Field(default=10, ge=0, le=300)
    manager_call_timeout_seconds: int = Field(default=120, ge=5, le=300)
    manager_lease_seconds: int = Field(default=180, ge=60, le=600)
    manager_max_attempts: int = Field(default=2, ge=1, le=5)
    manager_max_output_tokens: int = Field(default=2048, ge=128, le=8192)
    runtime_mode: Literal["real", "demo"] = "real"
    runtime_file: Path | None = None
    artifact_root: Path = Field(
        default=Path("var/artifacts"), validation_alias="JARVIS_ARTIFACT_ROOT"
    )

    @model_validator(mode="after")
    def manager_lease_covers_call(self) -> "OrchestratorSettings":
        if self.manager_lease_seconds < self.manager_call_timeout_seconds + 30:
            raise ValueError("Manager lease must exceed its call timeout by at least 30 seconds")
        return self


async def serve() -> None:
    settings = OrchestratorSettings()
    composition = None
    runtime_manifest_sha256 = None
    runtime_summary: dict[str, JsonValue] = {"configured": False}
    if settings.runtime_mode == "demo":
        from jarvis_orchestrator.demo.safety import install_network_guard

        install_network_guard(settings.database_url)
    else:
        if settings.runtime_file is None:
            raise ValueError("Real mode requires JARVIS_ORCHESTRATOR_RUNTIME_FILE")
        if settings.max_concurrency != 1 or settings.global_concurrency != 1:
            raise ValueError("Legacy first-test runtime requires local and global concurrency one")

        def load_composition() -> "RealComposition":
            from jarvis_orchestrator.runtime.composition import RealComposition
            from jarvis_orchestrator.runtime.configuration import RealRuntimeConfiguration

            assert settings.runtime_file is not None
            return RealComposition(
                RealRuntimeConfiguration.load(settings.runtime_file), settings.artifact_root
            )

        # Import and filesystem configuration work happens before any lease is
        # claimed, off the event loop. Never extend TTL to hide cold startup work.
        composition = await asyncio.to_thread(load_composition)
        assert settings.runtime_file is not None
        manifest_bytes = await asyncio.to_thread(settings.runtime_file.read_bytes)
        runtime_manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
        config = composition.settings
        runtime_summary = {
            "configured": True,
            "worker_revision_ids": cast(
                list[JsonValue], sorted(str(item) for item in config.workers)
            ),
            "repository_binding_count": sum(
                len(workflows) for workflows in config.project_workflows.values()
            )
            + len(config.workflows),
            "provider_endpoint_count": len(config.providers.allowed_endpoints),
            "verification_image_id": config.verification_isolation.image_id,
            "verification_profile_count": len(config.verification_isolation.profiles),
            "verification_broker_configured": bool(config.verification_isolation.broker_argv),
        }
    engine = create_async_database_engine(settings.database_url)
    ownership = RunOwnership(
        create_async_session_factory(engine),
        owner=str(uuid7()),
        ttl=timedelta(seconds=settings.lease_seconds),
        runtime_mode=settings.runtime_mode,
        runtime_manifest_sha256=runtime_manifest_sha256,
        runtime_summary=runtime_summary,
    )
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    previous = {}
    for signum in (signal.SIGINT, signal.SIGTERM):
        previous[signum] = signal.signal(signum, lambda *_args: loop.call_soon_threadsafe(stop.set))
    try:
        await OrchestratorService(
            settings.database_url,
            ownership,
            max_concurrency=settings.max_concurrency,
            global_concurrency=settings.global_concurrency,
            poll_seconds=settings.poll_seconds,
            grace_seconds=settings.grace_seconds,
            demo=settings.runtime_mode == "demo",
            artifact_root=settings.artifact_root,
            real_composition=composition,
            manager_lease_seconds=settings.manager_lease_seconds,
            manager_max_attempts=settings.manager_max_attempts,
            manager_call_timeout_seconds=settings.manager_call_timeout_seconds,
            manager_max_output_tokens=settings.manager_max_output_tokens,
        ).serve(stop)
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)
        await engine.dispose()


def run() -> None:
    logging.basicConfig(level=logging.INFO)
    if sys.platform == "win32":
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            runner.run(serve())
    else:
        asyncio.run(serve())


if __name__ == "__main__":
    run()
