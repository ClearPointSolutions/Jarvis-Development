"""DATA-002 real M3 revision closure, retirement policy, and historical binding."""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from uuid6 import uuid7

from jarvis_contracts.workflow import WorkflowSpec
from jarvis_contracts.workflow_api import WorkflowResolvedSnapshot
from jarvis_orchestrator.workflows import compile_workflow
from jarvis_persistence.models import (
    RunConfigSnapshotModel,
    RunModel,
    WorkflowRevisionReferenceModel,
    WorkflowVersionModel,
)
from tests.integration.support import seed_run
from tests.integration.test_m2_integrated_api import IntegratedApi
from tests.integration.test_m2_integrated_api import integrated_api as integrated_api
from tests.integration.test_m4_workflow_api import ROOT, command, create

pytestmark = pytest.mark.integration


async def test_snapshot_pins_full_registry_closure_and_historical_run(
    integrated_api: IntegratedApi, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    api = integrated_api
    headers, doc = await create(api)

    async def registry(spec: dict[str, Any]) -> dict[str, Any]:
        result = await api.client.post(
            f"/api/v1/registry/{spec['kind']}",
            headers=headers,
            json={
                "key": f"snapshot-{uuid7().hex}",
                "display_name": "Snapshot fixture",
                "idempotency_key": str(uuid7()),
                "spec": spec,
            },
        )
        assert result.status_code == 200, result.text
        return dict(result.json())

    provider = await registry({"kind": "provider_connection", "provider_kind": "demo"})
    model = await registry(
        {
            "kind": "model_profile",
            "provider_revision_id": provider["revision_id"],
            "model_identifier": "fixture-model",
            "purposes": ["organizer"],
            "context_limit": 4096,
            "output_limit": 1024,
        }
    )
    route = await registry(
        {
            "kind": "route_policy",
            "candidates": [{"profile_revision_id": model["revision_id"]}],
            "purposes": ["organizer"],
        }
    )
    retry = await registry({"kind": "retry_policy", "rules": []})
    permission = await registry({"kind": "permission_policy"})
    spec = deepcopy(doc["version"]["spec"])
    spec["entrypoint"] = "organize"
    spec["nodes"].insert(
        0,
        {
            "id": "organize",
            "type": "organizer",
            "label": "Organizer",
            "config": {},
            "policy": {
                "model_route_ref": route["revision_id"],
                "retry_policy_ref": retry["revision_id"],
                "permission_policy_ref": permission["revision_id"],
                "timeout_seconds": 300,
            },
        },
    )
    spec["edges"] = [{"id": "next", "from": "organize", "to": "finish", "kind": "always"}]
    path = f"{ROOT}/{doc['template']['id']}"
    response = await api.client.put(
        f"{path}/draft", json={**command(doc), "spec": spec}, headers=headers
    )
    assert response.status_code == 200, response.text
    doc = response.json()
    response = await api.client.post(f"{path}/publish", json=command(doc), headers=headers)
    assert response.status_code == 200, response.text
    published = response.json()
    version_id = UUID(published["version"]["id"])
    async with session_factory() as session:
        version = await session.get(WorkflowVersionModel, version_id)
        assert version and version.resolved_snapshot_json
        snapshot_json = deepcopy(version.resolved_snapshot_json)
        snapshot = WorkflowResolvedSnapshot.model_validate(snapshot_json)
        assert {r.revision_id for r in snapshot.revisions} == {
            UUID(r["revision_id"]) for r in (provider, model, route, retry, permission)
        }
        assert (
            len(
                list(
                    await session.scalars(
                        select(WorkflowRevisionReferenceModel).where(
                            WorkflowRevisionReferenceModel.workflow_version_id == version_id
                        )
                    )
                )
            )
            == 5
        )
    # A preexisting run is pointed at this immutable version/snapshot only in this fixture.
    # No application enqueue/claim endpoint or M5 scheduling behavior is introduced.
    run = await seed_run(session_factory)
    async with session_factory.begin() as session:
        pinned = RunConfigSnapshotModel(
            id=uuid7(),
            workflow_version_id=version_id,
            schema_version="1.0",
            resolved_revisions_json=[r.model_dump(mode="json") for r in snapshot.revisions],
            effective_spec_json=snapshot_json,
            snapshot_hash=snapshot.snapshot_hash,
        )
        session.add(pinned)
        await session.flush()
        active = await session.get(RunModel, run.run_id)
        assert active
        active.workflow_version_id = version_id
        active.config_snapshot_id = pinned.id
    # Retirement vetoes NEW publication, but cannot rewrite old bindings/semantics.
    response = await api.client.put(
        f"/api/v1/registry/provider_connection/{provider['id']}",
        headers=headers,
        json={
            "key": provider["key"],
            "display_name": provider["display_name"],
            "idempotency_key": str(uuid7()),
            "expected_version": provider["version"],
            "enabled": False,
            "spec": provider["spec"],
        },
    )
    assert response.status_code == 200, response.text
    response = await api.client.post(f"{path}/draft", json=command(published), headers=headers)
    assert response.status_code == 200, response.text
    draft = response.json()
    response = await api.client.post(f"{path}/publish", json=command(draft), headers=headers)
    assert response.status_code == 422
    assert any(
        i["node_id"] == "organize"
        for i in response.json()["error"]["details"]["validation"]["issues"]
    )
    old = (await api.client.get(f"{path}/versions/{version_id}")).json()["version"]
    assert old == published["version"]
    compile_workflow(WorkflowSpec.model_validate(old["spec"]), snapshot)
    async with session_factory() as session:
        active = await session.get(RunModel, run.run_id)
        stored = await session.get(RunConfigSnapshotModel, pinned.id)
        assert active and stored and active.workflow_version_id == version_id
        assert (
            active.config_snapshot_id == pinned.id
            and stored.snapshot_hash == snapshot.snapshot_hash
        )
        assert stored.effective_spec_json == snapshot_json
    for sql in (
        "UPDATE control.workflow_revision_references SET revision_id=:revision "
        "WHERE workflow_version_id=:version",
        "DELETE FROM control.workflow_revision_references WHERE workflow_version_id=:version",
        "INSERT INTO control.workflow_revision_references(workflow_version_id,revision_id) "
        "VALUES (:version,:revision)",
    ):
        with pytest.raises(DBAPIError):
            async with session_factory.begin() as session:
                await session.execute(
                    text(sql), {"version": version_id, "revision": UUID(provider["revision_id"])}
                )


async def test_uuid_kind_injection_and_disabled_reference_fail_before_publish(
    integrated_api: IntegratedApi,
) -> None:
    api = integrated_api
    headers, doc = await create(api)
    path = f"{ROOT}/{doc['template']['id']}"
    spec = deepcopy(doc["version"]["spec"])
    spec["nodes"][0]["policy"] = {"retry_policy_ref": str(uuid7())}
    response = await api.client.post(
        f"{path}/validate", json={**command(doc), "spec": spec}, headers=headers
    )
    assert response.status_code == 200 and not response.json()["valid"]
    assert any(
        i["node_id"] == "finish" and i["code"].startswith("reference.")
        for i in response.json()["issues"]
    )
