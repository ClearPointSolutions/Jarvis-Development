"""Owner-scoped persistent mission API above the existing run engine."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Query, Request
from pydantic import JsonValue
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased
from uuid6 import uuid7

from jarvis_api.auth.dependencies import CsrfPrincipal, CurrentPrincipal
from jarvis_api.auth.service import AuthPrincipal
from jarvis_api.errors import ApiProblemError
from jarvis_api.events.normalizer import EventIntent
from jarvis_api.registry.service import RegistryService, _safe_strings
from jarvis_api.runtime import create_job
from jarvis_contracts.base import sha256_digest
from jarvis_contracts.enums import EventMode, EventSeverity, EventVisibility
from jarvis_contracts.events import EventScope, EventSource
from jarvis_contracts.missions import (
    DirectiveUpdate,
    FixedTeamSelection,
    ManagementTurnPage,
    ManagementTurnView,
    MissionCreate,
    MissionMessageCreate,
    MissionMessagePage,
    MissionMessageView,
    MissionPage,
    MissionView,
    WorkItemPage,
    WorkItemStart,
    WorkItemView,
)
from jarvis_contracts.registry import (
    AgentRoleSpec,
    ModelProfileSpec,
    ProviderSpec,
    TeamTemplateSpec,
    WorkerSpec,
)
from jarvis_contracts.runtime_api import JobCreate, RunView
from jarvis_contracts.workflow_api import WorkflowResolvedSnapshot
from jarvis_orchestrator.runtime.ownership import lock_events, runtime_writer
from jarvis_persistence.models import (
    ManagementTurnModel,
    MissionDirectiveModel,
    MissionMessageModel,
    MissionModel,
    MissionTeamVersionModel,
    MissionWorkItemDependencyModel,
    MissionWorkItemModel,
    ProjectModel,
    RunModel,
    WorkflowTemplateModel,
    WorkflowVersionModel,
)
from jarvis_persistence.repositories import IdempotencyConflictError, IdempotencyRepository

router = APIRouter(prefix="/api/v1/missions", tags=["missions"])
Limit = Annotated[int, Query(ge=1, le=100)]


def sessions(request: Request, principal: AuthPrincipal) -> async_sessionmaker[AsyncSession]:
    if principal.role != "owner":
        raise ApiProblemError(403, "mission.forbidden", "Owner access is required")
    return cast(async_sessionmaker[AsyncSession], request.app.state.session_factory)


def missing() -> ApiProblemError:
    return ApiProblemError(404, "mission.not_found", "Mission resource not found")


def view(row: MissionModel, team_version: int) -> MissionView:
    return MissionView(
        id=row.id,
        project_id=row.project_id,
        objective=row.objective,
        constraints=tuple(row.constraints_json),
        lifecycle=row.lifecycle,
        mode=row.mode,
        version=row.version,
        directive_version=row.directive_version,
        team_version=team_version,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def owned(
    session: AsyncSession, mission_id: UUID, user_id: UUID, *, lock: bool = False
) -> tuple[MissionModel, MissionTeamVersionModel]:
    statement = (
        select(MissionModel, MissionTeamVersionModel)
        .join(ProjectModel, ProjectModel.id == MissionModel.project_id)
        .join(
            MissionTeamVersionModel,
            MissionTeamVersionModel.id == MissionModel.selected_team_version_id,
        )
        .where(MissionModel.id == mission_id, ProjectModel.owner_user_id == user_id)
    )
    row = (await session.execute(statement.with_for_update() if lock else statement)).one_or_none()
    if row is None:
        raise missing()
    return row[0], row[1]


async def emit(
    session: AsyncSession, mission: MissionModel, event_type: str, data: dict[str, JsonValue]
) -> None:
    await runtime_writer().append(
        session,
        EventIntent(
            occurred_at=datetime.now(UTC),
            type=event_type,
            severity=EventSeverity.INFO,
            mode=EventMode(mission.mode),
            visibility=EventVisibility.OWNER,
            scope=EventScope(project_id=mission.project_id),
            source=EventSource(kind="api", name="mission-control"),
            correlation_id=str(mission.id),
            data=data,
        ),
    )


async def validate_team(
    request: Request,
    session: AsyncSession,
    team_template_revision_id: UUID,
    user_id: UUID,
    mode: str,
) -> FixedTeamSelection:
    registry = cast(RegistryService, request.app.state.registry_service)
    template = await registry._revision(
        session, team_template_revision_id, "team_template", active=True
    )
    if not isinstance(template.spec, TeamTemplateSpec) or template.spec.mode != mode:
        raise ApiProblemError(422, "mission.mode_mismatch", "Mission and team modes differ")
    team = FixedTeamSelection(
        team_template_revision_id=team_template_revision_id,
        **template.spec.model_dump(mode="python", exclude={"kind"}),
    )
    roles = [
        (team.manager_role_revision_id, "manager"),
        (team.developer_role_revision_id, "developer"),
        (team.reviewer_role_revision_id, "reviewer"),
    ]
    for revision_id, responsibility in roles:
        record = await registry._revision(session, revision_id, "agent_role", active=True)
        if (
            not isinstance(record.spec, AgentRoleSpec)
            or record.spec.responsibility != responsibility
        ):
            raise ApiProblemError(422, "mission.invalid_team", "Team role responsibility mismatch")
    for revision_id, purpose in (
        (team.manager_profile_revision_id, "mission_manager"),
        (team.reviewer_profile_revision_id, "reviewer"),
    ):
        record = await registry._revision(session, revision_id, "model_profile", active=True)
        if not isinstance(record.spec, ModelProfileSpec) or purpose not in record.spec.purposes:
            raise ApiProblemError(
                422, "mission.invalid_team", "Team profiles lack their required purposes"
            )
        if not record.spec.structured_json or record.spec.context_limit < 16_384:
            raise ApiProblemError(
                422,
                "mission.invalid_team",
                "Team profiles require structured JSON and at least 16384 context tokens",
            )
        provider = await registry._revision(
            session, record.spec.provider_revision_id, "provider_connection", active=True
        )
        assert isinstance(provider.spec, ProviderSpec)
        if (provider.spec.provider_kind == "demo") != (mode == "demo"):
            raise ApiProblemError(422, "mission.mode_mismatch", "Mission and provider modes differ")
    worker = await registry._revision(
        session, team.developer_worker_revision_id, "worker", active=True
    )
    if not isinstance(worker.spec, WorkerSpec) or worker.spec.max_concurrency != 1:
        raise ApiProblemError(
            422, "mission.invalid_team", "Development team requires one exclusive worker"
        )
    if (worker.spec.adapter_kind == "demo") != (mode == "demo"):
        raise ApiProblemError(422, "mission.mode_mismatch", "Mission and worker modes differ")
    workflow = await session.scalar(
        select(WorkflowVersionModel)
        .join(WorkflowTemplateModel)
        .where(
            WorkflowVersionModel.id == team.workflow_version_id,
            WorkflowVersionModel.published_at.is_not(None),
            WorkflowTemplateModel.owner_user_id == user_id,
            WorkflowTemplateModel.archived_at.is_(None),
        )
    )
    if workflow is None:
        raise ApiProblemError(422, "mission.invalid_team", "Team workflow is not published")
    if workflow.resolved_snapshot_json is None:
        raise ApiProblemError(
            422, "mission.invalid_team", "Team workflow lacks a resolved execution snapshot"
        )
    snapshot = WorkflowResolvedSnapshot.model_validate(workflow.resolved_snapshot_json)
    referenced = {revision.revision_id for revision in snapshot.revisions}
    required = {
        team.manager_profile_revision_id,
        team.reviewer_profile_revision_id,
        team.developer_worker_revision_id,
    }
    if not required <= referenced:
        raise ApiProblemError(
            422,
            "mission.invalid_team",
            "Team execution bindings must be frozen by the published workflow",
        )
    return team


@router.post("", response_model=MissionView, status_code=201)
async def create_mission(
    request: Request, body: MissionCreate, principal: CsrfPrincipal
) -> MissionView:
    _safe_strings(body.model_dump(mode="json"))
    async with sessions(request, principal).begin() as session:
        await lock_events(session)
        project = await session.scalar(
            select(ProjectModel).where(
                ProjectModel.id == body.project_id,
                ProjectModel.owner_user_id == principal.user_id,
                ProjectModel.status == "active",
            )
        )
        if project is None:
            raise missing()
        try:
            idem, fresh = await IdempotencyRepository().begin(
                session,
                scope=f"mission:create:{principal.user_id}",
                key=body.idempotency_key,
                request_digest=sha256_digest(body.model_dump(mode="json")),
            )
        except IdempotencyConflictError:
            raise ApiProblemError(
                409, "mission.idempotency_conflict", "Idempotency input changed"
            ) from None
        if not fresh:
            return MissionView.model_validate(idem.response_json)
        team_selection = await validate_team(
            request,
            session,
            body.team_template_revision_id,
            principal.user_id,
            body.mode,
        )
        now = datetime.now(UTC)
        mission_id, team_id = uuid7(), uuid7()
        mission = MissionModel(
            id=mission_id,
            project_id=body.project_id,
            objective=body.objective,
            constraints_json=list(body.constraints),
            lifecycle="active",
            mode=body.mode,
            directive_version=1,
            selected_team_version_id=team_id,
            version=1,
            created_at=now,
            updated_at=now,
        )
        team = MissionTeamVersionModel(
            id=team_id,
            mission_id=mission_id,
            version=1,
            selection_json=team_selection.model_dump(mode="json"),
            content_hash=sha256_digest(team_selection.model_dump(mode="json")),
        )
        session.add_all((mission, team))
        session.add(
            MissionDirectiveModel(
                id=uuid7(),
                mission_id=mission.id,
                version=1,
                objective=body.objective,
                constraints_json=list(body.constraints),
                content_hash=sha256_digest(
                    {"objective": body.objective, "constraints": body.constraints}
                ),
                created_by=principal.user_id,
            )
        )
        await session.flush()
        result = view(mission, 1)
        await emit(
            session,
            mission,
            "mission.created",
            {"mission_id": str(mission.id), "actor_id": str(principal.user_id)},
        )
        idem.state, idem.response_status, idem.response_json = (
            "completed",
            201,
            result.model_dump(mode="json"),
        )
        return result


@router.get("", response_model=MissionPage)
async def list_missions(
    request: Request, principal: CurrentPrincipal, after: UUID | None = None, limit: Limit = 50
) -> MissionPage:
    async with sessions(request, principal)() as session:
        query = (
            select(MissionModel, MissionTeamVersionModel)
            .join(ProjectModel, ProjectModel.id == MissionModel.project_id)
            .join(
                MissionTeamVersionModel,
                MissionTeamVersionModel.id == MissionModel.selected_team_version_id,
            )
            .where(ProjectModel.owner_user_id == principal.user_id)
        )
        if after:
            query = query.where(MissionModel.id > after)
        rows = (await session.execute(query.order_by(MissionModel.id).limit(limit + 1))).all()
        return MissionPage(
            items=tuple(view(m, t.version) for m, t in rows[:limit]),
            next_after=rows[limit - 1][0].id if len(rows) > limit else None,
        )


@router.get("/{mission_id}", response_model=MissionView)
async def get_mission(
    request: Request, mission_id: UUID, principal: CurrentPrincipal
) -> MissionView:
    async with sessions(request, principal)() as session:
        mission, team = await owned(session, mission_id, principal.user_id)
        return view(mission, team.version)


@router.put("/{mission_id}/directive", response_model=MissionView)
async def update_directive(
    request: Request, mission_id: UUID, body: DirectiveUpdate, principal: CsrfPrincipal
) -> MissionView:
    _safe_strings(body.model_dump(mode="json"))
    async with sessions(request, principal).begin() as session:
        await lock_events(session)
        mission, team = await owned(session, mission_id, principal.user_id, lock=True)
        try:
            idem, fresh = await IdempotencyRepository().begin(
                session,
                scope=f"mission:directive:{mission_id}",
                key=body.idempotency_key,
                request_digest=sha256_digest(body.model_dump(mode="json")),
            )
        except IdempotencyConflictError:
            raise ApiProblemError(
                409, "mission.idempotency_conflict", "Idempotency input changed"
            ) from None
        if not fresh:
            return MissionView.model_validate(idem.response_json)
        if mission.version != body.expected_version:
            raise ApiProblemError(
                409, "mission.version_conflict", "Mission changed; refresh and retry"
            )
        mission.directive_version += 1
        mission.version += 1
        mission.objective, mission.constraints_json = body.objective, list(body.constraints)
        session.add(
            MissionDirectiveModel(
                id=uuid7(),
                mission_id=mission.id,
                version=mission.directive_version,
                objective=body.objective,
                constraints_json=list(body.constraints),
                content_hash=sha256_digest(
                    {"objective": body.objective, "constraints": body.constraints}
                ),
                created_by=principal.user_id,
            )
        )
        result = view(mission, team.version)
        await emit(
            session,
            mission,
            "mission.directive_revised",
            {
                "mission_id": str(mission.id),
                "directive_version": mission.directive_version,
                "actor_id": str(principal.user_id),
            },
        )
        idem.state, idem.response_status, idem.response_json = (
            "completed",
            200,
            result.model_dump(mode="json"),
        )
        return result


@router.post("/{mission_id}/messages", response_model=ManagementTurnView, status_code=202)
async def create_message(
    request: Request, mission_id: UUID, body: MissionMessageCreate, principal: CsrfPrincipal
) -> ManagementTurnView:
    _safe_strings(body.model_dump(mode="json"))
    async with sessions(request, principal).begin() as session:
        await lock_events(session)
        mission, team = await owned(session, mission_id, principal.user_id, lock=True)
        try:
            idem, fresh = await IdempotencyRepository().begin(
                session,
                scope=f"mission:message:{mission_id}",
                key=body.idempotency_key,
                request_digest=sha256_digest(body.model_dump(mode="json")),
            )
        except IdempotencyConflictError:
            raise ApiProblemError(
                409, "mission.idempotency_conflict", "Idempotency input changed"
            ) from None
        if not fresh:
            return ManagementTurnView.model_validate(idem.response_json)
        if mission.version != body.expected_version:
            raise ApiProblemError(
                409, "mission.version_conflict", "Mission changed; refresh and retry"
            )
        mission.next_message_sequence += 1
        message = MissionMessageModel(
            id=uuid7(),
            mission_id=mission.id,
            sequence=mission.next_message_sequence,
            role="user",
            identity=str(principal.user_id),
            body=body.body,
            directive_version=mission.directive_version,
            disposition="queued",
            context_json={},
        )
        session.add(message)
        await session.flush()
        histories = list(
            (
                await session.scalars(
                    select(MissionMessageModel)
                    .where(MissionMessageModel.mission_id == mission.id)
                    .order_by(MissionMessageModel.sequence.desc())
                    .limit(50)
                )
            ).all()
        )
        backlog = list(
            (
                await session.scalars(
                    select(MissionWorkItemModel)
                    .where(MissionWorkItemModel.mission_id == mission.id)
                    .order_by(MissionWorkItemModel.priority.desc(), MissionWorkItemModel.id)
                    .limit(100)
                )
            ).all()
        )
        dependency_keys: dict[UUID, list[str]] = {row.id: [] for row in backlog}
        if backlog:
            dependency = aliased(MissionWorkItemModel)
            pairs = (
                await session.execute(
                    select(
                        MissionWorkItemDependencyModel.work_item_id,
                        dependency.key,
                    )
                    .join(
                        dependency,
                        dependency.id == MissionWorkItemDependencyModel.depends_on_work_item_id,
                    )
                    .where(
                        MissionWorkItemDependencyModel.work_item_id.in_([row.id for row in backlog])
                    )
                )
            ).all()
            for work_item_id, dependency_key in pairs:
                dependency_keys[work_item_id].append(dependency_key)
        turn = ManagementTurnModel(
            id=uuid7(),
            mission_id=mission.id,
            input_message_id=message.id,
            directive_version=mission.directive_version,
            team_version_id=team.id,
            input_snapshot_json={
                "objective": mission.objective,
                "constraints": mission.constraints_json,
                "messages": [
                    {"role": row.role, "body": row.body, "sequence": row.sequence}
                    for row in reversed(histories)
                ],
                "backlog": [
                    {
                        "key": row.key,
                        "title": row.title,
                        "objective": row.objective,
                        "acceptance_criteria": row.acceptance_criteria_json,
                        "priority": row.priority,
                        "dependencies": dependency_keys[row.id],
                        "lifecycle": row.lifecycle,
                        "directive_version": row.directive_version,
                    }
                    for row in backlog
                ],
            },
            status="queued",
            mode=mission.mode,
            allow_paid_inference=body.allow_paid_inference,
            claimable_at=datetime.now(UTC),
            attempt_count=0,
        )
        session.add(turn)
        mission.version += 1
        await session.flush()
        message.management_turn_id = turn.id
        result = ManagementTurnView(
            id=turn.id,
            status="queued",
            directive_version=turn.directive_version,
            team_version=team.version,
            created_at=turn.created_at,
        )
        await emit(
            session,
            mission,
            "management.turn_queued",
            {
                "mission_id": str(mission.id),
                "management_turn_id": str(turn.id),
                "message_id": str(message.id),
            },
        )
        idem.state, idem.response_status, idem.response_json = (
            "completed",
            202,
            result.model_dump(mode="json"),
        )
        return result


@router.get("/{mission_id}/messages", response_model=MissionMessagePage)
async def list_messages(
    request: Request,
    mission_id: UUID,
    principal: CurrentPrincipal,
    after: int = 0,
    limit: Limit = 50,
) -> MissionMessagePage:
    async with sessions(request, principal)() as session:
        await owned(session, mission_id, principal.user_id)
        rows = list(
            (
                await session.scalars(
                    select(MissionMessageModel)
                    .where(
                        MissionMessageModel.mission_id == mission_id,
                        MissionMessageModel.sequence > after,
                    )
                    .order_by(MissionMessageModel.sequence)
                    .limit(limit + 1)
                )
            ).all()
        )
        return MissionMessagePage(
            items=tuple(
                MissionMessageView(
                    id=r.id,
                    sequence=r.sequence,
                    role=r.role,
                    identity=r.identity,
                    body=r.body,
                    directive_version=r.directive_version,
                    management_turn_id=r.management_turn_id,
                    disposition=r.disposition,
                    created_at=r.created_at,
                )
                for r in rows[:limit]
            ),
            next_after=rows[limit - 1].sequence if len(rows) > limit else None,
        )


@router.get("/{mission_id}/turns", response_model=ManagementTurnPage)
async def list_turns(
    request: Request,
    mission_id: UUID,
    principal: CurrentPrincipal,
    after: UUID | None = None,
    limit: Limit = 50,
) -> ManagementTurnPage:
    async with sessions(request, principal)() as session:
        await owned(session, mission_id, principal.user_id)
        query = (
            select(ManagementTurnModel, MissionTeamVersionModel)
            .join(
                MissionTeamVersionModel,
                MissionTeamVersionModel.id == ManagementTurnModel.team_version_id,
            )
            .where(ManagementTurnModel.mission_id == mission_id)
        )
        if after:
            query = query.where(ManagementTurnModel.id > after)
        rows = (
            await session.execute(query.order_by(ManagementTurnModel.id).limit(limit + 1))
        ).all()
        return ManagementTurnPage(
            items=tuple(
                ManagementTurnView(
                    id=turn.id,
                    status=turn.status,
                    directive_version=turn.directive_version,
                    team_version=team.version,
                    model_call_id=turn.model_call_id,
                    decision=turn.response_json,
                    failure_code=turn.failure_code,
                    created_at=turn.created_at,
                    completed_at=turn.completed_at,
                )
                for turn, team in rows[:limit]
            ),
            next_after=rows[limit - 1][0].id if len(rows) > limit else None,
        )


async def item_view(session: AsyncSession, row: MissionWorkItemModel) -> WorkItemView:
    deps = tuple(
        await session.scalars(
            select(MissionWorkItemDependencyModel.depends_on_work_item_id).where(
                MissionWorkItemDependencyModel.work_item_id == row.id
            )
        )
    )
    team = await session.get(MissionTeamVersionModel, row.team_version_id)
    assert team is not None
    return WorkItemView(
        id=row.id,
        key=row.key,
        title=row.title,
        objective=row.objective,
        acceptance_criteria=tuple(row.acceptance_criteria_json),
        priority=row.priority,
        dependencies=deps,
        lifecycle=row.lifecycle,
        directive_version=row.directive_version,
        team_version=team.version,
        job_id=row.job_id,
        run_id=row.run_id,
        created_at=row.created_at,
    )


@router.get("/{mission_id}/work-items", response_model=WorkItemPage)
async def list_items(
    request: Request,
    mission_id: UUID,
    principal: CurrentPrincipal,
    after: UUID | None = None,
    limit: Limit = 50,
) -> WorkItemPage:
    async with sessions(request, principal)() as session:
        await owned(session, mission_id, principal.user_id)
        query = select(MissionWorkItemModel).where(MissionWorkItemModel.mission_id == mission_id)
        if after:
            query = query.where(MissionWorkItemModel.id > after)
        rows = list(
            (await session.scalars(query.order_by(MissionWorkItemModel.id).limit(limit + 1))).all()
        )
        return WorkItemPage(
            items=tuple([await item_view(session, r) for r in rows[:limit]]),
            next_after=rows[limit - 1].id if len(rows) > limit else None,
        )


@router.post("/{mission_id}/work-items/{item_id}/start", response_model=RunView, status_code=202)
async def start_item(
    request: Request, mission_id: UUID, item_id: UUID, body: WorkItemStart, principal: CsrfPrincipal
) -> RunView:
    async with sessions(request, principal)() as session:
        mission, team = await owned(session, mission_id, principal.user_id)
        item = await session.scalar(
            select(MissionWorkItemModel).where(
                MissionWorkItemModel.id == item_id, MissionWorkItemModel.mission_id == mission_id
            )
        )
        if item is None:
            raise missing()
        if item.run_id:
            run = await session.get(RunModel, item.run_id)
            if run is None:
                raise missing()
            from jarvis_api.runtime import get_run

            return await get_run(request, run.id, principal)
        if mission.version != body.expected_mission_version:
            raise ApiProblemError(
                409, "mission.version_conflict", "Mission changed; refresh and retry"
            )
        if item.lifecycle != "ready":
            raise ApiProblemError(409, "mission.item_not_ready", "Work item is not ready")
        if item.directive_version != mission.directive_version:
            raise ApiProblemError(
                409,
                "mission.item_stale",
                "Work item was proposed under an older directive; ask the manager to revise it",
            )
        blocked = await session.scalar(
            select(MissionWorkItemDependencyModel.work_item_id)
            .join(
                MissionWorkItemModel,
                MissionWorkItemModel.id == MissionWorkItemDependencyModel.depends_on_work_item_id,
            )
            .where(
                MissionWorkItemDependencyModel.work_item_id == item.id,
                MissionWorkItemModel.lifecycle != "accepted",
            )
        )
        if blocked:
            raise ApiProblemError(
                409, "mission.dependencies_incomplete", "Dependencies must be accepted before start"
            )
        selection = FixedTeamSelection.model_validate(team.selection_json)
        objective = (
            item.objective
            + "\n\nAcceptance criteria:\n- "
            + "\n- ".join(item.acceptance_criteria_json)
            + "\n\nMission constraints:\n- "
            + "\n- ".join(mission.constraints_json or ["No additional constraints"])
        )
    result = await create_job(
        request,
        mission.project_id,
        JobCreate(
            idempotency_key=f"mission-work-item:{item.id}",
            workflow_version_id=selection.workflow_version_id,
            objective=objective,
            priority=item.priority,
            mode=mission.mode,
        ),
        principal,
    )
    async with sessions(request, principal).begin() as session:
        await lock_events(session)
        mission, _ = await owned(session, mission_id, principal.user_id, lock=True)
        item = await session.scalar(
            select(MissionWorkItemModel)
            .where(
                MissionWorkItemModel.id == item_id, MissionWorkItemModel.mission_id == mission_id
            )
            .with_for_update()
        )
        assert item is not None
        if item.run_id and item.run_id != result.id:
            raise ApiProblemError(
                409, "mission.launch_conflict", "Work item has a different linked run"
            )
        item.job_id, item.run_id, item.lifecycle = result.job_id, result.id, "started"
        item.version += 1
        mission.version += 1
        await emit(
            session,
            mission,
            "work_item.started",
            {
                "mission_id": str(mission.id),
                "work_item_id": str(item.id),
                "job_id": str(result.job_id),
                "run_id": str(result.id),
            },
        )
    return result
