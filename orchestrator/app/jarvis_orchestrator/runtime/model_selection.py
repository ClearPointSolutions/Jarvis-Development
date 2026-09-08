"""M3 routing against the immutable M4 snapshot; no provider network access."""

from datetime import datetime
from uuid import UUID

from jarvis_api.routing.policies import resolve_route
from jarvis_contracts.enums import FailureClass
from jarvis_contracts.registry import (
    RegistryRecord,
    RouteEvaluationData,
    RoutePreviewRequest,
    RouteRequirements,
)
from jarvis_orchestrator.workflows.factories import NodeContext


def select_model(
    context: NodeContext, failed: tuple[UUID, ...], failure: FailureClass | None, now: datetime
) -> RouteEvaluationData:
    reference = context.policy.model_route_ref
    assert reference is not None
    records = {
        revision.revision_id: RegistryRecord(
            id=revision.configuration_id,
            revision_id=revision.revision_id,
            revision=revision.revision,
            version=revision.revision,
            key=revision.key,
            display_name=revision.display_name,
            description=revision.description,
            enabled=revision.enabled,
            archived=revision.archived,
            spec=revision.spec,
            content_hash=revision.content_hash,
            created_at=now,
            updated_at=now,
        )
        for revision in context.snapshot.revisions
    }
    request = RoutePreviewRequest(
        route_revision_id=reference,
        requirements=RouteRequirements(
            purpose="developer" if context.node.type.value == "worker" else context.node.type.value
        ),
        failed_profile_revision_ids=failed,
        failure_class=failure,
    )
    resolution = resolve_route(request, records[reference], records)
    return RouteEvaluationData(**resolution.model_dump(), request=request, observed_state=())
