"""`jarvis-admin runtime build --check-registry` against a published workflow.

The check surfaces, at manifest-build time, the same model/worker invariants
RealComposition enforces at orchestrator startup: the worker node's selector
must match the binding, and every planning node's immutable retry policy must
cover the provider/infrastructure failure classes and route a structured-JSON
profile.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from uuid6 import uuid7

from jarvis_contracts.base import sha256_digest
from jarvis_contracts.enums import FailureClass
from jarvis_contracts.failures import RetryRule
from jarvis_contracts.registry import (
    ModelProfileSpec,
    PermissionPolicySpec,
    ProviderSpec,
    RetryRegistrySpec,
    RouteCandidate,
    RoutePolicySpec,
    WorkerSpec,
)
from jarvis_contracts.workflow import NodePolicy, WorkerSelector
from jarvis_orchestrator import admin
from jarvis_orchestrator.admin import REQUIRED_MODEL_RETRY_CLASSES
from jarvis_persistence.models import WorkflowVersionModel
from tests.integration.support import NOW, seed_run
from tests.unit.test_m4_workflows_compiler import (
    edge,
    node,
    resolved_revision,
    snapshot_for,
    spec_for,
)

pytestmark = pytest.mark.integration


@dataclass(frozen=True)
class Published:
    workflow_version_id: UUID
    worker_revision_id: UUID


def _binding(worker_revision_id: UUID, workflow_version_id: UUID) -> admin.ManifestBinding:
    project = uuid4()
    return admin.ManifestBinding.model_validate(
        {
            "project_id": str(project),
            "workflow_version_id": str(workflow_version_id),
            "worker_revision_id": str(worker_revision_id),
            "worker_project": {
                "project_id": str(project),
                "repository_id": str(uuid4()),
                "slug": "acceptance-app",
                "workspace_root": "/opt/jarvis-worker/workspaces/acceptance-app",
                "branch": "main",
                "base_sha": "a" * 40,
            },
            "combined_commands": [{"argv": ["python", "-m", "pytest", "-q"]}],
        }
    )


async def _publish(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    retry_classes: tuple[FailureClass, ...] = REQUIRED_MODEL_RETRY_CLASSES,
    structured_json: bool = True,
    published: bool = True,
) -> Published:
    provider = resolved_revision(
        ProviderSpec(provider_kind="ollama", base_url="http://ollama:11434")
    )
    profile = resolved_revision(
        ModelProfileSpec(
            provider_revision_id=provider.revision_id,
            model_identifier="gpt-oss:20b",
            purposes=("organizer", "architect", "reviewer"),
            capabilities=("chat",),
            context_limit=32_768,
            output_limit=4_096,
            structured_json=structured_json,
        )
    )
    route = resolved_revision(
        RoutePolicySpec(
            candidates=(RouteCandidate(profile_revision_id=profile.revision_id),),
            purposes=("organizer", "architect", "reviewer"),
            allow_unknown_health=True,
        )
    )
    retry = resolved_revision(
        RetryRegistrySpec(
            rules=tuple(
                RetryRule(failure_class=item, max_retries=1, exhaustion_action="fail")
                for item in retry_classes
            )
        )
    )
    permission = resolved_revision(
        PermissionPolicySpec(allowed_capabilities=("code", "git", "tests"))
    )
    worker = resolved_revision(WorkerSpec(capabilities=("code", "git", "tests"), max_concurrency=1))
    policy = NodePolicy(
        worker_selector=WorkerSelector(revision_id=worker.revision_id),
        model_route_ref=route.revision_id,
        retry_policy_ref=retry.revision_id,
        permission_policy_ref=permission.revision_id,
        timeout_seconds=30,
    )
    spec = spec_for(
        (
            node("organizer", "organizer"),
            node("arch", "architect"),
            node("work", "worker"),
            node("review", "reviewer"),
            node("done", "finalize"),
        ),
        (
            edge("organizer", "arch"),
            edge("arch", "work"),
            edge("work", "review"),
            edge("review", "done"),
        ),
        defaults=policy,
    )
    snapshot = snapshot_for(spec, provider, profile, route, retry, permission, worker)

    seeded = await seed_run(session_factory)
    version_id = uuid7()
    async with session_factory.begin() as session:
        template = await session.get(WorkflowVersionModel, seeded.workflow_version_id)
        assert template is not None
        session.add(
            WorkflowVersionModel(
                id=version_id,
                workflow_template_id=template.workflow_template_id,
                version=3,
                spec_version=spec.spec_version,
                compiler_version=snapshot.compiler_version,
                spec_json=spec.model_dump(mode="json", by_alias=True),
                layout_json={},
                content_hash=spec.content_hash,
                resolved_snapshot_json=snapshot.model_dump(mode="json", by_alias=True),
                snapshot_hash=sha256_digest({"v": str(version_id)}),
                published_at=NOW if published else None,
            )
        )
    return Published(version_id, worker.revision_id)


async def test_consistent_published_workflow_passes(
    database_url: str, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    pub = await _publish(session_factory)
    problems = await admin.check_registry(
        database_url, [_binding(pub.worker_revision_id, pub.workflow_version_id)]
    )
    assert problems == []


async def test_worker_selector_mismatch_is_reported(
    database_url: str, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    pub = await _publish(session_factory)
    problems = await admin.check_registry(
        database_url, [_binding(uuid4(), pub.workflow_version_id)]
    )
    assert any("worker node work selects" in item for item in problems)


async def test_missing_provider_retry_class_is_reported(
    database_url: str, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    pub = await _publish(
        session_factory,
        retry_classes=tuple(
            item
            for item in REQUIRED_MODEL_RETRY_CLASSES
            if item is not FailureClass.INFRASTRUCTURE_TIMEOUT
        ),
    )
    problems = await admin.check_registry(
        database_url, [_binding(pub.worker_revision_id, pub.workflow_version_id)]
    )
    assert any("infrastructure.timeout" in item and "no retries" in item for item in problems)


async def test_non_structured_profile_is_reported(
    database_url: str, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    pub = await _publish(session_factory, structured_json=False)
    problems = await admin.check_registry(
        database_url, [_binding(pub.worker_revision_id, pub.workflow_version_id)]
    )
    assert any("not a structured-JSON planning profile" in item for item in problems)


async def test_unpublished_and_unknown_versions_are_reported(
    database_url: str, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    pub = await _publish(session_factory, published=False)
    problems = await admin.check_registry(
        database_url, [_binding(pub.worker_revision_id, pub.workflow_version_id)]
    )
    assert any("not published" in item for item in problems)

    absent = await admin.check_registry(database_url, [_binding(uuid4(), uuid4())])
    assert any("no such workflow version" in item for item in absent)
