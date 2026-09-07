from __future__ import annotations

from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import pytest
from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from jarvis_api.events.artifacts import EventArtifactSink
from jarvis_api.events.normalizer import (
    ArtifactExtractionRequiredError,
    EventCategoryMismatchError,
    EventIntent,
    EventNormalizer,
    UnknownEventTypeError,
)
from jarvis_api.events.redaction import RecursiveRedactor
from jarvis_api.events.sse import (
    EventStream,
    EventWakeupSource,
    SseConnectionLimiter,
    SseConnectionLimitError,
    WakeupSubscription,
    encode_event_frame,
    parse_sse_data,
    resolve_event_cursor,
)
from jarvis_contracts.api import EventPage
from jarvis_contracts.enums import (
    EventCategory,
    EventMode,
    EventSeverity,
    EventVisibility,
)
from jarvis_contracts.event_registry import EVENT_REGISTRY
from jarvis_contracts.events import (
    ArtifactReference,
    EventScope,
    EventSource,
    NormalizedEvent,
)
from jarvis_contracts.ids import ArtifactId, EventId, RunId, SessionId, UserId, new_id
from jarvis_persistence.repositories import (
    EventCursorExpiredError,
    EventRepository,
    RunSequenceGapError,
    UnsupportedEventSchemaError,
)

NOW = datetime(2026, 9, 7, 18, 0, tzinfo=UTC)


def intent(event_type: str = "run.started", **overrides: object) -> EventIntent:
    definition = EVENT_REGISTRY[event_type]
    values: dict[str, object] = {
        "occurred_at": NOW,
        "category": definition.category,
        "type": event_type,
        "severity": EventSeverity.INFO,
        "mode": EventMode.DEMO,
        "visibility": EventVisibility.OWNER,
        "source": EventSource(kind="orchestrator", name="unit-test"),
        "correlation_id": "m2b-unit-test",
        "data": {},
    }
    values.update(overrides)
    return EventIntent.model_validate(values)


def normalized(position: int) -> NormalizedEvent:
    return NormalizedEvent(
        event_id=new_id(EventId),
        global_position=position,
        occurred_at=NOW,
        recorded_at=NOW,
        category=EventCategory.SYSTEM,
        type="system.health_changed",
        severity=EventSeverity.INFO,
        message="System health changed",
        mode=EventMode.DEMO,
        visibility=EventVisibility.OWNER,
        source=EventSource(kind="api", name="unit-test"),
        correlation_id="stream-unit-test",
        data={"healthy": True},
    )


class RecordingArtifactSink(EventArtifactSink):
    def __init__(self) -> None:
        self.contents: list[bytes] = []

    async def put(
        self,
        session: AsyncSession,
        *,
        content: bytes,
        scope: EventScope,
        relation: str,
        media_type: str,
    ) -> ArtifactReference:
        del session, scope, media_type
        self.contents.append(content)
        return ArtifactReference(artifact_id=new_id(ArtifactId), relation=relation)


@pytest.mark.parametrize("event_type", sorted(EVENT_REGISTRY))
async def test_every_registered_event_normalizes_with_a_human_summary(event_type: str) -> None:
    data: dict[str, JsonValue] = {}
    if event_type == "auth.login_succeeded":
        data = {
            "user_id": str(new_id(UserId)),
            "session_id": str(new_id(SessionId)),
            "client_network": "loopback",
        }
    elif event_type == "auth.login_failed":
        data = {
            "subject_fingerprint": "a" * 16,
            "outcome": "invalid_credentials",
            "rate_limited": False,
            "retry_after_seconds": 0,
        }
    elif event_type == "auth.logout":
        data = {
            "user_id": str(new_id(UserId)),
            "session_id": str(new_id(SessionId)),
        }
    elif event_type == "auth.session_revoked":
        data = {
            "user_id": str(new_id(UserId)),
            "session_id": str(new_id(SessionId)),
            "reason": "logout",
        }
    elif event_type == "auth.owner_bootstrapped":
        data = {"user_id": str(new_id(UserId)), "migrated_project_count": 0}

    normalizer = EventNormalizer(
        redactor=RecursiveRedactor(),
        artifact_sink=None,
        inline_bytes=1_024,
        max_bytes=65_536,
    )
    prepared = await normalizer.prepare(cast(AsyncSession, object()), intent(event_type, data=data))

    assert prepared.event.type == event_type
    assert prepared.event.category == EVENT_REGISTRY[event_type].category
    assert prepared.event.message


