from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError
from uuid6 import uuid7

from jarvis_contracts.registry import TeamMemberSpec, TeamTemplateSpec, WorkerPoolSpec
from jarvis_orchestrator.workers.scheduler import (
    AssignmentRequest,
    EligibleWorker,
    effective_tools,
    fair_order,
    select_worker,
)


def request(
    *, mission_id: UUID | None = None, priority: int = 0, sequence: int = 1
) -> AssignmentRequest:
    return AssignmentRequest(
        id=uuid7(),
        mission_id=mission_id or uuid7(),
        priority=priority,
        fairness_sequence=sequence,
        project_id=PROJECT,
        required_capabilities=frozenset({"code", "git"}),
        execution_profile_ids=frozenset({PROFILE}),
        health_freshness_seconds=60,
    )


PROJECT, PROFILE = uuid7(), uuid7()
NOW = datetime(2026, 9, 15, tzinfo=UTC)


def worker(
    *,
    resource: str = "host-a",
    revision: UUID | None = None,
    used: int = 0,
    health: str = "healthy",
) -> EligibleWorker:
    return EligibleWorker(
        revision_id=revision or uuid7(),
        physical_resource_id=resource,
        capabilities=frozenset({"code", "git"}),
        permitted_project_ids=frozenset({PROJECT}),
        execution_profile_ids=frozenset({PROFILE}),
        capacity=1,
        slots_in_use=used,
        health=health,
        observed_at=NOW,
    )


def test_duplicate_physical_registration_does_not_multiply_capacity() -> None:
    first, second = worker(resource="same-host"), worker(resource="same-host")
    selected, reason = select_worker(request(), (first, second), now=NOW)
    assert reason == "selected"
    assert selected is not None
    assert selected.revision_id == min(
        first.revision_id, second.revision_id, key=lambda item: item.int
    )


def test_capacity_health_project_profile_and_live_veto_fail_closed() -> None:
    stale = worker()
    stale = EligibleWorker(**{**stale.__dict__, "observed_at": NOW - timedelta(seconds=61)})
    selected, reason = select_worker(request(), (stale,), now=NOW)
    assert selected is None and reason == "waiting_for_eligible_worker_capacity"
    fresh = worker(resource="host-b")
    selected, _ = select_worker(
        request(), (fresh,), now=NOW, disabled_resource_ids=frozenset({"host-b"})
    )
    assert selected is None


def test_fair_order_prevents_one_mission_from_monopolizing_queue() -> None:
    old_mission, recently_served = uuid7(), uuid7()
    old = request(mission_id=old_mission, priority=0, sequence=4)
    urgent = request(mission_id=recently_served, priority=100, sequence=1)
    assert fair_order((urgent, old), {old_mission: 2, recently_served: 9})[0] == old


def test_custom_team_requires_separate_protected_reviewer() -> None:
    member = dict(
        key="developer",
        role_revision_id=uuid7(),
        model_route_revision_id=uuid7(),
        worker_pool_revision_ids=(uuid7(),),
        permission_policy_revision_id=uuid7(),
        allowed_tools=("code", "git"),
    )
    with pytest.raises(ValidationError, match="cannot execute"):
        TeamMemberSpec(**member, may_review=True, may_execute=True)
    with pytest.raises(ValidationError, match="independent reviewer"):
        TeamTemplateSpec(
            mode="demo",
            manager_role_revision_id=uuid7(),
            manager_profile_revision_id=uuid7(),
            developer_role_revision_id=uuid7(),
            developer_worker_revision_id=uuid7(),
            reviewer_role_revision_id=uuid7(),
            reviewer_profile_revision_id=uuid7(),
            workflow_version_id=uuid7(),
            members=(TeamMemberSpec(**member),),
        )


def test_worker_pool_is_an_immutable_unique_allowlist() -> None:
    worker_id = uuid7()
    with pytest.raises(ValidationError, match="unique"):
        WorkerPoolSpec(worker_revision_ids=(worker_id, worker_id))


def test_tool_authority_is_the_fail_closed_policy_intersection() -> None:
    assert effective_tools(
        frozenset({"code", "git", "network"}),
        frozenset({"code", "git"}),
        frozenset({"code", "git", "docker"}),
        frozenset({"code", "git", "network"}),
        frozenset({"git"}),
    ) == frozenset({"code"})
