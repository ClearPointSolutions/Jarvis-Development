"""LangGraph PostgreSQL checkpointer bootstrap in its dedicated schema."""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import quote, urlencode

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection
from psycopg.rows import dict_row
from sqlalchemy.engine import make_url

from jarvis_persistence.models import LANGGRAPH_SCHEMA


def psycopg_connection_string(database_url: str) -> str:
    """Remove SQLAlchemy's driver suffix without exposing or changing credentials."""

    url = make_url(database_url).set(drivername="postgresql")
    # SQLAlchemy uses form-style '+' for query spaces; libpq URI parsing requires
    # percent encoding. Preserve literal '+' credentials and repeated query values.
    base = url.set(query={}).render_as_string(hide_password=False)
    query = urlencode(url.query, doseq=True, quote_via=quote)
    return f"{base}?{query}" if query else base


@asynccontextmanager
async def postgres_saver(
    database_url: str, *, setup: bool = False
) -> AsyncIterator[AsyncPostgresSaver]:
    """Open a checkpointer whose unqualified tables resolve to `langgraph`."""

    connection = await AsyncConnection.connect(
        psycopg_connection_string(database_url),
        autocommit=True,
        prepare_threshold=0,
        row_factory=dict_row,
    )
    try:
        await connection.execute(f"SET search_path TO {LANGGRAPH_SCHEMA}, public")
        saver = AsyncPostgresSaver(connection)
        if setup:
            await saver.setup()
            await connection.execute(
                "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA langgraph "
                "TO jarvis_v1_orchestrator"
            )
        yield saver
    finally:
        await connection.close()


async def bootstrap() -> None:
    """Explicit migration/bootstrap step; ordinary executors never perform DDL."""
    async with postgres_saver(os.environ["DATABASE_URL"], setup=True):
        pass
    print("LangGraph checkpoint schema ready")


if __name__ == "__main__":
    if sys.platform == "win32":
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            runner.run(bootstrap())
    else:
        asyncio.run(bootstrap())