async def test_normalizer_rejects_unknown_types_and_category_mismatches() -> None:
    normalizer = EventNormalizer(
        redactor=RecursiveRedactor(),
        artifact_sink=None,
        inline_bytes=1_024,
        max_bytes=65_536,
    )
    with pytest.raises(UnknownEventTypeError):
        await normalizer.prepare(
            cast(AsyncSession, object()),
            EventIntent(
                occurred_at=NOW,
                type="future.safe_event",
                severity=EventSeverity.INFO,
                mode=EventMode.DEMO,
                visibility=EventVisibility.OWNER,
                source=EventSource(kind="api", name="test"),
                correlation_id="unknown",
                data={},
            ),
        )
    with pytest.raises(EventCategoryMismatchError):
        await normalizer.prepare(
            cast(AsyncSession, object()),
            intent(category=EventCategory.AUTH),
        )


async def test_recursive_redaction_precedes_artifact_extraction() -> None:
    secret = "synthetic-super-secret-value"
    sink = RecordingArtifactSink()
    normalizer = EventNormalizer(
        redactor=RecursiveRedactor((secret,)),
        artifact_sink=sink,
        inline_bytes=1_024,
        max_bytes=65_536,
    )
    private_key = "-----" + "BEGIN PRIVATE KEY-----\nsynthetic\n-----" + "END PRIVATE KEY-----"
    prepared = await normalizer.prepare(
        cast(AsyncSession, object()),
        intent(
            data={
                "authorization": f"Bearer {secret}",
                "nested": {
                    "scratchpad": "must not persist",
                    "output": f"{secret} {private_key} " + ("x" * 2_000),
                    "url": f"https://owner:{secret}@example.invalid/repository",
                },
            }
        ),
    )

    assert prepared.extracted
    assert prepared.redaction_rule_counts
    assert len(sink.contents) == 1
    persisted = sink.contents[0].decode()
    assert secret not in persisted
    assert "must not persist" not in persisted
    assert "PRIVATE KEY" not in persisted
    assert "[REDACTED:" in persisted
    assert prepared.event.data["content_extracted"] is True
    assert prepared.event.artifact_refs[0].relation == "data"


async def test_oversized_content_requires_an_artifact_sink() -> None:
    normalizer = EventNormalizer(
        redactor=RecursiveRedactor(),
        artifact_sink=None,
        inline_bytes=1_024,
        max_bytes=65_536,
    )
    with pytest.raises(ArtifactExtractionRequiredError):
        await normalizer.prepare(cast(AsyncSession, object()), intent(data={"output": "x" * 2_000}))


class FakeSessionContext:
    async def __aenter__(self) -> AsyncSession:
        return cast(AsyncSession, object())

    async def __aexit__(self, *args: object) -> None:
        del args


class FakeSessionFactory:
    def __call__(self) -> FakeSessionContext:
        return FakeSessionContext()


class LostNotificationSubscription:
    def __init__(self, on_first_wait: Callable[[], None]) -> None:
        self._callback = on_first_wait
        self.waits = 0

    async def wait(self, timeout: float) -> bool:
        del timeout
        self.waits += 1
        if self.waits == 1:
            self._callback()
        return False


class FakeWakeupContext:
    def __init__(self, subscription: WakeupSubscription) -> None:
        self._subscription = subscription

    async def __aenter__(self) -> WakeupSubscription:
        return self._subscription

    async def __aexit__(self, *args: object) -> None:
        del args


class FakeWakeups(EventWakeupSource):
    def __init__(self, subscription: WakeupSubscription) -> None:
        self._subscription = subscription

    def subscribe(self) -> AbstractAsyncContextManager[WakeupSubscription]:
        return FakeWakeupContext(self._subscription)


