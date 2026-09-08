"""Actual M2 app boundary exercised with PostgreSQL's least-privilege API role."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from uuid6 import uuid7

from jarvis_api.auth.crypto import PasswordManager, sha256_text
from jarvis_api.config import Settings
from jarvis_api.main import create_app
from jarvis_persistence.models import (
    EventGlobalCounterModel,
    EventModel,
    LoginRateLimitModel,
    ProjectModel,
    SessionModel,
    UserModel,
)
from jarvis_persistence.testing import FrozenClock
from tests.integration.support import NOW, seed_run

pytestmark = pytest.mark.integration
ORIGIN = "https://jarvis.test"
CREDENTIAL = "integrated-owner-test-credential"
KEY = b"integrated-api-fixture-secret-key"


@dataclass
class IntegratedApi:
    client: httpx.AsyncClient
    factory: async_sessionmaker[AsyncSession]
    settings: Settings
    clock: FrozenClock
    owner_id: UUID
    username: str


@pytest_asyncio.fixture
async def integrated_api(
    session_factory: async_sessionmaker[AsyncSession], database_url: str, tmp_path: Path
) -> AsyncIterator[IntegratedApi]:
    async with session_factory.begin() as session:
        await session.execute(delete(LoginRateLimitModel))
        await session.execute(delete(SessionModel))
        owner = await session.scalar(select(UserModel).where(UserModel.enabled))
        if owner is None:
            owner = UserModel(
                id=uuid7(),
                username=f"integrated-{uuid7().hex[-12:]}",
                role="owner",
                enabled=True,
                password_hash=PasswordManager().hash(CREDENTIAL),
            )
            session.add(owner)
        else:
            owner.password_hash = PasswordManager().hash(CREDENTIAL)
        await session.flush()
    engine = create_async_engine(database_url, connect_args={"options": "-c role=jarvis_v1_api"})
    factory = async_sessionmaker(engine, expire_on_commit=False)
    settings = Settings(
        _env_file=None,
        env="test",
        public_origin=ORIGIN,
        cookie_secure=True,
        database_url=database_url,
        artifact_root=tmp_path,
        api_instance_id="password=synthetic-audit-source-canary",
        session_idle_seconds=60,
        session_touch_interval_seconds=1,
    )
    clock = FrozenClock(NOW)
    app = create_app(settings=settings, session_factory=factory, clock=clock, server_key=KEY)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
        ) as client:
            yield IntegratedApi(client, factory, settings, clock, owner.id, owner.username)
    finally:
        await engine.dispose()


async def login(api: IntegratedApi) -> httpx.Response:
    response = await api.client.post(
        "/api/v1/auth/login", json={"username": api.username, "password": CREDENTIAL}
    )
    assert response.status_code == 200
    return response


async def test_actual_api_role_readiness_redacted_audit_and_rotated_logout_restart(
    integrated_api: IntegratedApi, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    api = integrated_api
    async with api.factory() as session:
        assert await session.scalar(text("SELECT current_user")) == "jarvis_v1_api"
        assert (
            await session.scalar(text("SELECT version_num FROM public.alembic_version")) == "0007"
        )
    assert (await api.client.get("/api/v1/system/readiness")).status_code == 401
    first = await login(api)
    first_token = api.client.cookies.get("jarvis_session")
    assert first_token
    second = await login(api)
    current_token = api.client.cookies.get("jarvis_session")
    assert current_token and current_token != first_token
    assert (await api.client.get("/api/v1/system/readiness")).json() == {
        "status": "ready",
        "database": "ready",
    }
    async with session_factory() as session:
        old = await session.scalar(
            select(SessionModel).where(SessionModel.token_hash == sha256_text(first_token))
        )
        current = await session.scalar(
            select(SessionModel).where(SessionModel.token_hash == sha256_text(current_token))
        )
        assert old and current
        assert old.revoke_reason == "rotated_on_login" and old.revoked_at is not None
        assert old.csrf_secret_hash == sha256_text(first.json()["csrf_token"])
        assert current.csrf_secret_hash == sha256_text(second.json()["csrf_token"])
        audits = list(
            await session.scalars(
                select(EventModel).where(
                    EventModel.correlation_id == second.headers["x-request-id"]
                )
            )
        )
        assert {row.type for row in audits} == {"auth.session_revoked", "auth.login_succeeded"}
        assert all(row.source_instance_id == "password=[REDACTED:credential]" for row in audits)
        serialized = str([(row.data_json, row.source_instance_id) for row in audits])
        assert "synthetic-audit-source-canary" not in serialized
        assert CREDENTIAL not in serialized and current_token not in serialized
    logout = await api.client.post(
        "/api/v1/auth/logout", json={}, headers={"X-CSRF-Token": second.json()["csrf_token"]}
    )
    assert logout.status_code == 200 and logout.json()["revoked"]
    replacement = create_app(
        settings=api.settings, session_factory=api.factory, clock=api.clock, server_key=KEY
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=replacement),
        base_url=ORIGIN,
        headers={"Cookie": f"jarvis_session={current_token}"},
    ) as client:
        assert (await client.get("/api/v1/session")).status_code == 401
        assert (await client.get("/api/v1/system/readiness")).status_code == 401
    async with session_factory() as session:
        current = await session.scalar(
            select(SessionModel).where(SessionModel.token_hash == sha256_text(current_token))
        )
        assert (
            current and current.revoked_at is not None and current.revoke_reason == "owner_logout"
        )


async def test_actual_event_routes_hide_ownership_and_preserve_schema_reset_errors(
    integrated_api: IntegratedApi, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    api = integrated_api
    await login(api)
    unowned = await seed_run(session_factory)
    missing = await api.client.get(f"/api/v1/runs/{uuid7()}/events")
    denied = await api.client.get(f"/api/v1/runs/{unowned.run_id}/events")
    assert missing.status_code == denied.status_code == 404
    assert missing.json()["error"]["code"] == denied.json()["error"]["code"] == "resource.not_found"
    async with session_factory.begin() as session:
        await session.execute(
            update(ProjectModel)
            .where(ProjectModel.id == unowned.project_id)
            .values(owner_user_id=api.owner_id)
        )
        counter = await session.scalar(
            select(EventGlobalCounterModel).where(EventGlobalCounterModel.id == 1).with_for_update()
        )
        assert counter is not None
        counter.last_position += 1
        # Model a retained event from a newer producer by INSERT only. Never disable
        # append-only triggers or UPDATE existing history to inject a version.
        session.add(
            EventModel(
                event_id=uuid7(),
                global_position=counter.last_position,
                run_sequence=1,
                schema_version="2.0",
                occurred_at=NOW,
                category="run",
                type="run.started",
                severity="info",
                message="Future schema event",
                mode="demo",
                visibility="owner",
                run_id=unowned.run_id,
                source_kind="orchestrator",
                source_name="future-fixture",
                correlation_id=str(uuid7()),
                data_json={},
                artifact_refs_json=[],
            )
        )
    response = await api.client.get(f"/api/v1/runs/{unowned.run_id}/events")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "event.unsupported_schema"
    assert response.headers["x-request-id"] == response.json()["error"]["request_id"]
    stream = await api.client.get(f"/api/v1/runs/{unowned.run_id}/events/stream")
    assert stream.status_code == 200
    assert "event: stream.reset" in stream.text and '"reason":"unsupported_schema"' in stream.text


async def test_actual_sse_origin_denial_and_reset_get_never_touch_session_or_audit(
    integrated_api: IntegratedApi, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    api = integrated_api
    await login(api)
    seeded = await seed_run(session_factory)
    async with session_factory.begin() as session:
        await session.execute(
            update(ProjectModel)
            .where(ProjectModel.id == seeded.project_id)
            .values(owner_user_id=api.owner_id)
        )
    api.clock.advance(timedelta(seconds=30))
    async with session_factory() as session:
        event_count = await session.scalar(select(func.count()).select_from(EventModel))
        token = api.client.cookies.get("jarvis_session")
        assert token
        before = await session.scalar(
            select(SessionModel).where(SessionModel.token_hash == sha256_text(token))
        )
        assert before
        timestamps = (before.last_seen_at, before.expires_at, before.revoked_at)
    for headers in ({"Origin": "https://attacker.test"}, {"Sec-Fetch-Site": "cross-site"}):
        denied = await api.client.get(
            f"/api/v1/runs/{seeded.run_id}/events/stream", headers=headers
        )
        assert denied.status_code == 403
        assert denied.json()["error"]["code"] == "request.origin_rejected"
    # A malformed cursor gives a finite authenticated SSE GET without bypassing
    # either the real auth dependency or Origin guard.
    malformed = await api.client.get(
        f"/api/v1/runs/{seeded.run_id}/events/stream", headers={"Last-Event-ID": "not-a-cursor"}
    )
    assert malformed.status_code == 400
    async with session_factory() as session:
        after = await session.scalar(
            select(SessionModel).where(SessionModel.token_hash == sha256_text(token))
        )
        assert after and (after.last_seen_at, after.expires_at, after.revoked_at) == timestamps
        assert await session.scalar(select(func.count()).select_from(EventModel)) == event_count
