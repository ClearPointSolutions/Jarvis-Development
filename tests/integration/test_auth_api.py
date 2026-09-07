from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from uuid6 import uuid7

from jarvis_api.auth.authorization import ObjectAuthorizer
from jarvis_api.auth.bootstrap import BootstrapAlreadyCompletedError, bootstrap_owner
from jarvis_api.auth.crypto import PasswordManager, sha256_text
from jarvis_api.config import Settings
from jarvis_api.errors import ApiProblemError
from jarvis_api.main import create_app
from jarvis_contracts.ids import UserId
from jarvis_persistence.models import (
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
TEST_CREDENTIAL = "correct-horse-battery-fixture"
SERVER_KEY = b"test-only-csrf-and-fingerprint-key"


@dataclass
class AuthEnvironment:
    client: httpx.AsyncClient
    clock: FrozenClock
    user_id: UUID
    username: str
    settings: Settings


@pytest_asyncio.fixture
async def auth_environment(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AuthEnvironment]:
    passwords = PasswordManager()
    async with session_factory.begin() as session:
        await session.execute(delete(LoginRateLimitModel))
        await session.execute(delete(SessionModel))
        owner = await session.scalar(select(UserModel).where(UserModel.enabled))
        if owner is None:
            owner = UserModel(
                id=uuid7(),
                username=f"test-owner-{uuid7().hex[:8]}",
                password_hash=passwords.hash(TEST_CREDENTIAL),
                role="owner",
                enabled=True,
            )
            session.add(owner)
            await session.flush()
        else:
            owner.password_hash = passwords.hash(TEST_CREDENTIAL)
            owner.enabled = True

    clock = FrozenClock(NOW)
    settings = Settings(
        _env_file=None,
        env="test",
        public_origin=ORIGIN,
        cookie_secure=True,
        session_idle_seconds=60,
        session_absolute_seconds=300,
        session_touch_interval_seconds=1,
        login_account_limit=2,
        login_network_limit=50,
        login_base_delay_seconds=1,
        login_max_delay_seconds=8,
    )
    app = create_app(
        settings=settings,
        session_factory=session_factory,
        clock=clock,
        server_key=SERVER_KEY,
    )
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=ORIGIN,
        headers={"Origin": ORIGIN},
    )
    try:
        yield AuthEnvironment(client, clock, owner.id, owner.username, settings)
    finally:
        await client.aclose()


async def _login(environment: AuthEnvironment, credential: str = TEST_CREDENTIAL) -> httpx.Response:
    return await environment.client.post(
        "/api/v1/auth/login",
        json={"username": environment.username, "password": credential},
    )


async def test_auth_001_login_logout_hash_only_session_and_audit(
    auth_environment: AuthEnvironment,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    client = auth_environment.client
    assert (await client.get("/api/v1/session")).status_code == 401

    login = await _login(auth_environment)
    assert login.status_code == 200
    cookie_header = login.headers["set-cookie"].lower()
    assert "httponly" in cookie_header
    assert "secure" in cookie_header
    assert "samesite=strict" in cookie_header
    assert "path=/api/v1" in cookie_header
    raw_token = client.cookies.get(auth_environment.settings.session_cookie_name)
    assert raw_token is not None
    csrf = login.json()["csrf_token"]

    rotated = await _login(auth_environment)
    assert rotated.status_code == 200
    rotated_token = client.cookies.get(auth_environment.settings.session_cookie_name)
    assert rotated_token is not None and rotated_token != raw_token
    csrf = rotated.json()["csrf_token"]

    async with session_factory() as session:
        stored = await session.scalar(
            select(SessionModel).where(SessionModel.token_hash == sha256_text(raw_token))
        )
        assert stored is not None
        assert stored.token_hash != raw_token
        assert stored.csrf_secret_hash != csrf
        event_types = list(
            await session.scalars(
                select(EventModel.type).where(
                    EventModel.type.in_(["auth.login_succeeded", "auth.logout"])
                )
            )
        )
    assert "auth.login_succeeded" in event_types

    assert (await client.get("/api/v1/session")).status_code == 200
    logout = await client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf}, json={})
    assert logout.status_code == 200
    assert logout.json() == {"revoked": True}
    assert (
        await client.get(
            "/api/v1/session",
            headers={"Cookie": f"{auth_environment.settings.session_cookie_name}={raw_token}"},
        )
    ).status_code == 401


