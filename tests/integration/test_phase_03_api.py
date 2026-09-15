"""Phase 3 authenticated profile discovery and project persistence."""

import pytest
from uuid6 import uuid7

from jarvis_orchestrator.verification.profiles import profile_templates
from tests.integration.test_m2_integrated_api import IntegratedApi, login
from tests.integration.test_m2_integrated_api import integrated_api as integrated_api

pytestmark = pytest.mark.integration


async def test_execution_profile_templates_and_project_selection(
    integrated_api: IntegratedApi,
) -> None:
    api = integrated_api
    templates_path = "/api/v1/execution-profiles/templates"
    assert (await api.client.get(templates_path)).status_code == 401
    headers = {"x-csrf-token": (await login(api)).json()["csrf_token"]}
    templates = await api.client.get(templates_path)
    assert templates.status_code == 200
    assert [item["profile_key"] for item in templates.json()["items"]] == [
        "python-pytest-v1",
        "node-build-v1",
        "browser-acceptance-v1",
    ]

    registry = await api.client.post(
        "/api/v1/registry/execution_profile",
        headers=headers,
        json={
            "key": f"phase3-profile-{uuid7().hex}",
            "display_name": "Phase 3 Node profile",
            "idempotency_key": str(uuid7()),
            "spec": profile_templates()[1].model_dump(mode="json"),
        },
    )
    assert registry.status_code == 200, registry.text
    revision_id = registry.json()["revision_id"]
    project_body = {
        "idempotency_key": str(uuid7()),
        "slug": f"phase3-{uuid7().hex}",
        "name": "Phase 3 web project",
        "project_type": "node",
        "execution_profile_revision_ids": [revision_id],
    }
    project = await api.client.post("/api/v1/projects", headers=headers, json=project_body)
    assert project.status_code == 201, project.text
    assert project.json()["project_type"] == "node"
    assert project.json()["execution_profile_revision_ids"] == [revision_id]
    listed = await api.client.get("/api/v1/projects")
    assert any(item == project.json() for item in listed.json()["items"])

    missing = await api.client.post(
        "/api/v1/projects",
        headers=headers,
        json={
            **project_body,
            "idempotency_key": str(uuid7()),
            "slug": f"missing-{uuid7().hex}",
            "execution_profile_revision_ids": [str(uuid7())],
        },
    )
    assert missing.status_code == 422
    assert missing.json()["error"]["code"] == "project.execution_profile_invalid"
