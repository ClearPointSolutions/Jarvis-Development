"""Real authenticated registry HTTP boundary with database-role enforcement."""

from __future__ import annotations

import pytest
from uuid6 import uuid7

from tests.integration.test_m2_integrated_api import (
    ORIGIN,
    IntegratedApi,
    login,
)
from tests.integration.test_m2_integrated_api import (
    integrated_api as integrated_api,
)

pytestmark = pytest.mark.integration


async def test_registry_http_auth_csrf_origin_and_safe_errors(
    integrated_api: IntegratedApi,
) -> None:
    client = integrated_api.client
    path = "/api/v1/registry/worker"
    body = {
        "key": f"http-{uuid7().hex}",
        "display_name": "HTTP worker",
        "idempotency_key": str(uuid7()),
        "spec": {"kind": "worker"},
    }
    assert (await client.get(path)).status_code == 401
    assert (await client.post(path, json=body)).status_code == 401
    session = await login(integrated_api)
    csrf = session.json()["csrf_token"]
    assert (await client.post(path, json=body)).status_code == 403
    assert (
        await client.post(path, json=body, headers={"x-csrf-token": "invalid"})
    ).status_code == 403
    headers = {"x-csrf-token": csrf}
    assert (
        await client.post(path, json=body, headers={**headers, "origin": "https://untrusted.test"})
    ).status_code == 403
    created = await client.post(path, json=body, headers=headers)
    assert created.status_code == 200, created.text
    record = created.json()
    item_path = f"{path}/{record['id']}"
    assert (await client.get(item_path)).json() == record
    assert (await client.get(f"{item_path}/revisions")).json()["items"] == [record]
    assert (await client.get(f"{path}?limit=0")).status_code == 422
    assert (await client.get(f"{path}?limit=101")).status_code == 422
    assert (await client.get(f"{path}/{uuid7()}")).status_code == 404
    canary = "sk-proj-" + "SyntheticHttpRegistryCanary00000000000"
    response = await client.post(path, json={**body, "description": canary}, headers=headers)
    assert response.status_code == 422 and canary not in response.text
    malformed = await client.post(path, json={**body, "secret_ref": canary}, headers=headers)
    assert malformed.status_code == 422 and canary not in malformed.text
    invalid = await client.post(
        path,
        json={
            **body,
            "spec": {"kind": "worker", "labels": {"password": "arbitrary-credential-value"}},
        },
        headers=headers,
    )
    assert invalid.status_code == 422 and "arbitrary-credential-value" not in invalid.text
    assert (
        await client.post(
            f"{item_path}/validate", json={"idempotency_key": str(uuid7())}, headers=headers
        )
    ).status_code == 200
    # The request needs both same-origin transport and the authenticated session.
    client.cookies.clear()
    assert (await client.get(item_path, headers={"Origin": ORIGIN})).status_code == 401


async def test_registry_masks_execution_paths_before_storage(integrated_api: IntegratedApi) -> None:
    client = integrated_api.client
    session = await login(integrated_api)
    response = await client.post(
        "/api/v1/registry/worker",
        headers={"x-csrf-token": session.json()["csrf_token"]},
        json={
            "key": f"masked-{uuid7().hex}",
            "display_name": "Masked worker",
            "idempotency_key": str(uuid7()),
            "spec": {
                "kind": "worker",
                "execution_host_label": "/opt/private-deployment/configuration",
            },
        },
    )
    assert response.status_code == 200
    assert "/opt/private-deployment" not in response.text
    assert response.json()["spec"]["execution_host_label"] == "Server-managed execution host"
