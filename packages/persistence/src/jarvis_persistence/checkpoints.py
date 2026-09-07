"""LangGraph PostgreSQL checkpointer bootstrap in its dedicated schema."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection
from psycopg.rows import dict_row
from sqlalchemy.engine import make_url

from jarvis_persistence.models import LANGGRAPH_SCHEMA


def psycopg_connection_string(database_url: str) -> str:
    """Remove SQLAlchemy's driver suffix without exposing or changing credentials."""

    url = make_url(database_url).set(drivername="postgresql")
    return url.render_as_string(hide_password=False)


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
        yield saver
    finally:
        await connection.close()
