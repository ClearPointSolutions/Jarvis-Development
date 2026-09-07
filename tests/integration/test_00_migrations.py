from __future__ import annotations

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from uuid6 import uuid7

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

    command.upgrade(config, "0001")
    legacy_project_id = uuid7()
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO control.projects (id, slug, name, status) "
                "VALUES (:id, :slug, 'Pre-M2 project', 'active')"
            ),
            {"id": legacy_project_id, "slug": f"pre-m2-{legacy_project_id}"},
        )

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
        migrated_owner = connection.execute(
            text(
                "SELECT users.username, users.enabled "
                "FROM control.projects JOIN control.users "
                "ON users.id = projects.owner_user_id WHERE projects.id = :project_id"
            ),
            {"project_id": legacy_project_id},
        ).one()
        assert tuple(migrated_owner) == ("migration-unassigned", False)
        assert not connection.scalar(
            text("SELECT has_table_privilege('jarvis_v1_orchestrator','control.users','SELECT')")
        )
        assert not connection.scalar(
            text("SELECT has_table_privilege('jarvis_v1_readonly','control.sessions','SELECT')")
        )
        assert connection.scalar(
            text(
                "SELECT has_table_privilege("
                "'jarvis_v1_api','control.sessions','SELECT,INSERT,UPDATE')"
            )
        )
    engine.dispose()