class FakeEventRepository(EventRepository):
    def __init__(self) -> None:
        super().__init__()
        self.items: list[NormalizedEvent] = []
        self.error: Exception | None = None

    async def page(
        self,
        session: AsyncSession,
        *,
        run_id: UUID,
        after: int,
        limit: int,
    ) -> EventPage:
        del session, run_id, limit
        if self.error is not None:
            raise self.error
        visible = tuple(item for item in self.items if item.global_position > after)
        return EventPage(
            items=visible,
            after=after,
            high_watermark=max((item.global_position for item in self.items), default=0),
        )


async def test_stream_requeries_after_a_lost_notification() -> None:
    repository = FakeEventRepository()
    event = normalized(7)
    subscription = LostNotificationSubscription(lambda: repository.items.append(event))
    stream = EventStream(
        session_factory=cast(async_sessionmaker[AsyncSession], FakeSessionFactory()),
        repository=repository,
        wakeups=FakeWakeups(subscription),
        page_size=20,
        poll_seconds=0.01,
        keepalive_seconds=30,
    )
    frames = stream.iter_frames(run_id=new_id(RunId), after=0)
    frame = await anext(frames)
    await cast(AsyncGenerator[str, None], frames).aclose()

    assert frame.startswith("id: 7\nevent: jarvis.event\n")
    assert parse_sse_data(frame)["global_position"] == 7
    assert subscription.waits == 1


async def test_stream_emits_keepalive_and_explicit_schema_reset() -> None:
    repository = FakeEventRepository()
    clock_values = iter((0.0, 2.0))
    stream = EventStream(
        session_factory=cast(async_sessionmaker[AsyncSession], FakeSessionFactory()),
        repository=repository,
        wakeups=FakeWakeups(LostNotificationSubscription(lambda: None)),
        page_size=20,
        poll_seconds=0.01,
        keepalive_seconds=1,
        monotonic=lambda: next(clock_values),
    )
    frames = stream.iter_frames(run_id=new_id(RunId), after=0)
    assert await anext(frames) == ": keepalive\n\n"
    await cast(AsyncGenerator[str, None], frames).aclose()

    repository.error = UnsupportedEventSchemaError(global_position=11, schema_version="2.0")
    reset_stream = EventStream(
        session_factory=cast(async_sessionmaker[AsyncSession], FakeSessionFactory()),
        repository=repository,
        wakeups=FakeWakeups(LostNotificationSubscription(lambda: None)),
        page_size=20,
        poll_seconds=0.01,
        keepalive_seconds=1,
    )
    reset = await anext(reset_stream.iter_frames(run_id=new_id(RunId), after=0))
    assert "event: stream.reset" in reset
    assert parse_sse_data(reset)["reason"] == "unsupported_schema"


@pytest.mark.parametrize(
    ("error", "reason"),
    (
        (
            EventCursorExpiredError(requested=1, earliest=5, latest=9),
            "cursor_expired",
        ),
        (
            RunSequenceGapError(expected=2, actual=3, global_position=9),
            "run_sequence_gap",
        ),
    ),
)
async def test_stream_emits_explicit_cursor_and_sequence_resets(
    error: Exception, reason: str
) -> None:
    repository = FakeEventRepository()
    repository.error = error
    stream = EventStream(
        session_factory=cast(async_sessionmaker[AsyncSession], FakeSessionFactory()),
        repository=repository,
        wakeups=FakeWakeups(LostNotificationSubscription(lambda: None)),
        page_size=20,
        poll_seconds=0.01,
        keepalive_seconds=1,
    )
    reset = await anext(stream.iter_frames(run_id=new_id(RunId), after=1))
    assert parse_sse_data(reset)["reason"] == reason


async def test_sse_frames_cursor_precedence_and_connection_limit() -> None:
    event = normalized(42)
    frame = encode_event_frame(event)
    assert frame.count("\ndata: ") == 1
    assert resolve_event_cursor(after=2, last_event_id="41") == 41
    assert resolve_event_cursor(after=2, last_event_id=None) == 2
    with pytest.raises(ValueError):
        resolve_event_cursor(after=2, last_event_id="4x")

    limiter = SseConnectionLimiter(1)
    async with limiter.acquire("owner"):
        with pytest.raises(SseConnectionLimitError):
            async with limiter.acquire("owner"):
                pass
    async with limiter.acquire("owner"):
        pass
