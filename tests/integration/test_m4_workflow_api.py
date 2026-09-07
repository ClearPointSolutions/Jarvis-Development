"""WF-004 and M4 security against real PostgreSQL and the least-privilege API."""

from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from uuid6 import uuid7

from jarvis_contracts.workflow_api import WorkflowResolvedSnapshot
from jarvis_persistence.models import EventModel, WorkflowVersionModel
from tests.integration.support import seed_run
from tests.integration.test_m2_integrated_api import IntegratedApi, login
from tests.integration.test_m2_integrated_api import integrated_api as integrated_api

pytestmark = pytest.mark.integration
ROOT = "/api/v1/workflow-templates"


@pytest.mark.parametrize("encoding", ["utf-16", "utf-16-be", "utf-32", "latin-1"])
async def test_m4_non_utf8_cannot_bypass_preparse_depth_limit(
    integrated_api: IntegratedApi, encoding: str
) -> None:
    headers, doc = await create(integrated_api)
    raw = json.dumps({"label": '"'})[:-1] + ',"spec":' + "[" * 20000 + "0" + "]" * 20000 + "}"
    content = raw.encode(encoding) if encoding != "latin-1" else b'{"label":"\xff"}'
    response = await integrated_api.client.post(
        f"{ROOT}/{doc['template']['id']}/validate",
        content=content,
        headers={**headers, "content-type": "application/json"},
    )
    assert response.status_code == 422 and response.json()["error"]["code"] == "workflow.encoding"


async def test_m4_inherited_boolean_policy_survives_save_and_idempotency(
    integrated_api: IntegratedApi,
) -> None:
    headers, doc = await create(integrated_api)
    path = f"{ROOT}/{doc['template']['id']}/draft"
    spec = deepcopy(doc["version"]["spec"])
    spec["defaults"] = {"accepts_runtime_instructions": True}
    spec["nodes"][0]["policy"] = {}
    body = {**command(doc), "spec": spec}
    response = await integrated_api.client.put(path, json=body, headers=headers)
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["version"]["spec"]["nodes"][0]["policy"]["accepts_runtime_instructions"] is True
    assert (await integrated_api.client.put(path, json=body, headers=headers)).json() == saved
    spec["nodes"][0]["policy"] = {"accepts_runtime_instructions": False}
    response = await integrated_api.client.put(path, json=body, headers=headers)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "workflow.idempotency_conflict"
    response = await integrated_api.client.put(
        path, json={**command(saved), "spec": spec}, headers=headers
    )
    assert response.status_code == 200, response.text
    assert (
        response.json()["version"]["spec"]["nodes"][0]["policy"]["accepts_runtime_instructions"]
        is False
    )


