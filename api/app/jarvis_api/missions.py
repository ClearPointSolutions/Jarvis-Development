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
from jarvis_contracts.commands import RunCommandRequest
from jarvis_contracts.enums import EventMode, EventSeverity, EventVisibility, RunCommandKind
from jarvis_contracts.events import EventScope, EventSource
from jarvis_contracts.missions import (
    DirectiveUpdate,
    FixedTeamSelection,
    ManagementTurnPage,
    ManagementTurnView,
    MissionAutonomyUpdate,
    MissionControlRequest,
    MissionControlView,
    MissionCreate,
    MissionMessageCreate,
    MissionMessagePage,
    MissionMessageView,
    MissionPage,
    MissionResourceLimits,
    MissionView,
    MissionWakeupPage,
    MissionWakeupView,
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
from jarvis_orchestrator.mission_resources import (
    MissionAdmissionDeniedError,
    MissionBudgetDeniedError,
    ensure_controls,
    release,
    require_admission,
    reserve,
    usage_view,
)
from jarvis_orchestrator.runtime.ownership import RunOwnership, lock_events, runtime_writer
from jarvis_persistence.models import (
    ConfigurationRevisionModel,
    EventGlobalCounterModel,
    ManagementTurnModel,
    MissionAdmissionControlModel,
    MissionDirectiveModel,
    MissionMessageModel,
    MissionModel,
    MissionTeamVersionModel,
    MissionWakeupModel,
    MissionWorkItemDependencyModel,
    MissionWorkItemModel,
    ProjectModel,
    RunModel,
    WorkflowTemplateModel,
    WorkflowVersionModel,
)
from jarvis_persistence.repositories import (
    CommandRepository,
    IdempotencyConflictError,
    IdempotencyRepository,
)

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
        autonomous=row.autonomous,
        waiting_reason=row.waiting_reason,
        next_action=row.next_action,
        next_action_basis=row.next_action_basis,
        user_action_required=row.user_action_required,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def detailed_view(session: AsyncSession, row: MissionModel, team_version: int) -> MissionView:
    controls = list(
        await session.scalars(
            select(MissionAdmissionControlModel).where(
                MissionAdmissionControlModel.scope_key.in_(
                    ("global", f"team:{row.selected_team_version_id}", f"mission:{row.id}")
                )
            )
        )
    )
    active_directive = await session.scalar(
        select(MissionWorkItemModel.directive_version)
        .where(
            MissionWorkItemModel.mission_id == row.id,
            MissionWorkItemModel.lifecycle == "started",
        )
        .limit(1)
    )
    return view(row, team_version).model_copy(
        update={
            "controls": {control.scope: control.state for control in controls},
            "active_work_directive_version": active_directive,
            "usage": await usage_view(session, row, datetime.now(UTC)),
            # Legacy worker-managed paid credentials cannot yet be metered by
            # the control plane; this must remain honest even when autonomy is on.
            "paid_unattended_available": False,
        }
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
    row = (
        await session.execute(statement.with_for_update(of=MissionModel) if lock else statement)
    ).one_or_none()
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
    template = await registry._reference_spec(
        session, team_template_revision_id, "team_template", active=True
    )
    if not isinstance(template, TeamTemplateSpec) or template.mode != mode:
        raise ApiProblemError(422, "mission.mode_mismatch", "Mission and team modes differ")
    team = FixedTeamSelection(
        team_template_revision_id=team_template_revision_id,
        **template.model_dump(mode="python", exclude={"kind", "mode"}),
    )
    roles = [
        (team.manager_role_revision_id, "manager"),
        (team.developer_role_revision_id, "developer"),
        (team.reviewer_role_revision_id, "reviewer"),
    ]
    for revision_id, responsibility in roles:
        role = await registry._reference_spec(session, revision_id, "agent_role", active=True)
        if not isinstance(role, AgentRoleSpec) or role.responsibility != responsibility:
            raise ApiProblemError(422, "mission.invalid_team", "Team role responsibility mismatch")
    for revision_id, purpose in (
        (team.manager_profile_revision_id, "mission_manager"),
        (team.reviewer_profile_revision_id, "reviewer"),
    ):
        profile = await registry._reference_spec(session, revision_id, "model_profile", active=True)
        if not isinstance(profile, ModelProfileSpec) or purpose not in profile.purposes:
            raise ApiProblemError(
                422, "mission.invalid_team", "Team profiles lack their required purposes"
            )
        if not profile.structured_json or profile.context_limit < 16_384:
            raise ApiProblemError(
                422,
                "mission.invalid_team",
                "Team profiles require structured JSON and at least 16384 context tokens",
            )
        provider = await registry._reference_spec(
            session, profile.provider_revision_id, "provider_connection", active=True
        )
        assert isinstance(provider, ProviderSpec)
        if (provider.provider_kind == "demo") != (mode == "demo"):
            raise ApiProblemError(422, "mission.mode_mismatch", "Mission and provider modes differ")
    worker = await registry._reference_spec(
        session, team.developer_worker_revision_id, "worker", active=True
    )
    if not isinstance(worker, WorkerSpec) or worker.max_concurrency != 1:
        raise ApiProblemError(
            422, "mission.invalid_team", "Development team requires one exclusive worker"
        )
    if (worker.adapter_kind == "demo") != (mode == "demo"):
        raise ApiProblemError(422, "mission.mode_mismatch", "Mission and worker modes differ")
    workflow = await session.scalar(
        select(WorkflowVersionModel)
        .join(
            WorkflowTemplateModel,
            WorkflowVersionModel.workflow_template_id == WorkflowTemplateModel.id,
        )
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


async def autonomous_unpaid_only(session: AsyncSession, selection: FixedTeamSelection) -> bool:
    """Paid unattended execution stays disabled until worker usage is enforceable."""
    profile_ids = {
        selection.manager_profile_revision_id,
        selection.reviewer_profile_revision_id,
    }
    worker_row = await session.get(
        ConfigurationRevisionModel, selection.developer_worker_revision_id
    )
    if worker_row is None:
        return False
    worker = WorkerSpec.model_validate(worker_row.spec_json["spec"])
    profile_ids.update(worker.model_binding.allowed_profile_revision_ids)
    for profile_id in profile_ids:
        row = await session.get(ConfigurationRevisionModel, profile_id)
        if row is None:
            return False
        profile = ModelProfileSpec.model_validate(row.spec_json["spec"])
        provider_row = await session.get(ConfigurationRevisionModel, profile.provider_revision_id)
        if provider_row is None:
            return False
        provider = ProviderSpec.model_validate(provider_row.spec_json["spec"])
        if provider.egress.paid:
            return False
    return True


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
            autonomous=body.autonomous,
            resource_limits_json=body.limits.model_dump(mode="json"),
            budget_window_started_at=now,
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
        # The mission and its selected immutable team version intentionally form
        # a deferred FK cycle. Flush the mission first so immediate child FKs
        # (including the initial directive) always observe their parent.
        session.add(mission)
        await session.flush()
        if body.autonomous and not await autonomous_unpaid_only(session, team_selection):
            raise ApiProblemError(
                422,
                "mission.paid_unattended_disabled",
                "Autonomous mode requires entirely unpaid, enforceably bounded model bindings",
            )
        session.add(team)
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
        await ensure_controls(session, mission)
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
        return await detailed_view(session, mission, team.version)


@router.put("/{mission_id}/autonomy", response_model=MissionView)
async def update_autonomy(
    request: Request,
    mission_id: UUID,
    body: MissionAutonomyUpdate,
    principal: CsrfPrincipal,
) -> MissionView:
    async with sessions(request, principal).begin() as session:
        await lock_events(session)
        mission, team = await owned(session, mission_id, principal.user_id, lock=True)
        try:
            idem, fresh = await IdempotencyRepository().begin(
                session,
                scope=f"mission:autonomy:{mission_id}",
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
        selection = FixedTeamSelection.model_validate(team.selection_json)
        if body.enabled and not await autonomous_unpaid_only(session, selection):
            raise ApiProblemError(
                422,
                "mission.paid_unattended_disabled",
                "Paid or unmetered worker inference cannot run unattended",
            )
        mission.autonomous = body.enabled
        mission.version += 1
        if body.enabled and mission.lifecycle == "idle":
            mission.lifecycle = "active"
        await emit(
            session,
            mission,
            "mission.autonomy_changed",
            {"mission_id": str(mission.id), "enabled": body.enabled},
        )
        result = await detailed_view(session, mission, team.version)
        idem.state, idem.response_status, idem.response_json = (
            "completed",
            200,
            result.model_dump(mode="json"),
        )
        return result


@router.post("/{mission_id}/controls", response_model=MissionControlView)
async def control_mission(
    request: Request,
    mission_id: UUID,
    body: MissionControlRequest,
    principal: CsrfPrincipal,
) -> MissionControlView:
    async with sessions(request, principal).begin() as session:
        await lock_events(session)
        mission, team = await owned(session, mission_id, principal.user_id, lock=True)
        try:
            idem, fresh = await IdempotencyRepository().begin(
                session,
                scope=f"mission:control:{mission_id}",
                key=body.idempotency_key,
                request_digest=sha256_digest(body.model_dump(mode="json")),
            )
        except IdempotencyConflictError:
            raise ApiProblemError(
                409, "mission.idempotency_conflict", "Idempotency input changed"
            ) from None
        if not fresh:
            return MissionControlView.model_validate(idem.response_json)
        if mission.version != body.expected_version:
            raise ApiProblemError(
                409, "mission.version_conflict", "Mission changed; refresh and retry"
            )
        await ensure_controls(session, mission)
        scope_key = {
            "global": "global",
            "team": f"team:{team.id}",
            "mission": f"mission:{mission.id}",
        }[body.scope]
        control = await session.scalar(
            select(MissionAdmissionControlModel)
            .where(MissionAdmissionControlModel.scope_key == scope_key)
            .with_for_update()
        )
        assert control is not None
        if body.action == "safe_point":
            control.safe_point_instruction = body.instruction
        else:
            control.state = {
                "pause": "paused",
                "resume": "open",
                "drain": "draining",
                "cancel": "cancelling",
            }[body.action]
        if body.limits is not None:
            control.resource_limits_json = body.limits.model_dump(mode="json")
            if body.scope == "mission":
                mission.resource_limits_json = body.limits.model_dump(mode="json")
        control.version += 1
        active = await session.scalar(
            select(RunModel)
            .join(MissionWorkItemModel, MissionWorkItemModel.run_id == RunModel.id)
            .where(
                MissionWorkItemModel.mission_id == mission.id,
                MissionWorkItemModel.lifecycle == "started",
                RunModel.status.not_in(("completed", "failed", "blocked", "cancelled")),
            )
            .with_for_update()
        )
        command_kind = {
            "pause": RunCommandKind.PAUSE,
            "resume": RunCommandKind.RESUME,
            "cancel": RunCommandKind.CANCEL,
            "safe_point": RunCommandKind.INSTRUCTION,
        }.get(body.action)
        if active is not None and command_kind is not None:
            receipt = await CommandRepository().enqueue(
                session,
                RunCommandRequest(
                    run_id=active.id,
                    kind=command_kind,
                    idempotency_key=f"mission-control:{body.idempotency_key}",
                    expected_run_version=active.version,
                    payload={
                        "actor_id": str(principal.user_id),
                        **({"instruction": body.instruction} if body.instruction else {}),
                    },
                ),
            )
            if not receipt.duplicate:
                active.version += 1
                await RunOwnership(
                    sessions(request, principal), owner="control-api"
                ).event(
                    session,
                    active,
                    "run.command_requested",
                    {
                        "command_id": str(receipt.command_id),
                        "kind": command_kind.value,
                        "sequence": receipt.sequence,
                        "actor_id": str(principal.user_id),
                    },
                )
        if body.scope == "mission":
            if body.action == "pause":
                mission.lifecycle = "paused"
                mission.waiting_reason = "admission_paused"
            elif body.action == "resume":
                mission.lifecycle = "active"
                mission.waiting_reason = None
            elif body.action == "cancel":
                mission.lifecycle = "cancelling" if active is not None else "cancelled"
                mission.waiting_reason = (
                    "cancellation_requested" if active is not None else None
                )
            elif body.action == "drain":
                mission.next_action = "Wait for active work to reach a terminal safe point"
                mission.next_action_basis = "Mission admission is draining"
        mission.version += 1
        await emit(
            session,
            mission,
            "mission.control_changed",
            {"scope": body.scope, "action": body.action, "state": control.state},
        )
        result = MissionControlView(
            scope=body.scope,
            state=control.state,
            instruction=control.safe_point_instruction,
            limits=control.resource_limits_json,
            version=control.version,
        )
        idem.state, idem.response_status, idem.response_json = (
            "completed",
            200,
            result.model_dump(mode="json"),
        )
        return result


@router.get("/{mission_id}/wakeups", response_model=MissionWakeupPage)
async def list_wakeups(
    request: Request,
    mission_id: UUID,
    principal: CurrentPrincipal,
    after: UUID | None = None,
    limit: Limit = 50,
) -> MissionWakeupPage:
    async with sessions(request, principal)() as session:
        await owned(session, mission_id, principal.user_id)
        query = select(MissionWakeupModel).where(MissionWakeupModel.mission_id == mission_id)
        if after:
            query = query.where(MissionWakeupModel.id > after)
        rows = list(
            (await session.scalars(query.order_by(MissionWakeupModel.id).limit(limit + 1))).all()
        )
        return MissionWakeupPage(
            items=tuple(
                MissionWakeupView(
                    id=row.id,
                    kind=row.kind,
                    status=row.status,
                    deduplication_key=row.deduplication_key,
                    directive_version=row.directive_version,
                    source_event_cursor=row.source_event_cursor,
                    management_turn_id=row.management_turn_id,
                    scheduled_for=row.scheduled_for,
                    created_at=row.created_at,
                )
                for row in rows[:limit]
            ),
            next_after=rows[limit - 1].id if len(rows) > limit else None,
        )


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
        if mission.lifecycle in {"cancelling", "cancelled", "completed", "archived"}:
            raise ApiProblemError(409, "mission.terminal", "Mission no longer accepts direction")
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
        if mission.lifecycle in {"cancelling", "cancelled", "completed", "archived"}:
            raise ApiProblemError(409, "mission.terminal", "Mission no longer accepts messages")
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
        snapshot = {
            "objective": mission.objective,
            "constraints": mission.constraints_json,
            "directive_version": mission.directive_version,
            "team_version": team.version,
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
                    "run_id": str(row.run_id) if row.run_id else None,
                }
                for row in backlog
            ],
        }
        cursor = await session.scalar(
            select(EventGlobalCounterModel.last_position).where(EventGlobalCounterModel.id == 1)
        )
        wakeup = MissionWakeupModel(
            id=uuid7(),
            mission_id=mission.id,
            kind="user_direction",
            deduplication_key=f"user-direction:{message.id}",
            directive_version=mission.directive_version,
            team_version_id=team.id,
            source_event_cursor=cursor or 0,
            accepted_target_identity=str(message.id),
            accepted_source_identity=str(principal.user_id),
            snapshot_json=snapshot,
            status="turn_queued",
            scheduled_for=datetime.now(UTC),
        )
        session.add(wakeup)
        await session.flush()
        turn = ManagementTurnModel(
            id=uuid7(),
            mission_id=mission.id,
            input_message_id=message.id,
            directive_version=mission.directive_version,
            team_version_id=team.id,
            input_snapshot_json=snapshot,
            status="queued",
            mode=mission.mode,
            allow_paid_inference=body.allow_paid_inference,
            claimable_at=datetime.now(UTC),
            attempt_count=0,
            wakeup_id=wakeup.id,
            source_event_cursor=cursor or 0,
        )
        session.add(turn)
        wakeup.management_turn_id = turn.id
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
    factory = sessions(request, principal)
    async with factory.begin() as session:
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
        try:
            await require_admission(session, mission, operation="dispatch")
            limits = MissionResourceLimits.model_validate(mission.resource_limits_json)
            await reserve(
                session,
                mission,
                action_id=f"job:{item.id}",
                kind="job_execution",
                liability={
                    "active_jobs": 1,
                    "wall_seconds": min(7_200, limits.max_wall_seconds),
                },
                currency=limits.currency,
                now=datetime.now(UTC),
            )
        except MissionAdmissionDeniedError as error:
            raise ApiProblemError(409, "mission.admission_paused", str(error)) from None
        except MissionBudgetDeniedError as error:
            raise ApiProblemError(409, "mission.budget_denied", str(error)) from None
        selection = FixedTeamSelection.model_validate(team.selection_json)
        objective = (
            item.objective
            + "\n\nAcceptance criteria:\n- "
            + "\n- ".join(item.acceptance_criteria_json)
            + "\n\nMission constraints:\n- "
            + "\n- ".join(mission.constraints_json or ["No additional constraints"])
        )
    try:
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
    except Exception:
        async with factory.begin() as session:
            mission, _ = await owned(session, mission_id, principal.user_id, lock=True)
            await release(session, mission, action_id=f"job:{item_id}", now=datetime.now(UTC))
        raise
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
