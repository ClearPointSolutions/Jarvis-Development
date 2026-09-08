"""Authenticated durable enqueue/control and owner-scoped query endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from uuid6 import uuid7

from jarvis_api.auth.dependencies import CsrfPrincipal, CurrentPrincipal
from jarvis_api.auth.service import AuthPrincipal
from jarvis_api.errors import ApiProblemError
from jarvis_api.events.normalizer import EventIntent
from jarvis_api.registry.service import _safe_strings
from jarvis_api.workflows.service import WorkflowService
from jarvis_contracts.base import sha256_digest
from jarvis_contracts.commands import RunCommandReceipt, RunCommandRequest
from jarvis_contracts.enums import EventMode, EventSeverity, EventVisibility
from jarvis_contracts.events import EventScope, EventSource
from jarvis_contracts.runtime_api import (
    CommandPage,
    CommandView,
    JobCreate,
    JobPage,
    JobView,
    NodePage,
    NodeView,
    ProjectCreate,
    ProjectPage,
    ProjectView,
    RunControl,
    RunPage,
    RunView,
)
from jarvis_contracts.workflow import WorkflowSpec
from jarvis_orchestrator.runtime.ownership import RunOwnership, lock_events, runtime_writer
from jarvis_persistence.models import (
    JobModel,
    NodeExecutionModel,
    ProjectModel,
    RunCommandModel,
    RunConfigSnapshotModel,
    RunModel,
    WorkflowTemplateModel,
    WorkflowVersionModel,
)
from jarvis_persistence.repositories import (
    CommandRepository,
    IdempotencyConflictError,
    IdempotencyRepository,
    OptimisticConcurrencyConflictError,
)

router = APIRouter(prefix="/api/v1", tags=["runs"])
Limit = Annotated[int, Query(ge=1, le=100)]


def sessions(request: Request, principal: AuthPrincipal) -> async_sessionmaker[AsyncSession]:
    if principal.role != "owner":
        raise ApiProblemError(403, "run.forbidden", "Owner access is required")
    return cast(async_sessionmaker[AsyncSession], request.app.state.session_factory)


def missing() -> ApiProblemError:
    return ApiProblemError(404, "run.not_found", "Resource not found")


def run_view(run: RunModel, job: JobModel) -> RunView:
    return RunView(
        id=run.id,
        job_id=job.id,
        project_id=job.project_id,
        workflow_version_id=run.workflow_version_id,
        run_number=run.run_number,
        retry_of_run_id=run.parent_run_id,
        thread_id=run.langgraph_thread_id,
        status=run.status,
        desired_state=run.desired_state,
        mode=run.mode,
        version=run.version,
        recovering=bool(run.runtime_json.get("recovering")),
        current_node=run.current_node,
        result_summary=run.result_summary,
        claimable_at=run.claimable_at,
        started_at=run.started_at,
        completed_at=run.completed_at,
        last_event_position=run.last_event_position,
        last_run_sequence=run.last_run_sequence,
        last_event_at=run.last_event_at,
    )


@router.get("/projects", response_model=ProjectPage)
async def projects(
    request: Request, principal: CurrentPrincipal, after: UUID | None = None, limit: Limit = 50
) -> ProjectPage:
    async with sessions(request, principal)() as session:
        query = select(ProjectModel).where(ProjectModel.owner_user_id == principal.user_id)
        if after:
            query = query.where(ProjectModel.id > after)
        rows = list((await session.scalars(query.order_by(ProjectModel.id).limit(limit + 1))).all())
        return ProjectPage(
            items=tuple(
                ProjectView(id=row.id, slug=row.slug, name=row.name) for row in rows[:limit]
            ),
            next_after=rows[limit - 1].id if len(rows) > limit else None,
        )


@router.post("/projects", response_model=ProjectView, status_code=201)
async def create_project(
    request: Request, body: ProjectCreate, principal: CsrfPrincipal
) -> ProjectView:
    _safe_strings(body.model_dump(mode="json"))
    async with sessions(request, principal).begin() as session:
        await lock_events(session)
        try:
            record, fresh = await IdempotencyRepository().begin(
                session,
                scope=f"project:{principal.user_id}",
                key=body.idempotency_key,
                request_digest=sha256_digest(body.model_dump(mode="json")),
            )
        except IdempotencyConflictError:
            raise ApiProblemError(
                409, "run.idempotency_conflict", "Idempotency key content changed"
            ) from None
        if not fresh:
            return ProjectView.model_validate(record.response_json)
        if await session.scalar(select(ProjectModel.id).where(ProjectModel.slug == body.slug)):
            raise ApiProblemError(409, "run.slug_conflict", "Project slug is unavailable")
        row = ProjectModel(
            id=uuid7(),
            owner_user_id=principal.user_id,
            slug=body.slug,
            name=body.name,
            status="active",
        )
        session.add(row)
        await session.flush()
        view = ProjectView(id=row.id, slug=row.slug, name=row.name)
        await runtime_writer().append(
            session,
            EventIntent(
                occurred_at=datetime.now(UTC),
                type="project.created",
                severity=EventSeverity.INFO,
                mode=EventMode.REAL,
                visibility=EventVisibility.OWNER,
                scope=EventScope(project_id=row.id),
                source=EventSource(kind="api", name="run-control"),
                correlation_id=str(row.id),
                data={"actor_id": str(principal.user_id)},
            ),
        )
        record.state, record.response_status, record.response_json = (
            "completed",
            201,
            view.model_dump(mode="json"),
        )
        return view


@router.post("/projects/{project_id}/jobs", response_model=RunView, status_code=202)
async def create_job(
    request: Request, project_id: UUID, body: JobCreate, principal: CsrfPrincipal
) -> RunView:
    _safe_strings(body.model_dump(mode="json"))
    factory = sessions(request, principal)
    ownership = RunOwnership(factory, owner="control-api")
    async with factory.begin() as session:
        await lock_events(session)
        project = await session.scalar(
            select(ProjectModel).where(
                ProjectModel.id == project_id,
                ProjectModel.owner_user_id == principal.user_id,
                ProjectModel.status == "active",
            )
        )
        if project is None:
            raise missing()
        try:
            record, fresh = await IdempotencyRepository().begin(
                session,
                scope=f"enqueue:{principal.user_id}:{project_id}",
                key=body.idempotency_key,
                request_digest=sha256_digest(body.model_dump(mode="json")),
            )
        except IdempotencyConflictError:
            raise ApiProblemError(
                409, "run.idempotency_conflict", "Idempotency key content changed"
            ) from None
        if not fresh:
            return RunView.model_validate(record.response_json)
        version = await session.scalar(
            select(WorkflowVersionModel)
            .join(
                WorkflowTemplateModel,
                WorkflowVersionModel.workflow_template_id == WorkflowTemplateModel.id,
            )
            .where(
                WorkflowVersionModel.id == body.workflow_version_id,
                WorkflowVersionModel.published_at.is_not(None),
                WorkflowTemplateModel.owner_user_id == principal.user_id,
                WorkflowTemplateModel.archived_at.is_(None),
            )
        )
        if version is None:
            raise missing()
        workflows = cast(WorkflowService, request.app.state.workflow_service)
        spec = WorkflowSpec.model_validate(version.spec_json)
        report, _spec, snapshot = await workflows._evaluate(
            session, spec.model_dump(mode="json", by_alias=True), version.layout_json
        )
        if not report.valid or snapshot is None or snapshot.snapshot_hash != version.snapshot_hash:
            raise ApiProblemError(
                422, "run.configuration_invalid", "Published workflow configuration is unavailable"
            )
        payload = {"snapshot": snapshot.model_dump(mode="json")}
        digest = sha256_digest(
            {"version_id": str(version.id), "snapshot": snapshot.model_dump(mode="json")}
        )
        stored = await session.scalar(
            select(RunConfigSnapshotModel).where(RunConfigSnapshotModel.snapshot_hash == digest)
        )
        if stored is None:
            stored = RunConfigSnapshotModel(
                id=uuid7(),
                workflow_version_id=version.id,
                schema_version="1.0",
                resolved_revisions_json=[
                    revision.model_dump(mode="json") for revision in snapshot.revisions
                ],
                effective_spec_json=payload,
                snapshot_hash=digest,
            )
            session.add(stored)
            await session.flush()
        job = JobModel(id=uuid7(), project_id=project_id, objective=body.objective, status="queued")
        session.add(job)
        await session.flush()
        identifier = uuid7()
        run = RunModel(
            id=identifier,
            job_id=job.id,
            run_number=1,
            workflow_version_id=version.id,
            config_snapshot_id=stored.id,
            langgraph_thread_id=str(identifier),
            status="queued",
            desired_state="running",
            priority=body.priority,
            mode=body.mode,
            claimable_at=ownership.clock.now(),
            runtime_json={},
        )
        session.add(run)
        await session.flush()
        await ownership.event(session, run, "job.created", {"actor_id": str(principal.user_id)})
        await ownership.event(session, run, "run.queued", {"actor_id": str(principal.user_id)})
        view = run_view(run, job)
        record.state, record.response_status, record.response_json = (
            "completed",
            202,
            view.model_dump(mode="json"),
        )
        return view


@router.get("/runs", response_model=RunPage)
async def runs(
    request: Request, principal: CurrentPrincipal, after: UUID | None = None, limit: Limit = 50
) -> RunPage:
    async with sessions(request, principal)() as session:
        query = (
            select(RunModel, JobModel)
            .join(JobModel)
            .join(ProjectModel)
            .where(ProjectModel.owner_user_id == principal.user_id)
        )
        if after:
            query = query.where(RunModel.id > after)
        rows = (await session.execute(query.order_by(RunModel.id).limit(limit + 1))).all()
        return RunPage(
            items=tuple(run_view(run, job) for run, job in rows[:limit]),
            next_after=rows[limit - 1][0].id if len(rows) > limit else None,
        )


@router.get("/runs/{run_id}", response_model=RunView)
async def get_run(request: Request, run_id: UUID, principal: CurrentPrincipal) -> RunView:
    async with sessions(request, principal)() as session:
        row = (
            await session.execute(
                select(RunModel, JobModel)
                .join(JobModel)
                .join(ProjectModel)
                .where(RunModel.id == run_id, ProjectModel.owner_user_id == principal.user_id)
            )
        ).one_or_none()
        if row is None:
            raise missing()
        return run_view(*row)


@router.get("/jobs", response_model=JobPage)
async def jobs(
    request: Request, principal: CurrentPrincipal, after: UUID | None = None, limit: Limit = 50
) -> JobPage:
    async with sessions(request, principal)() as session:
        query = (
            select(JobModel)
            .join(ProjectModel)
            .where(ProjectModel.owner_user_id == principal.user_id)
        )
        if after:
            query = query.where(JobModel.id > after)
        rows = list((await session.scalars(query.order_by(JobModel.id).limit(limit + 1))).all())
        return JobPage(
            items=tuple(
                JobView(
                    id=row.id, project_id=row.project_id, objective=row.objective, status=row.status
                )
                for row in rows[:limit]
            ),
            next_after=rows[limit - 1].id if len(rows) > limit else None,
        )


@router.get("/jobs/{job_id}", response_model=JobView)
async def get_job(request: Request, job_id: UUID, principal: CurrentPrincipal) -> JobView:
    async with sessions(request, principal)() as session:
        row = await session.scalar(
            select(JobModel)
            .join(ProjectModel)
            .where(JobModel.id == job_id, ProjectModel.owner_user_id == principal.user_id)
        )
        if row is None:
            raise missing()
        return JobView(
            id=row.id, project_id=row.project_id, objective=row.objective, status=row.status
        )


@router.post("/runs/{run_id}/commands", response_model=RunCommandReceipt, status_code=202)
async def control(
    request: Request, run_id: UUID, body: RunControl, principal: CsrfPrincipal
) -> RunCommandReceipt:
    _safe_strings(body.model_dump(mode="json"))
    factory = sessions(request, principal)
    async with factory.begin() as session:
        await lock_events(session)
        run = await session.scalar(
            select(RunModel)
            .join(JobModel)
            .join(ProjectModel)
            .where(RunModel.id == run_id, ProjectModel.owner_user_id == principal.user_id)
        )
        if run is None:
            raise missing()
        try:
            receipt = await CommandRepository().enqueue(
                session,
                RunCommandRequest(
                    run_id=run_id,
                    kind=body.kind,
                    idempotency_key=body.idempotency_key,
                    expected_run_version=body.expected_run_version,
                    payload={
                        "actor_id": str(principal.user_id),
                        **({"instruction": body.instruction} if body.instruction else {}),
                    },
                ),
            )
        except (IdempotencyConflictError, OptimisticConcurrencyConflictError):
            raise ApiProblemError(
                409, "run.command_conflict", "Run version or idempotency key changed"
            ) from None
        if not receipt.duplicate:
            run.version += 1
            await RunOwnership(factory, owner="control-api").event(
                session,
                run,
                "run.command_requested",
                {
                    "command_id": str(receipt.command_id),
                    "kind": body.kind.value,
                    "sequence": receipt.sequence,
                    "actor_id": str(principal.user_id),
                },
            )
        return receipt


@router.get("/runs/{run_id}/commands", response_model=CommandPage)
async def get_commands(
    request: Request, run_id: UUID, principal: CurrentPrincipal, after: int = 0, limit: Limit = 50
) -> CommandPage:
    await get_run(request, run_id, principal)
    async with sessions(request, principal)() as session:
        rows = (
            await session.scalars(
                select(RunCommandModel)
                .where(RunCommandModel.run_id == run_id, RunCommandModel.sequence > after)
                .order_by(RunCommandModel.sequence)
                .limit(limit + 1)
            )
        ).all()
        return CommandPage(
            items=tuple(
                CommandView(
                    id=row.id,
                    sequence=row.sequence,
                    kind=row.kind,
                    status=row.status,
                    applied_at=row.applied_at,
                )
                for row in rows[:limit]
            ),
            next_after=rows[limit - 1].sequence if len(rows) > limit else None,
        )


@router.get("/runs/{run_id}/nodes", response_model=NodePage)
async def get_nodes(
    request: Request,
    run_id: UUID,
    principal: CurrentPrincipal,
    after: UUID | None = None,
    limit: Limit = 50,
) -> NodePage:
    await get_run(request, run_id, principal)
    async with sessions(request, principal)() as session:
        query = select(NodeExecutionModel).where(NodeExecutionModel.run_id == run_id)
        if after:
            query = query.where(NodeExecutionModel.id > after)
        rows = (await session.scalars(query.order_by(NodeExecutionModel.id).limit(limit + 1))).all()
        return NodePage(
            items=tuple(
                NodeView(
                    id=row.id,
                    workflow_node_id=row.workflow_node_id,
                    execution_number=row.execution_number,
                    status=row.status,
                    task_id=row.task_id,
                    task_attempt_id=row.task_attempt_id,
                    started_at=row.started_at,
                    completed_at=row.completed_at,
                )
                for row in rows[:limit]
            ),
            next_after=rows[limit - 1].id if len(rows) > limit else None,
        )
