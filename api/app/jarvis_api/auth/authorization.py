"""Owner-scoped resource lookup helpers that do not disclose inaccessible IDs."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from jarvis_api.auth.repository import AuthRepository
from jarvis_api.errors import ApiProblemError
from jarvis_contracts.ids import UserId
from jarvis_persistence.models import ProjectModel, RunModel


class ObjectAuthorizer:
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        repository: AuthRepository | None = None,
    ) -> None:
        self._factory = factory
        self._repository = repository or AuthRepository()

    async def require_project(self, *, user_id: UserId, project_id: UUID) -> ProjectModel:
        async with self._factory() as session:
            project = await self._repository.owned_project(
                session, user_id=UUID(str(user_id)), project_id=project_id
            )
        if project is None:
            raise _not_found()
        return project

    async def require_run(self, *, user_id: UserId, run_id: UUID) -> RunModel:
        async with self._factory() as session:
            run = await self._repository.owned_run(
                session, user_id=UUID(str(user_id)), run_id=run_id
            )
        if run is None:
            raise _not_found()
        return run


def _not_found() -> ApiProblemError:
    return ApiProblemError(404, "resource.not_found", "The requested resource was not found")
