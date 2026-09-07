"""Authenticated route previews and accounting queries against real PostgreSQL."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from uuid6 import uuid7

from jarvis_api.auth.dependencies import current_principal
from jarvis_api.auth.service import AuthPrincipal
from jarvis_api.main import create_app
from jarvis_api.registry.service import RegistryService
from jarvis_api.routing.observability import AccountingService, HealthService
from jarvis_api.routing.policies import calculate_cost, resolve_route
from jarvis_contracts.registry import (
    AccountingRecord,
    CircuitPolicy,
    ModelProfileSpec,
    RegistryRecord,
    RegistryWrite,
    RouteCandidate,
    RouteEvaluationData,
    RoutePolicySpec,
    RoutePreviewRequest,
    RouteRequirements,
    SpendPolicy,
    Usage,
)
from jarvis_persistence.models import EventModel, ModelCallModel, ProviderHealthModel
from tests.integration.test_m2_integrated_api import (
    KEY,
    ORIGIN,
    IntegratedApi,
    login,
)
from tests.integration.test_m2_integrated_api import (
    integrated_api as integrated_api,
)
from tests.integration.test_m3_observability import configured as configured

pytestmark = pytest.mark.integration
Configured = tuple[async_sessionmaker[AsyncSession], RegistryRecord, RegistryRecord]


async def route_for(
    api: IntegratedApi, model: RegistryRecord, *, spend: SpendPolicy | None = None
) -> RegistryRecord:
    service = RegistryService(api.factory)
    return await service.write(
        "route_policy",
        RegistryWrite(
            key=f"route-{uuid7().hex}",
            display_name="HTTP preview route",
            idempotency_key=str(uuid7()),
            spec=RoutePolicySpec(
                candidates=(RouteCandidate(profile_revision_id=model.revision_id),),
                purposes=("utility",),
                allow_unknown_health=True,
                spend=spend or SpendPolicy(),
            ),
        ),
        actor_id=api.owner_id,
        correlation_id=str(uuid7()),
    )


async def test_preview_auth_csrf_exact_snapshot_and_current_disable(
    integrated_api: IntegratedApi,
    configured: Configured,
) -> None:
    api = integrated_api
    _, provider, model = configured
    route = await route_for(api, model)
    request = RoutePreviewRequest(
        route_revision_id=route.revision_id,
        requirements=RouteRequirements(purpose="utility", input_tokens=10, output_tokens=10),
    )
    payload = request.model_dump(mode="json")
    assert (await api.client.post("/api/v1/routing/preview", json=payload)).status_code == 401
    session = await login(api)
    assert (await api.client.post("/api/v1/routing/preview", json=payload)).status_code == 403
    headers = {"x-csrf-token": session.json()["csrf_token"]}
    response = await api.client.post("/api/v1/routing/preview", json=payload, headers=headers)
    assert response.status_code == 200, response.text
    expected = resolve_route(
        request, route, {model.revision_id: model, provider.revision_id: provider}
    )
    assert response.json() == expected.model_dump(mode="json")
    assert response.json()["decision"] == "allow"
    again = await api.client.post("/api/v1/routing/preview", json=payload, headers=headers)
    assert again.json()["snapshot_hash"] == response.json()["snapshot_hash"]
    service = RegistryService(api.factory)
    await service.write(
        "provider_connection",
        RegistryWrite(
            key=provider.key,
            display_name=provider.display_name,
            enabled=False,
            expected_version=provider.version,
            idempotency_key=str(uuid7()),
            spec=provider.spec,
        ),
        actor_id=api.owner_id,
        correlation_id="emergency-disable",
        configuration_id=provider.id,
    )
    denied = await api.client.post("/api/v1/routing/preview", json=payload, headers=headers)
    assert denied.status_code == 200 and denied.json()["decision"] == "deny"
    assert denied.json()["snapshot_hash"] != response.json()["snapshot_hash"]
    assert "Provider is disabled or archived" in denied.json()["candidates"][0]["reasons"]
    assert (await service.get_revision(provider.revision_id)).enabled
    for observed_response in (response, denied):
        async with api.factory() as database:
            event = await database.scalar(
                select(EventModel).where(
                    EventModel.correlation_id == observed_response.headers["x-request-id"],
                    EventModel.type == "model.route_selected",
                )
            )
            assert event is not None
            retained = RouteEvaluationData.model_validate(event.data_json)
        reconstructed: dict[UUID, RegistryRecord] = {}
        for observation in retained.observed_state:
            pinned = await service.get_revision(observation.revision_id)
            state = observation.model_dump(exclude={"revision_id", "credential_status"})
            state["secret_status"] = observation.credential_status
            reconstructed[pinned.revision_id] = pinned.model_copy(update=state)
        recovered_route = reconstructed.pop(retained.route_revision_id)
        replayed = resolve_route(retained.request, recovered_route, reconstructed)
        assert replayed.model_dump(mode="json") == observed_response.json()
    missing = await api.client.post(
        "/api/v1/routing/preview",
        json={**payload, "route_revision_id": str(uuid7())},
        headers=headers,
    )
    assert missing.status_code == 422
    wrong_kind = await api.client.post(
        "/api/v1/routing/preview",
        json={**payload, "route_revision_id": str(model.revision_id)},
        headers=headers,
    )
    assert wrong_kind.status_code == 422


@pytest.mark.parametrize("action", ["deny", "require_approval"])
async def test_spend_denial_is_durable_and_preview_never_creates_approval(
    integrated_api: IntegratedApi,
    configured: Configured,
    action: str,
) -> None:
    api = integrated_api
    _, _, model = configured
    route = await route_for(
        api,
        model,
        spend=SpendPolicy.model_validate({"max_output_tokens": 1, "on_exceeded": action}),
    )
    session = await login(api)
    response = await api.client.post(
        "/api/v1/routing/preview",
        headers={"x-csrf-token": session.json()["csrf_token"]},
        json={
            "route_revision_id": str(route.revision_id),
            "requirements": {"purpose": "utility", "output_tokens": 10},
        },
    )
    assert response.status_code == 200
    assert response.json()["decision"] == action
    assert response.json()["selected_profile_revision_id"] == str(model.revision_id)
    async with api.factory() as database:
        rows = list(
            await database.scalars(
                select(EventModel).where(
                    EventModel.correlation_id == response.headers["x-request-id"]
                )
            )
        )
        assert len(rows) == 1 and rows[0].type == "model.route_selected"
        assert rows[0].data_json["decision"] == action
        assert rows[0].data_json["snapshot_hash"] == response.json()["snapshot_hash"]


async def test_accounting_query_auth_pagination_and_read_only_role_boundary(
    integrated_api: IntegratedApi,
    configured: Configured,
) -> None:
    api = integrated_api
    factory, provider, model = configured
    assert isinstance(model.spec, ModelProfileSpec)
    usage = Usage(input_tokens=10, output_tokens=5, provenance="exact")
    calls: list[AccountingRecord] = []
    for _ in range(2):
        record = AccountingRecord(
            id=uuid7(),
            profile_revision_id=model.revision_id,
            provider_revision_id=provider.revision_id,
            correlation_id=str(uuid7()),
            latency_ms=12,
            usage=usage,
            pricing=model.spec.pricing,
            cost=calculate_cost(usage, model.spec.pricing),
            outcome="completed",
            created_at=datetime.now(UTC),
            demo=True,
        )
        calls.append(await AccountingService(factory).record(record, idempotency_key=str(uuid7())))
    assert (await api.client.get("/api/v1/accounting")).status_code == 401
    session = await login(api)
    page = await api.client.get(f"/api/v1/accounting?after={calls[0].id}&limit=1")
    assert page.status_code == 200
    assert page.json()["items"][0] == calls[1].model_dump(mode="json")
    assert (
        await api.client.get("/api/v1/accounting?after=ffffffff-ffff-ffff-ffff-ffffffffffff")
    ).json()["items"] == []
    assert (await api.client.get("/api/v1/accounting?after=invalid")).status_code == 422
    assert (await api.client.get("/api/v1/accounting?limit=101")).status_code == 422
    # Exercise the explicit owner guard, even though current database accounts are owner-only.
    app = create_app(
        settings=api.settings, session_factory=api.factory, clock=api.clock, server_key=KEY
    )
    owner = await app.state.auth_service.authenticate(
        session_token=api.client.cookies[api.settings.session_cookie_name],
        correlation_id="owner-guard",
    )
    assert owner is not None

    async def viewer() -> AuthPrincipal:
        return replace(cast(AuthPrincipal, owner), role="viewer")

    app.dependency_overrides[current_principal] = viewer
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as client:
        assert (await client.get("/api/v1/accounting")).status_code == 403
        assert (
            await client.post(
                "/api/v1/routing/preview",
                headers={"x-csrf-token": session.json()["csrf_token"]},
                json={
                    "route_revision_id": str(uuid7()),
                    "requirements": {"purpose": "utility"},
                },
            )
        ).status_code == 403


async def test_accounting_rejects_wrong_kind_and_undeclared_route_pin(
    integrated_api: IntegratedApi,
    configured: Configured,
) -> None:
    factory, provider, model = configured
    assert isinstance(model.spec, ModelProfileSpec)
    registry = RegistryService(integrated_api.factory)
    alternate = await registry.write(
        "model_profile",
        RegistryWrite(
            key=f"alternate-{uuid7().hex}",
            display_name="Alternate model",
            idempotency_key=str(uuid7()),
            spec=model.spec,
        ),
        actor_id=integrated_api.owner_id,
        correlation_id=str(uuid7()),
    )
    route = await route_for(integrated_api, alternate)
    usage = Usage(input_tokens=2, output_tokens=3, provenance="exact")
    for route_id in (provider.revision_id, route.revision_id):
        record = AccountingRecord(
            id=uuid7(),
            profile_revision_id=model.revision_id,
            provider_revision_id=provider.revision_id,
            route_revision_id=route_id,
            correlation_id=str(uuid7()),
            latency_ms=12,
            usage=usage,
            pricing=model.spec.pricing,
            cost=calculate_cost(usage, model.spec.pricing),
            outcome="completed",
            created_at=datetime.now(UTC),
            demo=True,
        )
        with pytest.raises(ValueError, match="profile is not declared by route"):
            await AccountingService(factory).record(record, idempotency_key=str(uuid7()))
        async with factory() as session:
            assert await session.get(ModelCallModel, record.id) is None
            assert (
                await session.scalar(
                    select(EventModel.event_id).where(
                        EventModel.correlation_id == record.correlation_id
                    )
                )
                is None
            )


async def test_provider_health_rejects_foreign_revision_without_durable_side_effects(
    configured: Configured,
) -> None:
    factory, _, model = configured
    service = HealthService(factory)
    with pytest.raises(ValueError, match="requires a provider revision"):
        await service.acquire_probe(model.revision_id, CircuitPolicy())
    with pytest.raises(ValueError, match="requires a provider revision"):
        await service.observe(model.revision_id, CircuitPolicy(), success=True)
    async with factory() as session:
        assert await session.get(ProviderHealthModel, model.revision_id) is None
        assert (
            await session.scalar(
                select(EventModel.event_id).where(
                    EventModel.correlation_id == str(model.revision_id),
                    EventModel.type == "model.health_changed",
                )
            )
            is None
        )
