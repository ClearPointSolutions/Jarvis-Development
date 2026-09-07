"""Explicit local-only owner bootstrap command."""

from __future__ import annotations

import argparse
import asyncio
import getpass
from pathlib import Path
from typing import Any, cast

from sqlalchemy import select, text, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from uuid6 import uuid7

from jarvis_api.auth.audit import AuthAuditWriter
from jarvis_api.auth.crypto import PasswordManager, normalize_username
from jarvis_api.auth.repository import AuthRepository
from jarvis_api.config import Settings
from jarvis_contracts.enums import EventSeverity
from jarvis_contracts.event_registry import OwnerBootstrappedData
from jarvis_contracts.ids import UserId
from jarvis_persistence.database import (
    create_async_database_engine,
    create_async_session_factory,
)
from jarvis_persistence.models import ProjectModel, UserModel
from jarvis_persistence.testing import Clock, SystemClock


class BootstrapAlreadyCompletedError(RuntimeError):
    """The one enabled owner already exists."""


async def bootstrap_owner(
    factory: async_sessionmaker[AsyncSession],
    *,
    username: str,
    password: str,
    instance_id: str = "local-bootstrap",
    clock: Clock | None = None,
    password_manager: PasswordManager | None = None,
) -> tuple[UserId, int]:
    normalized = normalize_username(username)
    passwords = password_manager or PasswordManager()
    password_hash = await asyncio.to_thread(passwords.hash, password)
    now = (clock or SystemClock()).now()
    repository = AuthRepository()
    audit = AuthAuditWriter(instance_id=instance_id)
    owner_id = uuid7()
    migrated_count = 0

    async with factory.begin() as session:
        await repository.lock_event_counter(session)
        # A transaction-scoped lock closes the no-row race before the unique enabled-owner index.
        await session.execute(text("SELECT pg_advisory_xact_lock(1245790711)"))
        existing = await session.scalar(
            select(UserModel).where(UserModel.enabled).with_for_update()
        )
        if existing is not None:
            raise BootstrapAlreadyCompletedError("owner bootstrap has already completed")
        session.add(
            UserModel(
                id=owner_id,
                username=normalized,
                password_hash=password_hash,
                role="owner",
                enabled=True,
                created_at=now,
                updated_at=now,
            )
        )
        await session.flush()
        migration_owner = await session.scalar(
            select(UserModel).where(
                UserModel.username == "migration-unassigned", UserModel.enabled.is_(False)
            )
        )
        if migration_owner is not None:
            result = cast(
                CursorResult[Any],
                await session.execute(
                    update(ProjectModel)
                    .where(ProjectModel.owner_user_id == migration_owner.id)
                    .values(owner_user_id=owner_id)
                ),
            )
            migrated_count = int(result.rowcount or 0)
        await audit.append(
            session,
            event_type="auth.owner_bootstrapped",
            payload=OwnerBootstrappedData(
                user_id=UserId(owner_id), migrated_project_count=migrated_count
            ),
            occurred_at=now,
            correlation_id=str(owner_id),
            severity=EventSeverity.SUCCESS,
            source_kind="local_cli",
            source_name="owner-bootstrap",
        )
    return UserId(owner_id), migrated_count


def _read_password(path: Path | None) -> str:
    if path is not None:
        if path.is_symlink():
            raise ValueError("password file must not be a symbolic link")
        value = path.read_text(encoding="utf-8").rstrip("\r\n")
        if len(value) > 1_024:
            raise ValueError("password file exceeds the maximum length")
        return value
    first = getpass.getpass("Owner password: ")
    second = getpass.getpass("Confirm owner password: ")
    if first != second:
        raise ValueError("password confirmation did not match")
    return first


async def _run(args: argparse.Namespace) -> int:
    settings = Settings()
    engine = create_async_database_engine(settings.database_url)
    try:
        owner_id, migrated_count = await bootstrap_owner(
            create_async_session_factory(engine),
            username=str(args.username),
            password=_read_password(args.password_file),
            instance_id=settings.api_instance_id,
        )
    finally:
        await engine.dispose()
    print(f"Owner bootstrap complete: user_id={owner_id}; claimed_projects={migrated_count}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Create the one Jarvis V1 owner locally")
    parser.add_argument("--username", required=True)
    parser.add_argument("--password-file", type=Path)
    args = parser.parse_args()
    try:
        return asyncio.run(_run(args))
    except (BootstrapAlreadyCompletedError, OSError, ValueError) as error:
        parser.exit(2, f"Owner bootstrap refused: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
