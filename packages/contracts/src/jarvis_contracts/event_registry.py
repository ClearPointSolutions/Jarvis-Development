"""Central registry for normalized event type/category and payload contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import Field

from jarvis_contracts.base import ContractModel
from jarvis_contracts.enums import EventCategory
from jarvis_contracts.ids import SessionId, UserId
from jarvis_contracts.registry import ProviderHealthData, RegistryAuditData, RouteEvaluationData
from jarvis_contracts.workflow_api import WorkflowAuditData


class LoginSucceededData(ContractModel):
    user_id: UserId
    session_id: SessionId
    client_network: str = Field(min_length=1, max_length=96)


class LoginFailedData(ContractModel):
    subject_fingerprint: str = Field(min_length=16, max_length=64)
    outcome: Literal["invalid_credentials"] = "invalid_credentials"
    rate_limited: bool
    retry_after_seconds: int = Field(ge=0)


class LogoutData(ContractModel):
    user_id: UserId
    session_id: SessionId


class SessionRevokedData(ContractModel):
    user_id: UserId
    session_id: SessionId
    reason: str = Field(min_length=1, max_length=64)


class OwnerBootstrappedData(ContractModel):
    user_id: UserId
    migrated_project_count: int = Field(ge=0)


class SecurityDeniedData(ContractModel):
    reason: Literal[
        "invalid_host",
        "invalid_origin",
        "invalid_csrf",
        "invalid_content_type",
        "unauthenticated",
        "not_found",
        "request_too_large",
        "forbidden",
    ]
    user_id: UserId | None = None
    session_id: SessionId | None = None


class OwnerPasswordResetData(ContractModel):
    user_id: UserId
    revoked_session_count: int = Field(ge=0)


@dataclass(frozen=True)
class EventDefinition:
    category: EventCategory
    default_message: str
    payload_model: type[ContractModel] | None = None


_EVENT_NAMES_TEXT = """
approval.cancelled approval.decided approval.expired approval.requested approval.resume_queued
approval.resumed artifact.created artifact.unavailable artifact.verified command.completed
command.failed command.output_summary command.started command.timed_out config.created
config.revised
effect.prepared effect.dispatched effect.succeeded effect.cancel_requested
effect.cancelled effect.unknown
project.created
config.validated failure.classified file.created file.deleted file.read file.snapshot_created
file.write_completed file.write_started git.branch_created git.ci_updated git.commit_created
git.integration_completed git.integration_conflict git.integration_started git.pr_created
git.integration_lease_acquired git.integration_lease_renewed git.integration_lease_released
command.normalized
git.push_completed git.push_started graph.checkpointed graph.compile_failed graph.compiled
graph.fanout_started graph.join_completed graph.route_selected instruction.applied
instruction.queued job.blocked job.cancelled job.completed job.created job.failed job.status_changed
lease.expired message.created model.call_completed model.call_failed model.call_started
model.failover
model.health_changed model.route_selected model.stream_progress model.usage_recorded node.cancelled
node.failed node.interrupted node.queued node.skipped node.started node.succeeded node.waiting
orchestrator.heartbeat retry.budget_consumed retry.budget_exhausted review.completed review.failed
review.snapshot_invalidated review.started run.blocked run.cancel_requested run.cancelled
run.claimed run.configuration_bound
run.command_applied run.command_rejected run.command_requested run.completed run.failed
run.pause_requested run.paused run.queued run.recovered run.recovering run.resumed run.started
security.redaction_applied service.health_changed system.health_changed task.attempt_started
task.blocked
task.cancelled task.created task.delegated task.dependencies_set task.failed task.ready
task.retry_scheduled task.reviewing task.succeeded task.verifying test.completed test.failed
test.started
thread.created tool.completed tool.failed tool.started worker.cancel_requested worker.cancelled
worker.health_changed worker.heartbeat worker.invocation_completed worker.invocation_dispatched
worker.invocation_failed worker.lease_acquired worker.lease_lost workflow.published
"""
_EVENT_NAMES = _EVENT_NAMES_TEXT.split()

_PREFIX_CATEGORIES = {
    "approval": EventCategory.APPROVAL,
    "artifact": EventCategory.ARTIFACT,
    "command": EventCategory.COMMAND,
    "config": EventCategory.CONFIG,
    "effect": EventCategory.NODE,
    "project": EventCategory.CONFIG,
    "failure": EventCategory.FAILURE,
    "file": EventCategory.FILE,
    "git": EventCategory.GIT,
    "graph": EventCategory.GRAPH,
    "instruction": EventCategory.COMMAND,
    "job": EventCategory.JOB,
    "lease": EventCategory.SYSTEM,
    "message": EventCategory.THREAD,
    "model": EventCategory.MODEL,
    "node": EventCategory.NODE,
    "orchestrator": EventCategory.SYSTEM,
    "retry": EventCategory.FAILURE,
    "review": EventCategory.REVIEW,
    "run": EventCategory.RUN,
    "security": EventCategory.SYSTEM,
    "service": EventCategory.SYSTEM,
    "system": EventCategory.SYSTEM,
    "task": EventCategory.TASK,
    "test": EventCategory.TEST,
    "thread": EventCategory.THREAD,
    "tool": EventCategory.TOOL,
    "worker": EventCategory.WORKER,
    "workflow": EventCategory.CONFIG,
}


def _humanize(event_type: str) -> str:
    return event_type.replace(".", " ").replace("_", " ").capitalize()


EVENT_REGISTRY: dict[str, EventDefinition] = {
    name: EventDefinition(
        category=_PREFIX_CATEGORIES[name.partition(".")[0]],
        default_message=_humanize(name),
    )
    for name in _EVENT_NAMES
}
EVENT_REGISTRY.update(
    {
        "config.created": EventDefinition(
            EventCategory.CONFIG, "Configuration created", RegistryAuditData
        ),
        "config.revised": EventDefinition(
            EventCategory.CONFIG, "Configuration revised", RegistryAuditData
        ),
        "config.validated": EventDefinition(
            EventCategory.CONFIG, "Configuration validated", RegistryAuditData
        ),
        "model.health_changed": EventDefinition(
            EventCategory.MODEL, "Provider health changed", ProviderHealthData
        ),
        "model.route_selected": EventDefinition(
            EventCategory.MODEL, "Model route evaluated", RouteEvaluationData
        ),
        "auth.security_denied": EventDefinition(
            EventCategory.AUTH, "Security boundary denied request", SecurityDeniedData
        ),
        "auth.owner_password_reset": EventDefinition(
            EventCategory.AUTH, "Owner password reset locally", OwnerPasswordResetData
        ),
        "auth.login_succeeded": EventDefinition(
            EventCategory.AUTH, "Login succeeded", LoginSucceededData
        ),
        "auth.login_failed": EventDefinition(EventCategory.AUTH, "Login failed", LoginFailedData),
        "auth.logout": EventDefinition(EventCategory.AUTH, "Logout completed", LogoutData),
        "auth.session_revoked": EventDefinition(
            EventCategory.AUTH, "Session revoked", SessionRevokedData
        ),
        "auth.owner_bootstrapped": EventDefinition(
            EventCategory.AUTH, "Owner bootstrapped", OwnerBootstrappedData
        ),
    }
)


def event_definition(event_type: str) -> EventDefinition | None:
    return EVENT_REGISTRY.get(event_type)


for _action in ("created", "revised", "validated", "published", "archived", "restored"):
    EVENT_REGISTRY[f"workflow.{_action}"] = EventDefinition(
        EventCategory.CONFIG, f"Workflow {_action}", WorkflowAuditData
    )
