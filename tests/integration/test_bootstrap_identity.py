"""Owner-bootstrap identity regressions (M12A defect 5).

The owner bootstrap must run as an identity that can create the first
``control.users`` row. The least-privilege ``jarvis_v1_api`` login must never
gain that ability, and the bootstrap command must not leak the password.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from uuid6 import uuid7

from jarvis_api.auth.crypto import PasswordManager
from jarvis_persistence.models import UserModel

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]

INSERT_USER = text(
    "INSERT INTO control.users (id, username, password_hash, role, enabled, version) "
    "VALUES (:id, :username, '!probe-disabled', 'owner', false, 0)"
)


@pytest_asyncio.fixture
async def api_role_factory(
    database_url: str,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(database_url, connect_args={"options": "-c role=jarvis_v1_api"})
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


async def test_api_login_cannot_insert_into_control_users(
    api_role_factory: async_sessionmaker[AsyncSession],
) -> None:
    with pytest.raises(ProgrammingError) as excinfo:
        async with api_role_factory.begin() as session:
            assert await session.scalar(text("SELECT current_user")) == "jarvis_v1_api"
            await session.execute(
                INSERT_USER, {"id": uuid7(), "username": f"probe-{uuid7().hex[-12:]}"}
            )
    assert "permission denied" in str(excinfo.value).lower()


async def test_api_and_orchestrator_roles_lack_insert_grant_on_users(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        for role in ("jarvis_v1_api", "jarvis_v1_orchestrator"):
            granted = await session.scalar(
                text("SELECT has_table_privilege(:role, 'control.users', 'INSERT')"),
                {"role": role},
            )
            assert granted is False, f"{role} must not hold INSERT on control.users"


async def test_database_owning_identity_can_create_a_user_row(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # The identity migrations run as (here jarvis_v1_dev, the table owner; in a
    # deployment jarvis_v1_migrator_login) is the one owner-bootstrap uses. Prove
    # it can insert, then roll back so the one-time bootstrap guard is untouched.
    async with session_factory() as session:
        await session.execute(
            INSERT_USER, {"id": uuid7(), "username": f"probe-{uuid7().hex[-12:]}"}
        )
        inserted = await session.scalar(
            text("SELECT count(*) FROM control.users WHERE password_hash = '!probe-disabled'")
        )
        assert inserted == 1
        await session.rollback()


async def test_owner_bootstrap_cli_never_prints_the_password(
    database_url: str,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    async with session_factory.begin() as session:
        if await session.scalar(text("SELECT 1 FROM control.users WHERE enabled LIMIT 1")) is None:
            session.add(
                UserModel(
                    id=uuid7(),
                    username=f"seed-{uuid7().hex[-12:]}",
                    password_hash=PasswordManager().hash("seed-password-not-secret"),
                    role="owner",
                    enabled=True,
                )
            )

    password = f"probe-secret-{uuid7().hex}"
    password_file = tmp_path / "owner_password"
    password_file.write_text(password, encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "jarvis_api.auth.bootstrap",
            "--username",
            f"probe-{uuid7().hex[-12:]}",
            "--password-file",
            str(password_file),
        ],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env={**os.environ, "DATABASE_URL": database_url, "JARVIS_ENV": "development"},
    )

    # A pre-existing owner makes this the "already completed" refusal path; either
    # way the password must not appear in the command's output.
    assert result.returncode == 2, result.stdout + result.stderr
    assert password not in result.stdout
    assert password not in result.stderr