async def test_m4_raw_json_depth_is_bounded_before_recursive_parser(
    integrated_api: IntegratedApi,
) -> None:
    headers, doc = await create(integrated_api)
    path = f"{ROOT}/{doc['template']['id']}/validate"
    response = await integrated_api.client.post(
        path,
        content='{"spec":' + "[" * 2000 + "0" + "]" * 2000 + "}",
        headers={**headers, "content-type": "application/json"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "workflow.resource_limit"
    spec = deepcopy(doc["version"]["spec"])
    spec["nodes"][0]["label"] = '[{"quoted \\" brackets }]]' * 4
    response = await integrated_api.client.post(
        path,
        content=json.dumps({**command(doc), "spec": spec, "layout": {}}),
        headers={**headers, "content-type": "application/json"},
    )
    assert response.status_code == 200 and response.json()["valid"], response.text
    async with integrated_api.factory() as session:
        audit = await session.scalar(
            select(EventModel).where(
                EventModel.type == "workflow.validated",
                EventModel.data_json["template_id"].astext == doc["template"]["id"],
            )
        )
    assert audit and audit.data_json["content_hash"] == response.json()["content_hash"]
    assert audit.data_json["content_hash"] != doc["version"]["content_hash"]


async def create(api: IntegratedApi) -> tuple[dict[str, str], dict[str, Any]]:
    headers = {"x-csrf-token": (await login(api)).json()["csrf_token"]}
    body = {
        "key": f"workflow-{uuid7().hex}",
        "name": "Reviewable workflow",
        "idempotency_key": str(uuid7()),
    }
    response = await api.client.post(ROOT, json=body, headers=headers)
    assert response.status_code == 200, response.text
    duplicate = await api.client.post(ROOT, json=body, headers=headers)
    assert duplicate.json() == response.json()
    return headers, response.json()


def command(document: dict[str, Any]) -> dict[str, Any]:
    return {"expected_version": document["template"]["version"], "idempotency_key": str(uuid7())}


async def test_m4_owner_csrf_origin_idor_and_pagination(
    integrated_api: IntegratedApi, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    api = integrated_api
    assert (await api.client.get(ROOT)).status_code == 401
    assert (await api.client.get(f"{ROOT}/node-types")).status_code == 401
    headers, doc = await create(api)
    path = f"{ROOT}/{doc['template']['id']}"
    for method, suffix, body in (
        ("POST", "/publish", command(doc)),
        ("PUT", "", {**command(doc), "archived": True}),
        ("PUT", "/draft", {**command(doc), "spec": doc["version"]["spec"]}),
    ):
        assert (await api.client.request(method, path + suffix, json=body)).status_code == 403
        assert (
            await api.client.request(
                method,
                path + suffix,
                json=body,
                headers={**headers, "origin": "https://other.test"},
            )
        ).status_code == 403
    assert (await api.client.get(f"{ROOT}?limit=101")).status_code == 422
    page = (await api.client.get(f"{ROOT}?limit=1")).json()
    assert len(page["items"]) == 1
    assert (await api.client.get(path)).json() == doc
    assert (await api.client.get(f"{path}/published")).status_code == 404
    assert (await api.client.get(f"{path}/versions/{uuid7()}")).status_code == 404
    assert len((await api.client.get(f"{ROOT}/node-types")).json()["items"]) == 13
    foreign = await seed_run(session_factory)
    async with api.factory() as session:
        version = await session.get(WorkflowVersionModel, foreign.workflow_version_id)
        assert version
        foreign_template = version.workflow_template_id
    assert (await api.client.get(f"{ROOT}/{foreign_template}")).status_code == 404
    assert (
        await api.client.get(f"{path}/versions/{foreign.workflow_version_id}")
    ).status_code == 404


async def test_m4_publish_revision_isolation_restart_and_database_immutability(
    integrated_api: IntegratedApi,
) -> None:
    api = integrated_api
    headers, draft = await create(api)
    path = f"{ROOT}/{draft['template']['id']}"
    validation = await api.client.post(
        f"{path}/validate",
        json={**command(draft), "spec": draft["version"]["spec"], "layout": {}},
        headers=headers,
    )
    assert validation.status_code == 200 and validation.json()["valid"], validation.text
    publication = command(draft)
    response = await api.client.post(f"{path}/publish", json=publication, headers=headers)
    assert response.status_code == 200, response.text
    published = response.json()
    assert (
        published["version"]["published"]
        and published["template"]["current_draft_version_id"] is None
    )
    assert (
        await api.client.post(f"{path}/publish", json=publication, headers=headers)
    ).json() == published
    assert (await api.client.get(f"{path}/published")).json() == published
    immutable = deepcopy(published["version"])
    assert (
        await api.client.put(
            f"{path}/draft",
            json={**command(published), "spec": published["version"]["spec"]},
            headers=headers,
        )
    ).status_code == 404
    response = await api.client.post(
        f"{path}/draft",
        json={**command(published), "source_version_id": immutable["id"]},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    revised = response.json()
    assert revised["version"]["id"] != immutable["id"] and revised["version"]["version"] == 2
    revised["version"]["spec"]["name"] = "Updated objective"
    response = await api.client.put(
        f"{path}/draft",
        json={
            **command(revised),
            "spec": revised["version"]["spec"],
            "layout": {"nodes": {"finish": {"x": 320, "y": 200}}},
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    revised = response.json()
    assert (await api.client.get(f"{path}/versions/{immutable['id']}")).json()[
        "version"
    ] == immutable
    response = await api.client.post(f"{path}/publish", json=command(revised), headers=headers)
    assert response.status_code == 200, response.text
    second = response.json()
    assert second["version"]["content_hash"] != immutable["content_hash"]
    versions = (await api.client.get(f"{path}/versions")).json()["items"]
    assert [v["version"] for v in versions] == [1, 2]
    assert versions[0] == immutable
    async with api.factory() as session:
        stored = await session.get(WorkflowVersionModel, UUID(immutable["id"]))
        assert stored and stored.resolved_snapshot_json
        snapshot = WorkflowResolvedSnapshot.model_validate(stored.resolved_snapshot_json)
        assert snapshot.snapshot_hash == stored.snapshot_hash == immutable["snapshot_hash"]
    for column, value in (
        ("spec_json", "'{}'::jsonb"),
        ("layout_json", "'{}'::jsonb"),
        ("published_at", "NULL"),
        ("resolved_snapshot_json", "'{}'::jsonb"),
    ):
        with pytest.raises(DBAPIError):
            async with api.factory.begin() as session:
                await session.execute(
                    text(f"UPDATE control.workflow_versions SET {column}={value} WHERE id=:id"),
                    {"id": immutable["id"]},
                )
    with pytest.raises(DBAPIError):
        async with api.factory.begin() as session:
            await session.execute(
                text("DELETE FROM control.workflow_versions WHERE id=:id"), {"id": immutable["id"]}
            )
    with pytest.raises(DBAPIError):
        async with api.factory.begin() as session:
            await session.execute(
                text(
                    "UPDATE control.workflow_templates SET current_draft_version_id=:version "
                    "WHERE id=:id"
                ),
                {"id": draft["template"]["id"], "version": immutable["id"]},
            )
    # Reconstruct a service in a different process-like session; no in-memory editor state.
    from jarvis_api.registry.service import RegistryService
    from jarvis_api.workflows.service import WorkflowService

    reopened = await WorkflowService(api.factory, RegistryService(api.factory)).get(
        UUID(draft["template"]["id"]), api.owner_id
    )
    assert reopened.version.id == UUID(second["version"]["id"])


async def test_m4_invalid_draft_preserved_publish_report_and_concurrent_writes(
    integrated_api: IntegratedApi,
) -> None:
    api = integrated_api
    headers, draft = await create(api)
    path = f"{ROOT}/{draft['template']['id']}"
    spec = deepcopy(draft["version"]["spec"])
    spec["nodes"].append(
        {"id": "unreachable", "type": "router", "label": "Disconnected router", "config": {}}
    )
    body = {**command(draft), "spec": spec, "layout": {}}
    first, second = await asyncio.gather(
        api.client.put(f"{path}/draft", json=body, headers=headers),
        api.client.put(
            f"{path}/draft", json={**body, "idempotency_key": str(uuid7())}, headers=headers
        ),
    )
    assert sorted((first.status_code, second.status_code)) == [200, 409]
    saved = first.json() if first.status_code == 200 else second.json()
    failed = await api.client.post(f"{path}/publish", json=command(saved), headers=headers)
    assert failed.status_code == 422, failed.text
    issues = failed.json()["error"]["details"]["validation"]["issues"]
    assert any(i["node_id"] == "unreachable" for i in issues)
    assert (await api.client.get(path)).json()["version"]["spec"] == saved["version"]["spec"]
    duplicate = deepcopy(spec)
    duplicate["nodes"].append(duplicate["nodes"][0])
    failed = await api.client.post(
        f"{path}/validate", json={**command(saved), "spec": duplicate}, headers=headers
    )
    assert failed.status_code == 200 and not failed.json()["valid"]
    assert any(i["node_id"] == "finish" for i in failed.json()["issues"])
    changed = await api.client.put(
        f"{path}/draft",
        json={**body, "spec": {**spec, "name": "Conflicting change"}},
        headers=headers,
    )
    assert changed.status_code == 409


async def test_m4_archive_history_audit_and_no_fake_runtime_events(
    integrated_api: IntegratedApi,
) -> None:
    api = integrated_api
    headers, draft = await create(api)
    path = f"{ROOT}/{draft['template']['id']}"
    response = await api.client.put(
        path, json={**command(draft), "archived": True}, headers=headers
    )
    assert response.status_code == 200
    archived = response.json()
    assert archived["archived"]
    assert (await api.client.get(path)).status_code == 200
    assert (
        await api.client.post(
            f"{path}/publish",
            json={"expected_version": archived["version"], "idempotency_key": str(uuid7())},
            headers=headers,
        )
    ).status_code == 409
    response = await api.client.put(
        path,
        json={
            "expected_version": archived["version"],
            "idempotency_key": str(uuid7()),
            "archived": False,
        },
        headers=headers,
    )
    assert response.status_code == 200 and not response.json()["archived"]
    async with api.factory() as session:
        events = list(
            await session.scalars(
                select(EventModel).where(
                    EventModel.data_json["template_id"].astext == draft["template"]["id"]
                )
            )
        )
    assert {event.type for event in events} == {
        "workflow.created",
        "workflow.archived",
        "workflow.restored",
    }
    assert all(event.run_id is None and event.category == "config" for event in events)


@pytest.mark.parametrize(
    "unsafe",
    [
        "secret:server-private",
        "file:private.env#KEY",
        "sk-proj-" + "M4SyntheticCredentialCanary00000000",
    ],
)
async def test_m4_private_reference_and_credential_strings_never_roundtrip(
    integrated_api: IntegratedApi, unsafe: str
) -> None:
    headers, doc = await create(integrated_api)
    path = f"{ROOT}/{doc['template']['id']}"
    spec = deepcopy(doc["version"]["spec"])
    spec["name"] = unsafe
    response = await integrated_api.client.put(
        f"{path}/draft", json={**command(doc), "spec": spec}, headers=headers
    )
    assert response.status_code == 422 and unsafe not in response.text
    assert unsafe not in (await integrated_api.client.get(path)).text


async def test_m4_xss_inert_layout_limits_and_large_document_transport(
    integrated_api: IntegratedApi,
) -> None:
    api = integrated_api
    headers, doc = await create(api)
    path = f"{ROOT}/{doc['template']['id']}"
    spec = deepcopy(doc["version"]["spec"])
    spec["nodes"][0]["label"] = "<img src=x onerror=alert(1)>"
    response = await api.client.put(
        f"{path}/draft",
        json={
            **command(doc),
            "spec": spec,
            "layout": {"nodes": {"finish": {"x": 0, "y": 0, "html": "<script>"}}},
        },
        headers=headers,
    )
    assert response.status_code == 422
    for position in (1e10, -1e10):
        response = await api.client.put(
            f"{path}/draft",
            json={
                **command(doc),
                "spec": spec,
                "layout": {"nodes": {"finish": {"x": position, "y": 0}}},
            },
            headers=headers,
        )
        assert response.status_code == 422
    response = await api.client.put(
        f"{path}/draft", json={**command(doc), "spec": spec}, headers=headers
    )
    assert response.status_code == 200, response.text
    saved = response.json()
    # A real 200-node document exceeds the old 64 KiB generic API envelope.
    large = deepcopy(spec)
    for index in range(200):
        large["nodes"].append(
            {
                "id": f"node-{index}",
                "type": "router",
                "label": "R" * 160,
                "config": {},
                "policy": large["defaults"],
            }
        )
    response = await api.client.put(
        f"{path}/draft", json={**command(saved), "spec": large}, headers=headers
    )
    assert response.status_code == 200, response.text
    response = await api.client.post(
        f"{path}/validate",
        content=b"x" * 1_048_577,
        headers={**headers, "content-type": "application/json"},
    )
    assert response.status_code == 413


async def test_m4_cross_template_pointer_and_identity_are_db_protected(
    integrated_api: IntegratedApi, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    headers, doc = await create(integrated_api)
    response = await integrated_api.client.post(
        ROOT,
        json={"key": f"other-{uuid7().hex}", "name": "Other", "idempotency_key": str(uuid7())},
        headers=headers,
    )
    other = response.json()
    for assignment, value in (
        ("current_draft_version_id", other["version"]["id"]),
        ("key", "replacement-key"),
    ):
        with pytest.raises(DBAPIError):
            async with session_factory.begin() as session:
                await session.execute(
                    text(f"UPDATE control.workflow_templates SET {assignment}=:value WHERE id=:id"),
                    {"id": doc["template"]["id"], "value": value},
                )
