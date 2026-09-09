"""Owner/CSRF protected decisions; API only queues same-thread resumption."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Request
from sqlalchemy import select

from jarvis_api.auth.dependencies import CsrfPrincipal, CurrentPrincipal
from jarvis_api.errors import ApiProblemError
from jarvis_api.runtime import get_run, missing, sessions
from jarvis_contracts.approvals import ApprovalDecisionRequest, ApprovalPage, ApprovalView
from jarvis_contracts.base import sha256_digest
from jarvis_orchestrator.runtime.approvals import validate_request_event
from jarvis_orchestrator.runtime.ownership import RunOwnership, lock_events
from jarvis_persistence.models import JobModel, ProjectModel, RunCommandModel, RunModel
from jarvis_persistence.repositories import IdempotencyConflictError, IdempotencyRepository

router = APIRouter(prefix="/api/v1", tags=["approvals"])


@router.get("/runs/{run_id}/approvals", response_model=ApprovalPage)
async def approvals(request: Request, run_id: UUID, principal: CurrentPrincipal) -> ApprovalPage:
    await get_run(request, run_id, principal)
    async with sessions(request, principal)() as session:
        run = await session.get(RunModel, run_id)
        assert run is not None
        return ApprovalPage(
            items=tuple(
                ApprovalView.model_validate(item)
                for item in run.runtime_json.get("approvals", {}).values()
            )
        )


@router.post(
    "/runs/{run_id}/approvals/{approval_id}/decisions", response_model=ApprovalView, status_code=202
)
async def decide(
    request: Request,
    run_id: UUID,
    approval_id: UUID,
    body: ApprovalDecisionRequest,
    principal: CsrfPrincipal,
) -> ApprovalView:
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
            .with_for_update()
        )
        if run is None or run.mode != "real":
            raise missing()
        stored = run.runtime_json.get("approvals", {}).get(str(approval_id))
        if stored is None:
            raise missing()
        try:
            record, fresh = await IdempotencyRepository().begin(
                session,
                scope=f"approval:{principal.user_id}:{approval_id}",
                key=body.idempotency_key,
                request_digest=sha256_digest(body),
            )
        except IdempotencyConflictError:
            raise ApiProblemError(409, "approval.conflict", "Decision request changed") from None
        if not fresh:
            return ApprovalView.model_validate(record.response_json)
        approval = ApprovalView.model_validate(stored)
        try:
            await validate_request_event(session, approval)
        except ValueError:
            raise ApiProblemError(
                409, "approval.invalid", "Approval request is no longer valid"
            ) from None
        pending = await session.scalar(
            select(RunCommandModel.id)
            .where(
                RunCommandModel.run_id == run_id,
                RunCommandModel.status == "pending",
            )
            .limit(1)
        )
        now = datetime.now(UTC)
        if (
            approval.run_id != run_id
            or approval.decision != "pending"
            or approval.request_digest != body.request_digest
            or run.status != "approval_required"
            or run.desired_state != "running"
            or run.version != body.expected_run_version
            or pending is not None
            or run.runtime_json.get("wait") != {"kind": "approval", "id": str(approval_id)}
            or (approval.expires_at is not None and approval.expires_at <= now)
        ):
            raise ApiProblemError(409, "approval.stale", "Approval wait has changed or expired")
        decided = approval.model_copy(
            update={
                "decision": body.decision,
                "actor_id": principal.user_id,
                "decided_at": now,
            }
        )
        run.runtime_json = {
            **run.runtime_json,
            "approvals": {
                **run.runtime_json["approvals"],
                str(approval_id): decided.model_dump(mode="json"),
            },
        }
        run.status, run.claimable_at = "queued", now
        run.version += 1
        await RunOwnership(factory, owner="control-api").event(
            session,
            run,
            "approval.decided",
            {
                "approval_id": str(approval_id),
                "decision": body.decision,
                "request_digest": approval.request_digest,
                "actor_id": str(principal.user_id),
                "session_id": str(principal.session_id),
            },
        )
        record.state, record.response_status, record.response_json = (
            "completed",
            202,
            decided.model_dump(mode="json"),
        )
        return decided