async def test_auth_002_rate_limit_is_durable_generic_and_recovers(
    auth_environment: AuthEnvironment,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    client = auth_environment.client
    username = auth_environment.username
    first = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": "invalid-fixture"}
    )
    second = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": "invalid-fixture"}
    )
    blocked = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": TEST_CREDENTIAL}
    )
    assert first.status_code == 401
    assert second.status_code == 429
    assert blocked.status_code == 429
    assert second.json()["error"]["message"] == blocked.json()["error"]["message"]
    assert int(blocked.headers["retry-after"]) >= 1

    async with session_factory() as session:
        failures = list(
            await session.scalars(select(EventModel).where(EventModel.type == "auth.login_failed"))
        )
        serialized = " ".join(str(row.data_json) for row in failures)
    assert TEST_CREDENTIAL not in serialized
    assert username not in serialized

    auth_environment.clock.advance(timedelta(seconds=2))
    recovered = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": TEST_CREDENTIAL}
    )
    assert recovered.status_code == 200

    async with session_factory.begin() as session:
        await session.execute(delete(LoginRateLimitModel))
        await session.execute(delete(SessionModel))
    network_settings = auth_environment.settings.model_copy(
        update={"login_account_limit": 50, "login_network_limit": 2}
    )
    network_app = create_app(
        settings=network_settings,
        session_factory=session_factory,
        clock=auth_environment.clock,
        server_key=SERVER_KEY,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=network_app),
        base_url=ORIGIN,
        headers={"Origin": ORIGIN},
    ) as network_client:
        network_first = await network_client.post(
            "/api/v1/auth/login",
            json={"username": f"missing-{uuid7().hex[:8]}", "password": "invalid-fixture"},
        )
        network_second = await network_client.post(
            "/api/v1/auth/login",
            json={"username": f"missing-{uuid7().hex[:8]}", "password": "invalid-fixture"},
        )
    assert network_first.status_code == 401
    assert network_second.status_code == 429


async def test_auth_003_origin_json_and_csrf_are_all_required(
    auth_environment: AuthEnvironment,
) -> None:
    client = auth_environment.client
    username = auth_environment.username
    no_origin = await client.post(
        "/api/v1/auth/login",
        headers={"Origin": ""},
        json={"username": username, "password": TEST_CREDENTIAL},
    )
    assert no_origin.status_code == 403

    login = await _login(auth_environment)
    csrf = login.json()["csrf_token"]
    assert (
        await client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": "wrong"}, json={})
    ).status_code == 403
    assert (
        await client.post(
            "/api/v1/auth/logout",
            headers={"Origin": "https://different.test", "X-CSRF-Token": csrf},
            json={},
        )
    ).status_code == 403
    assert (
        await client.post(
            "/api/v1/auth/logout",
            headers={"X-CSRF-Token": csrf, "Content-Type": "text/plain"},
            content="{}",
        )
    ).status_code == 415
    assert (
        await client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf}, json={})
    ).status_code == 200


