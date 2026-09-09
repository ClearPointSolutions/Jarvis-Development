"""Readiness pins the schema this code requires; drift must fail here, not live.

The API reports 503 `migration_required` until the database's Alembic revision
matches `EXPECTED_SCHEMA_REVISION`. Adding a migration without moving that pin
makes a correctly migrated deployment report itself permanently unready, so the
pin is checked against the actual head rather than trusted.
"""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from jarvis_api.auth.routes import EXPECTED_SCHEMA_REVISION

ROOT = Path(__file__).resolve().parents[2]


def alembic_head() -> str:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "api" / "migrations"))
    heads = ScriptDirectory.from_config(config).get_heads()
    assert len(heads) == 1, f"expected a single migration head, found {heads}"
    return heads[0]


def test_readiness_pin_matches_the_single_migration_head() -> None:
    assert alembic_head() == EXPECTED_SCHEMA_REVISION
