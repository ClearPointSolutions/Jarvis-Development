from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from jarvis_persistence.database import (
    create_async_database_engine,
    create_async_session_factory,
)


@pytest.fixture(scope="session")
def database_url() -> str:
    value = os.environ.get("TEST_DATABASE_URL")
    if not value:
        pytest.skip("TEST_DATABASE_URL is required for PostgreSQL integration tests")
    host = make_url(value).host
    if host not in {"127.0.0.1", "localhost", "::1"}:
        pytest.fail("M1 integration tests refuse non-loopback PostgreSQL hosts")
    return value


@pytest_asyncio.fixture
async def session_factory(
    database_url: str,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_database_engine(database_url)
    try:
        yield create_async_session_factory(engine)
    finally:
        await engine.dispose()
