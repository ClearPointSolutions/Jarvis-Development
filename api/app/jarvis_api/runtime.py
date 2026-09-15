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
from jarvis_contracts.demo import AttemptView, DemoDecision, DemoDecisionView, TaskPage, TaskView
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
    RunReconciliationReceipt,
    RunReconciliationRequest,
    RunView,
)
from jarvis_contracts.verification import (
    ExecutionProfileTemplatePage,
    IntegrationHeadPage,
    IntegrationHeadView,
)
from jarvis_contracts.workflow import WorkflowSpec
from jarvis_orchestrator.demo.safety import validate_demo_snapshot
from jarvis_orchestrator.runtime.ownership import RunOwnership, lock_events, runtime_writer
from jarvis_orchestrator.verification.profiles import profile_templates
from jarvis_orchestrator.workflows.validation import effective_policy
from jarvis_persistence.models import (
    ConfigurationModel,
    ConfigurationRevisionModel,
    EffectModel,
    IntegrationHeadModel,
    JobModel,
    NodeExecutionModel,
    ProjectModel,
    RunCommandModel,
    RunConfigSnapshotModel,
    RunModel,
    TaskAttemptModel,
    TaskDependencyModel,
    TaskModel,
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


@router.get("/execution-profiles/templates", response_model=ExecutionProfileTemplatePage)
async def execution_profile_templates(
    principal: CurrentPrincipal,
) -> ExecutionProfileTemplatePage:
    del principal
    return ExecutionProfileTemplatePage(items=profile_templates())


@router.get("/runs/{run_id}/workflow", response_model=WorkflowSpec)
async def run_workflow(request: Request, run_id: UUID, principal: CurrentPrincipal) -> WorkflowSpec:
    view = await get_run(request, run_id, principal)
    async with sessions(request, principal)() as session:
        version = await session.get(WorkflowVersionModel, view.workflow_version_id)
        if version is None:
            raise missing()
        return WorkflowSpec.model_validate(version.spec_json)


@router.get("/runs/{run_id}/integration-heads", response_model=IntegrationHeadPage)
async def integration_heads(
    request: Request,
    run_id: UUID,
    principal: CurrentPrincipal,
    after: UUID | None = None,
    limit: Limit = 50,
) -> IntegrationHeadPage:
    await get_run(request, run_id, principal)
    async with sessions(request, principal)() as session:
        query = select(IntegrationHeadModel).where(IntegrationHeadModel.run_id == run_id)
        if after:
            query = query.where(IntegrationHeadModel.repository_id > after)
        rows = (
            await session.scalars(
                query.order_by(IntegrationHeadModel.repository_id).limit(limit + 1)
            )
        ).all()
        return IntegrationHeadPage(
            items=tuple(
                IntegrationHeadView(
                    repository_id=row.repository_id,
                    base_sha=row.base_sha,
                    head_sha=row.head_sha,
                    branch=row.branch,
                    snapshot_artifact_id=row.snapshot_artifact_id,
                    generation=row.generation,
                    lease_owner=row.lease_owner,
                    expires_at=row.expires_at,
                    released_at=row.released_at,
                )
                for row in rows[:limit]
            ),
            next_after=rows[limit - 1].repository_id if len(rows) > limit else None,
        )


@router.get("/runs/{run_id}/tasks", response_model=TaskPage)
async def run_tasks(
    request: Request,
    run_id: UUID,
    principal: CurrentPrincipal,
    after: UUID | None = None,
    limit: Limit = 50,
) -> TaskPage:
    await get_run(request, run_id, principal)
    async with sessions(request, principal)() as session:
        query = select(TaskModel).where(TaskModel.run_id == run_id)
        if after:
            query = query.where(TaskModel.id > after)
        rows = (await session.scalars(query.order_by(TaskModel.id).limit(limit + 1))).all()
        items = []
        for row in rows[:limit]:
            attempts = (
                await session.scalars(
                    select(TaskAttemptModel)
                    .where(
                        TaskAttemptModel.task_id == row.id,
                    )
                    .order_by(TaskAttemptModel.attempt_number)
                    .limit(100)
                )
            ).all()
            dependencies = (
                await session.scalars(
                    select(TaskDependencyModel.depends_on_task_id).where(
                        TaskDependencyModel.task_id == row.id,
                    )
                )
            ).all()
            items.append(
                TaskView(
                    id=row.id,
                    key=row.key,
                    title=row.title,
                    status=row.status,
                    weight=row.weight,
                    dependencies=tuple(dependencies),
                    attempts=tuple(
                        AttemptView(
                            id=a.id,
                            number=a.attempt_number,
                            status=a.status,
                            snapshot_digest=a.result_sha,
                        )
                        for a in attempts
                    ),
                )
            )
        return TaskPage(
            items=tuple(items), next_after=rows[limit - 1].id if len(rows) > limit else None
        )


@router.get("/runs/{run_id}/demo-decision", response_model=DemoDecisionView | None)
async def get_demo_decision(
    request: Request,
    run_id: UUID,
    principal: CurrentPrincipal,
) -> DemoDecisionView | None:
    await get_run(request, run_id, principal)
    async with sessions(request, principal)() as session:
        run = await session.get(RunModel, run_id)
        assert run is not None
        value = run.runtime_json.get("demo_decision")
        return DemoDecisionView(id=value["id"], decision=value["decision"]) if value else None


@router.post("/runs/{run_id}/demo-decision", response_model=DemoDecisionView, status_code=202)
async def submit_demo_decision(
    request: Request,
    run_id: UUID,
    body: DemoDecision,
    principal: CsrfPrincipal,
) -> DemoDecisionView:
    factory = sessions(request, principal)
    async with factory.begin() as session:
        await lock_events(session)
        run = await session.scalar(
            select(RunModel)
            .join(JobModel)
            .join(ProjectModel)
            .where(
                RunModel.id == run_id,
                ProjectModel.owner_user_id == principal.user_id,
            )
        )
        if run is None or run.mode != "demo":
            raise missing()
        try:
            record, fresh = await IdempotencyRepository().begin(
                session,
                scope=f"demo-decision:{principal.user_id}:{run_id}",
                key=body.idempotency_key,
                request_digest=sha256_digest(body),
            )
        except IdempotencyConflictError:
            raise ApiProblemError(409, "demo.conflict", "Decision identity changed") from None
        if not fresh:
            return DemoDecisionView.model_validate(record.response_json)
        decision = run.runtime_json.get("demo_decision", {})
        pending_command = await session.scalar(
            select(RunCommandModel.id)
            .where(
                RunCommandModel.run_id == run_id,
                RunCommandModel.status == "pending",
            )
            .limit(1)
        )
        if (
            run.status != "approval_required"
            or run.desired_state != "running"
            or run.version != body.expected_run_version
            or decision.get("id") != body.decision_id
            or decision.get("decision") != "pending"
            or pending_command is not None
        ):
            raise ApiProblemError(409, "demo.conflict", "Demo wait is no longer current")
        run.runtime_json = {
            **run.runtime_json,
            "demo_decision": {
                **decision,
                "decision": body.decision,
                "actor_id": str(principal.user_id),
            },
        }
        run.status = "queued"
        run.claimable_at = datetime.now(UTC)
        run.version += 1
        await RunOwnership(factory, owner="control-api").event(
            session,
            run,
            "approval.decided",
            {
                "decision": body.decision,
                "decision_id": body.decision_id,
                "actor_id": str(principal.user_id),
                "summary": "DEMO decision only",
            },
        )
        view = DemoDecisionView(id=body.decision_id, decision=body.decision)
        record.state, record.response_status, record.response_json = (
            "completed",
            202,
            view.model_dump(mode="json"),
        )
        return view


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
                ProjectView(
                    id=row.id,
                    slug=row.slug,
                    name=row.name,
                    project_type=row.project_type,
                    execution_profile_revision_ids=tuple(
                        UUID(value) for value in row.execution_profile_revision_ids_json
                    ),
                )
                for row in rows[:limit]
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
        if body.execution_profile_revision_ids:
            configured = set(
                await session.scalars(
                    select(ConfigurationRevisionModel.id)
                    .join(
                        ConfigurationModel,
                        ConfigurationModel.id == ConfigurationRevisionModel.configuration_id,
                    )
                    .where(
                        ConfigurationRevisionModel.id.in_(body.execution_profile_revision_ids),
                        ConfigurationModel.kind == "execution_profile",
                        ConfigurationModel.enabled.is_(True),
                        ConfigurationModel.archived_at.is_(None),
                    )
                )
            )
            if configured != set(body.execution_profile_revision_ids):
                raise ApiProblemError(
                    422,
                    "project.execution_profile_invalid",
                    "Project references a missing or inactive execution profile revision",
                )
        row = ProjectModel(
            id=uuid7(),
            owner_user_id=principal.user_id,
            slug=body.slug,
            name=body.name,
            project_type=body.project_type,
            execution_profile_revision_ids_json=[
                str(value) for value in body.execution_profile_revision_ids
            ],
            status="active",
        )
        session.add(row)
        await session.flush()
        view = ProjectView(
            id=row.id,
            slug=row.slug,
            name=row.name,
            project_type=row.project_type,
            execution_profile_revision_ids=body.execution_profile_revision_ids,
        )
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
        if body.mode == "real" and project.project_type != "python":
            policies = [
                effective_policy(spec, node).verification
                for node in spec.nodes
                if node.type.value == "verify"
            ]
            workflow_profiles = {
                revision_id
                for policy in policies
                if policy
                for revision_id in policy.execution_profile_revision_ids
            }
            project_profiles = {
                UUID(value) for value in project.execution_profile_revision_ids_json
            }
            if workflow_profiles != project_profiles:
                raise ApiProblemError(
                    422,
                    "run.execution_profile_mismatch",
                    "Workflow profiles must exactly match the project's approved revisions",
                )
            purposes = {
                check.purpose
                for policy in policies
                if policy
                for check in policy.required_acceptance_checks
            }
            missing_purposes = {"build", "unit", "browser"} - purposes
            if missing_purposes:
                raise ApiProblemError(
                    422,
                    "run.acceptance_checks_missing",
                    "Web project is missing approved required checks: "
                    + ", ".join(sorted(missing_purposes)),
                )
        payload = {"snapshot": snapshot.model_dump(mode="json")}
        if body.mode == "demo":
            try:
                validate_demo_snapshot(snapshot)
            except ValueError:
                raise ApiProblemError(
                    422, "run.demo_boundary", "Demo runs require demo adapters"
                ) from None
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
            runtime_json={"demo_fixture": body.demo_fixture.model_dump(mode="json")}
            if body.demo_fixture
            else {},
        )
        session.add(run)
        await session.flush()
        await ownership.event(session, run, "job.created", {"actor_id": str(principal.user_id)})
        await ownership.event(
            session,
            run,
            "message.created",
            {
                "role": "user",
                "body": body.objective,
                "actor_id": str(principal.user_id),
                "message_kind": "objective",
            },
        )
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
            if body.instruction:
                await RunOwnership(factory, owner="control-api").event(
                    session,
                    run,
                    "message.created",
                    {
                        "role": "user",
                        "body": body.instruction,
                        "actor_id": str(principal.user_id),
                        "command_id": str(receipt.command_id),
                        "message_kind": "instruction",
                    },
                )
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


