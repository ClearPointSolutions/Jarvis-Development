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
from jarvis_contracts.event_registry import (
    OwnerBootstrappedData,
    OwnerPasswordResetData,
    SessionRevokedData,
)
from jarvis_contracts.ids import SessionId, UserId
from jarvis_persistence.database import (
    create_async_database_engine,
    create_async_session_factory,
)
from jarvis_persistence.models import EventModel, ProjectModel, SessionModel, UserModel
from jarvis_persistence.testing import Clock, SystemClock


class BootstrapAlreadyCompletedError(RuntimeError):
    """Owner initialization has already completed, even if the owner is disabled."""


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
        bootstrapped = await session.scalar(
            select(EventModel.event_id).where(EventModel.type == "auth.owner_bootstrapped").limit(1)
        )
        if existing is not None or bootstrapped is not None:
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


async def reset_owner_password(
    factory: async_sessionmaker[AsyncSession],
    *,
    username: str,
    password: str,
    instance_id: str = "local-reset",
    clock: Clock | None = None,
) -> tuple[UserId, int]:
    """Explicit local recovery; change an existing owner, never create a second one."""
    normalized = normalize_username(username)
    password_hash = await asyncio.to_thread(PasswordManager().hash, password)
    now = (clock or SystemClock()).now()
    repository = AuthRepository()
    audit = AuthAuditWriter(instance_id=instance_id)
    async with factory.begin() as session:
        await repository.lock_event_counter(session)
        await session.execute(text("SELECT pg_advisory_xact_lock(1245790711)"))
        owner = await session.scalar(
            select(UserModel).where(UserModel.username == normalized).with_for_update()
        )
        if owner is None:
            raise ValueError("the specified owner does not exist")
        other_owner = await session.scalar(
            select(UserModel.id).where(UserModel.enabled, UserModel.id != owner.id)
        )
        if other_owner is not None:
            raise ValueError("a different owner is enabled; local recovery refused")
        owner.password_hash = password_hash
        owner.enabled = True
        owner.updated_at = now
        owner.version += 1
        rows = list(
            await session.scalars(
                select(SessionModel)
                .where(SessionModel.user_id == owner.id, SessionModel.revoked_at.is_(None))
                .order_by(SessionModel.id)
                .with_for_update()
            )
        )
        for row in rows:
            row.revoked_at = now
            row.revoke_reason = "local_password_reset"
            await audit.append(
                session,
                event_type="auth.session_revoked",
                payload=SessionRevokedData(
                    user_id=UserId(owner.id),
                    session_id=SessionId(row.id),
                    reason="local_password_reset",
                ),
                occurred_at=now,
                correlation_id=str(owner.id),
                severity=EventSeverity.INFO,
                source_kind="local_cli",
                source_name="owner-password-reset",
            )
        await audit.append(
            session,
            event_type="auth.owner_password_reset",
            payload=OwnerPasswordResetData(
                user_id=UserId(owner.id), revoked_session_count=len(rows)
            ),
            occurred_at=now,
            correlation_id=str(owner.id),
            severity=EventSeverity.WARNING,
            source_kind="local_cli",
            source_name="owner-password-reset",
        )
        return UserId(owner.id), len(rows)


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
        operation = reset_owner_password if args.reset_password else bootstrap_owner
        owner_id, affected_count = await operation(
            create_async_session_factory(engine),
            username=str(args.username),
            password=_read_password(args.password_file),
            instance_id=settings.api_instance_id,
        )
    finally:
        await engine.dispose()
    action = "password reset" if args.reset_password else "bootstrap"
    print(f"Owner {action} complete: user_id={owner_id}; affected_rows={affected_count}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Create the one Jarvis V1 owner locally")
    parser.add_argument("--username", required=True)
    parser.add_argument("--password-file", type=Path)
    parser.add_argument(
        "--reset-password",
        action="store_true",
        help="Locally reset the existing owner's password and revoke every session",
    )
    args = parser.parse_args()
    try:
        return asyncio.run(_run(args))
    except (BootstrapAlreadyCompletedError, OSError, ValueError) as error:
        parser.exit(2, f"Owner bootstrap refused: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