async def test_auth_004_owner_scoping_hides_unowned_and_missing_resources(
    auth_environment: AuthEnvironment,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    seeded = await seed_run(session_factory)
    authorizer = ObjectAuthorizer(session_factory)

    with pytest.raises(ApiProblemError) as unowned:
        await authorizer.require_project(
            user_id=UserId(auth_environment.user_id), project_id=seeded.project_id
        )
    with pytest.raises(ApiProblemError) as missing:
        await authorizer.require_project(
            user_id=UserId(auth_environment.user_id), project_id=uuid7()
        )
    with pytest.raises(ApiProblemError) as unowned_run:
        await authorizer.require_run(user_id=UserId(auth_environment.user_id), run_id=seeded.run_id)

    assert (unowned.value.status_code, unowned.value.code) == (404, "resource.not_found")
    assert (missing.value.status_code, missing.value.code) == (404, "resource.not_found")
    assert (unowned_run.value.status_code, unowned_run.value.code) == (
        404,
        "resource.not_found",
    )
    async with session_factory.begin() as session:
        owned = ProjectModel(
            id=uuid7(),
            owner_user_id=auth_environment.user_id,
            slug=f"owned-{uuid7().hex[:8]}",
            name="Owned fixture",
            status="active",
        )
        session.add(owned)
    assert (
        await authorizer.require_project(
            user_id=UserId(auth_environment.user_id), project_id=owned.id
        )
    ).id == owned.id


async def test_auth_005_expiry_revocation_and_api_restart(
    auth_environment: AuthEnvironment,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    client = auth_environment.client
    assert (await _login(auth_environment)).status_code == 200
    raw_token = client.cookies.get(auth_environment.settings.session_cookie_name)
    assert raw_token is not None

    replacement_app = create_app(
        settings=auth_environment.settings,
        session_factory=session_factory,
        clock=auth_environment.clock,
        server_key=SERVER_KEY,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=replacement_app),
        base_url=ORIGIN,
        headers={"Cookie": f"jarvis_session={raw_token}"},
    ) as replacement:
        assert (await replacement.get("/api/v1/session")).status_code == 200

    auth_environment.clock.advance(timedelta(seconds=61))
    expired = await client.get("/api/v1/session")
    assert expired.status_code == 401
    async with session_factory() as session:
        expired_row = await session.scalar(
            select(SessionModel).where(SessionModel.token_hash == sha256_text(raw_token))
        )
        assert expired_row is not None
        assert expired_row.revoked_at is not None
        assert expired_row.revoke_reason == "idle_expired"

    second = await _login(auth_environment)
    assert second.status_code == 200
    second_token = client.cookies.get(auth_environment.settings.session_cookie_name)
    assert second_token is not None
    async with session_factory.begin() as session:
        await session.execute(
            update(SessionModel)
            .where(SessionModel.token_hash == sha256_text(second_token))
            .values(revoked_at=auth_environment.clock.now(), revoke_reason="operator_revoked")
        )
    assert (await client.get("/api/v1/session")).status_code == 401

    third = await _login(auth_environment)
    assert third.status_code == 200
    third_token = client.cookies.get(auth_environment.settings.session_cookie_name)
    assert third_token is not None
    for _ in range(5):
        auth_environment.clock.advance(timedelta(seconds=59))
        assert (await client.get("/api/v1/session")).status_code == 200
    auth_environment.clock.advance(timedelta(seconds=6))
    assert (await client.get("/api/v1/session")).status_code == 401
    async with session_factory() as session:
        absolute_row = await session.scalar(
            select(SessionModel).where(SessionModel.token_hash == sha256_text(third_token))
        )
        assert absolute_row is not None
        assert absolute_row.revoke_reason == "absolute_expired"


async def test_readiness_is_authenticated_and_bootstrap_is_one_time(
    auth_environment: AuthEnvironment,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    client = auth_environment.client
    assert (await client.get("/api/v1/system/readiness")).status_code == 401
    assert (await _login(auth_environment)).status_code == 200
    readiness = await client.get("/api/v1/system/readiness")
    assert readiness.status_code == 200
    assert readiness.json() == {"status": "ready", "database": "ready"}

    async with session_factory.begin() as session:
        await session.execute(update(UserModel).where(UserModel.enabled).values(enabled=False))
        migration_owner = await session.scalar(
            select(UserModel).where(UserModel.username == "migration-unassigned")
        )
        assert migration_owner is not None
        claimed_project = ProjectModel(
            id=uuid7(),
            owner_user_id=migration_owner.id,
            slug=f"bootstrap-project-{uuid7().hex[:8]}",
            name="Bootstrap fixture",
            status="active",
        )
        session.add(claimed_project)

    bootstrap_name = f"bootstrap-{uuid7().hex[:12]}"
    owner_id, claimed = await bootstrap_owner(
        session_factory,
        username=bootstrap_name,
        password=TEST_CREDENTIAL,
        clock=auth_environment.clock,
    )
    assert claimed >= 1
    async with session_factory() as session:
        project_owner = await session.scalar(
            select(ProjectModel.owner_user_id).where(ProjectModel.id == claimed_project.id)
        )
        owner = await session.get(UserModel, UUID(str(owner_id)))
        assert project_owner == owner_id
        assert owner is not None and owner.password_hash != TEST_CREDENTIAL
    with pytest.raises(BootstrapAlreadyCompletedError):
        await bootstrap_owner(
            session_factory,
            username=f"other-{uuid7().hex[:12]}",
            password=TEST_CREDENTIAL,
            clock=auth_environment.clock,
        )
