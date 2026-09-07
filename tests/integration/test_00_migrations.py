from __future__ import annotations

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

pytestmark = pytest.mark.integration


def alembic_config(database_url: str) -> Config:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def test_postgresql_16_migration_round_trip_and_metadata_drift(database_url: str) -> None:
    engine = create_engine(database_url)
    config = alembic_config(database_url)

    command.downgrade(config, "base")
    with engine.connect() as connection:
        schemas = set(inspect(connection).get_schema_names())
        assert "control" not in schemas
        assert "event_store" not in schemas
        assert int(connection.scalar(text("SHOW server_version_num"))) // 10_000 == 16

    command.upgrade(config, "head")
    command.check(config)
    with engine.connect() as connection:
        inspector = inspect(connection)
        schemas = set(inspector.get_schema_names())
        assert {"control", "event_store", "langgraph"}.issubset(schemas)
        assert inspector.get_pk_constraint("events", schema="event_store")[
            "constrained_columns"
        ] == ["global_position"]
        assert (
            connection.scalar(
                text("SELECT last_position FROM event_store.event_global_counter WHERE id = 1")
            )
            == 0
        )
    engine.dispose()