@router.post(
    "/runs/{run_id}/reconciliation",
    response_model=RunReconciliationReceipt,
    status_code=202,
)
async def request_reconciliation(
    request: Request,
    run_id: UUID,
    body: RunReconciliationRequest,
    principal: CsrfPrincipal,
) -> RunReconciliationReceipt:
    """Requeue inspection of one existing ambiguous identity without replacing it."""

    factory = sessions(request, principal)
    async with factory.begin() as session:
        await lock_events(session)
        row = (
            await session.execute(
                select(RunModel, JobModel)
                .join(JobModel)
                .join(ProjectModel)
                .where(RunModel.id == run_id, ProjectModel.owner_user_id == principal.user_id)
                .with_for_update(of=RunModel)
            )
        ).one_or_none()
        if row is None:
            raise missing()
        run, job = row
        try:
            idem, fresh = await IdempotencyRepository().begin(
                session,
                scope=f"run:reconciliation:{run_id}",
                key=body.idempotency_key,
                request_digest=sha256_digest(body.model_dump(mode="json")),
            )
        except IdempotencyConflictError:
            raise ApiProblemError(
                409, "run.reconciliation_conflict", "Idempotency input changed"
            ) from None
        if not fresh:
            return RunReconciliationReceipt.model_validate(idem.response_json).model_copy(
                update={"duplicate": True}
            )
        if run.version != body.expected_run_version:
            raise ApiProblemError(409, "run.version_conflict", "Run changed; refresh and retry")
        effect = await session.scalar(
            select(EffectModel).where(
                EffectModel.id == body.effect_id,
                EffectModel.run_id == run.id,
            )
        )
        if effect is None:
            raise missing()
        if effect.status not in {"dispatched", "running", "cancel_requested", "unknown"}:
            raise ApiProblemError(
                409,
                "run.reconciliation_not_required",
                "Only a non-terminal external identity can be inspected",
            )
        queued = run.status == "blocked"
        if queued:
            run.status = "queued"
            job.status = "queued"
            run.current_node = None
            run.completed_at = None
            run.claimable_at = datetime.now(UTC)
            run.runtime_json = {**run.runtime_json, "recovering": True}
        run.version += 1
        await RunOwnership(factory, owner="control-api").event(
            session,
            run,
            "effect.reconciliation_requested",
            {
                "effect_id": str(effect.id),
                "effect_status": effect.status,
                "external_identity_present": effect.external_id is not None,
                "actor_id": str(principal.user_id),
                "queued_for_inspection": queued,
            },
        )
        receipt = RunReconciliationReceipt(
            run_id=run.id,
            effect_id=effect.id,
            effect_status=effect.status,
            queued_for_inspection=queued,
        )
        idem.state, idem.response_status, idem.response_json = (
            "completed",
            202,
            receipt.model_dump(mode="json"),
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
