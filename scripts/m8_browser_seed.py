"""Disposable local M8 acceptance data produced by the real API and runtime."""

from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.engine import make_url
from tests.integration.support import NOW
from tests.integration.test_m2_integrated_api import CREDENTIAL, IntegratedApi
from tests.integration.test_m8_runtime import test_m8_published_runtime_local_git

from jarvis_api.auth.crypto import PasswordManager
from jarvis_api.config import Settings
from jarvis_api.main import create_app
from jarvis_persistence.database import create_async_database_engine, create_async_session_factory
from jarvis_persistence.models import (
    IntegrationHeadModel,
    JobModel,
    ProjectModel,
    RunModel,
    UserModel,
)
from jarvis_persistence.testing import FrozenClock


async def seed_m8(url: str, directory: Path) -> str:
    parsed = make_url(url)
    if parsed.host not in {"127.0.0.1", "localhost", "::1"} or not (
        parsed.database or ""
    ).startswith("jarvis_m2_browser_"):
        raise ValueError("M8 browser seed requires disposable loopback PostgreSQL")
    engine = create_async_database_engine(url)
    sessions = create_async_session_factory(engine)
    api_engine = create_async_database_engine(
        parsed.update_query_dict({"options": "-c role=jarvis_v1_api"}).render_as_string(
            hide_password=False
        )
    )
    api_sessions = create_async_session_factory(api_engine)
    try:
        async with sessions.begin() as session:
            owner = await session.scalar(
                select(UserModel).where(UserModel.username == "browser-owner")
            )
            assert owner is not None
            previous_hash = owner.password_hash
            owner.password_hash = PasswordManager().hash(CREDENTIAL)
        settings = Settings(
            _env_file=None,
            env="test",
            public_origin="https://jarvis.test",
            cookie_secure=True,
            database_url=url,
            artifact_root=directory / "artifacts",
        )
        clock = FrozenClock(NOW)
        app = create_app(
            settings=settings,
            session_factory=api_sessions,
            clock=clock,
            server_key=b"local-m8-browser-fixture-key" * 2,
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="https://jarvis.test",
            headers={"Origin": "https://jarvis.test"},
        ) as client:
            await test_m8_published_runtime_local_git(
                url,
                sessions,
                directory,
                None,
                IntegratedApi(client, api_sessions, settings, clock, owner.id, owner.username),
            )
        async with sessions.begin() as session:
            run = await session.scalar(
                select(RunModel)
                .join(IntegrationHeadModel)
                .join(JobModel)
                .join(ProjectModel)
                .where(ProjectModel.owner_user_id == owner.id)
            )
            browser_owner = await session.scalar(
                select(UserModel).where(UserModel.username == "browser-owner")
            )
            assert run is not None and browser_owner is not None
            project = await session.scalar(
                select(ProjectModel).join(JobModel).where(JobModel.id == run.job_id)
            )
            assert project is not None
            project.owner_user_id = browser_owner.id
            browser_owner.password_hash = previous_hash
            return str(run.id)
    finally:
        await api_engine.dispose()
        await engine.dispose()
