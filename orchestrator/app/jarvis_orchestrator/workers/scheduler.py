"""Deterministic Phase 4 worker-pool eligibility and fairness policy.

The eligible list is frozen by the caller. Live state may only remove a worker;
it can never add one to an active assignment snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID


@dataclass(frozen=True)
class EligibleWorker:
    revision_id: UUID
    physical_resource_id: str
    capabilities: frozenset[str]
    permitted_project_ids: frozenset[UUID]
    execution_profile_ids: frozenset[UUID]
    capacity: int
    slots_in_use: int
    health: str
    observed_at: datetime | None
    enabled: bool = True


@dataclass(frozen=True)
class AssignmentRequest:
    id: UUID
    mission_id: UUID
    priority: int
    fairness_sequence: int
    project_id: UUID
    required_capabilities: frozenset[str]
    execution_profile_ids: frozenset[UUID]
    health_freshness_seconds: int


def select_worker(
    request: AssignmentRequest,
    frozen_workers: tuple[EligibleWorker, ...],
    *,
    now: datetime,
    disabled_revision_ids: frozenset[UUID] = frozenset(),
    disabled_resource_ids: frozenset[str] = frozenset(),
    allow_saturated: bool = False,
) -> tuple[EligibleWorker | None, str]:
    """Select least-loaded eligible physical resource with stable tie breaking."""
    by_resource: dict[str, EligibleWorker] = {}
    for worker in frozen_workers:
        if (
            not worker.enabled
            or worker.revision_id in disabled_revision_ids
            or worker.physical_resource_id in disabled_resource_ids
        ):
            continue
        if worker.health != "healthy" or worker.observed_at is None:
            continue
        if now - worker.observed_at > timedelta(seconds=request.health_freshness_seconds):
            continue
        if worker.permitted_project_ids and request.project_id not in worker.permitted_project_ids:
            continue
        if not request.required_capabilities <= worker.capabilities:
            continue
        if not request.execution_profile_ids <= worker.execution_profile_ids:
            continue
        if not allow_saturated and worker.slots_in_use >= worker.capacity:
            continue
        existing = by_resource.get(worker.physical_resource_id)
        if existing is None or worker.revision_id.int < existing.revision_id.int:
            by_resource[worker.physical_resource_id] = worker
    eligible = list(by_resource.values())
    if not eligible:
        return None, "waiting_for_eligible_worker_capacity"
    selected = min(
        eligible,
        key=lambda worker: (
            worker.slots_in_use / worker.capacity,
            worker.physical_resource_id,
            worker.revision_id.int,
        ),
    )
    return selected, "selected"


def fair_order(
    assignments: tuple[AssignmentRequest, ...], last_served: dict[UUID, int]
) -> tuple[AssignmentRequest, ...]:
    """Mission round-robin with priority and monotonic age starvation protection."""
    return tuple(
        sorted(
            assignments,
            key=lambda item: (
                last_served.get(item.mission_id, -1),
                -item.priority,
                item.fairness_sequence,
                item.id.int,
            ),
        )
    )


def effective_tools(
    role_allowed: frozenset[str],
    mission_allowed: frozenset[str],
    worker_capabilities: frozenset[str],
    security_allowed: frozenset[str],
    security_denied: frozenset[str] = frozenset(),
) -> frozenset[str]:
    """Fail-closed capability intersection used at the dispatch/tool boundary."""
    return (
        role_allowed & mission_allowed & worker_capabilities & security_allowed
    ) - security_denied
