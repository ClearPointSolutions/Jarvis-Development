"""Local test-only event producer; never imported by the production API."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy.engine import make_url

from jarvis_api.events.normalizer import EventIntent, EventNormalizer, EventWriter
from jarvis_api.events.redaction import RecursiveRedactor
from jarvis_contracts.enums import EventMode, EventSeverity, EventVisibility
from jarvis_contracts.events import EventScope, EventSource
from jarvis_contracts.ids import RunId
from jarvis_persistence.database import (
    create_async_database_engine,
    create_async_session_factory,
)
from jarvis_persistence.repositories import EventRepository


async def produce() -> None:
    url = os.environ["JARVIS_BROWSER_DATABASE_URL"]
    parsed = make_url(url)
    if parsed.host not in {"127.0.0.1", "localhost", "::1"} or not (
        parsed.database or ""
    ).startswith("jarvis_m2_browser_"):
        raise ValueError("browser fixtures require an isolated loopback test database")
    engine = create_async_database_engine(url)
    writer = EventWriter(
        normalizer=EventNormalizer(
            redactor=RecursiveRedactor(),
            artifact_sink=None,
            inline_bytes=32_768,
            max_bytes=65_536,
        ),
        repository=EventRepository(),
    )
    try:
        async with create_async_session_factory(engine).begin() as session:
            event = await writer.append(
                session,
                EventIntent(
                    occurred_at=datetime.now(UTC),
                    type="command.output_summary",
                    severity=EventSeverity.INFO,
                    mode=EventMode.DEMO,
                    visibility=EventVisibility.OWNER,
                    scope=EventScope(run_id=RunId(UUID(os.environ["JARVIS_BROWSER_RUN_ID"]))),
                    source=EventSource(kind="local_cli", name="browser-test"),
                    correlation_id="m2-browser-integration",
                    data={
                        "stdout": "Verified local browser event",
                        "password": "synthetic-" + "event-canary",
                    },
                ),
            )
            if "synthetic-" + "event-canary" in event.event.model_dump_json():
                raise RuntimeError("event canary crossed persistence normalization")
        print(
            json.dumps(
                {"position": event.event.global_position, "sequence": event.event.run_sequence}
            )
        )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(cast(Any, asyncio).WindowsSelectorEventLoopPolicy())
    asyncio.run(produce())
