"""Database access constrained to authentication and ownership queries."""

from __future__ import annotations

from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from jarvis_persistence.models import (
    EventGlobalCounterModel,
    JobModel,
    LoginRateLimitModel,
    ProjectModel,
    RunModel,
    SessionModel,
    UserModel,
)


class AuthRepository:
    async def lock_event_counter(self, session: AsyncSession) -> None:
        counter = await session.scalar(
            select(EventGlobalCounterModel).where(EventGlobalCounterModel.id == 1).with_for_update()
        )
        if counter is None:
            raise RuntimeError("event store is not initialized")

    async def find_user(self, session: AsyncSession, username: str) -> UserModel | None:
        return cast(
            UserModel | None,
            await session.scalar(select(UserModel).where(UserModel.username == username)),
        )

    async def lock_rate_limits(
        self,
        session: AsyncSession,
        *,
        keys: tuple[tuple[str, str], ...],
        now: datetime,
    ) -> dict[tuple[str, str], LoginRateLimitModel]:
        ordered = sorted(keys)
        for scope, subject_hash in ordered:
            await session.execute(
                insert(LoginRateLimitModel)
                .values(
                    scope=scope,
                    subject_hash=subject_hash,
                    failed_count=0,
                    window_started_at=now,
                    updated_at=now,
                )
                .on_conflict_do_nothing(
                    index_elements=[
                        LoginRateLimitModel.scope,
                        LoginRateLimitModel.subject_hash,
                    ]
                )
            )
        rows: dict[tuple[str, str], LoginRateLimitModel] = {}
        for scope, subject_hash in ordered:
            row = await session.scalar(
                select(LoginRateLimitModel)
                .where(
                    LoginRateLimitModel.scope == scope,
                    LoginRateLimitModel.subject_hash == subject_hash,
                )
                .with_for_update()
            )
            if row is None:
                raise RuntimeError("login rate-limit row disappeared")
            rows[(scope, subject_hash)] = row
        return rows

    async def create_session(self, session: AsyncSession, row: SessionModel) -> None:
        session.add(row)
        await session.flush()

    async def get_session_with_user(
        self,
        session: AsyncSession,
        token_hash: str,
        *,
        lock: bool,
    ) -> tuple[SessionModel, UserModel] | None:
        statement = (
            select(SessionModel, UserModel)
            .join(UserModel, UserModel.id == SessionModel.user_id)
            .where(SessionModel.token_hash == token_hash)
        )
        if lock:
            statement = statement.with_for_update()
        row = (await session.execute(statement)).one_or_none()
        if row is None:
            return None
        return row[0], row[1]

    async def get_session_by_id(
        self, session: AsyncSession, session_id: UUID, *, lock: bool
    ) -> SessionModel | None:
        statement = select(SessionModel).where(SessionModel.id == session_id)
        if lock:
            statement = statement.with_for_update()
        return cast(SessionModel | None, await session.scalar(statement))

    async def owned_project(
        self, session: AsyncSession, *, user_id: UUID, project_id: UUID
    ) -> ProjectModel | None:
        return cast(
            ProjectModel | None,
            await session.scalar(
                select(ProjectModel).where(
                    ProjectModel.id == project_id,
                    ProjectModel.owner_user_id == user_id,
                )
            ),
        )

    async def owned_run(
        self, session: AsyncSession, *, user_id: UUID, run_id: UUID
    ) -> RunModel | None:
        return cast(
            RunModel | None,
            await session.scalar(
                select(RunModel)
                .join(JobModel, JobModel.id == RunModel.job_id)
                .join(ProjectModel, ProjectModel.id == JobModel.project_id)
                .where(RunModel.id == run_id, ProjectModel.owner_user_id == user_id)
            ),
        )
