"""Real PostgreSQL registry behavior under the least-privilege API role."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from uuid6 import uuid7

from jarvis_api.errors import ApiProblemError
from jarvis_api.registry.service import RegistryService
from jarvis_contracts.base import sha256_digest
from jarvis_contracts.configuration import ConfigurationRevision
from jarvis_contracts.registry import (
    ModelBinding,
    ModelProfileSpec,
    PermissionPolicySpec,
    ProviderSpec,
    RegistryRecord,
    RegistrySpec,
    RegistryWrite,
    RetryRegistrySpec,
    RouteCandidate,
    RoutePolicySpec,
    WorkerSpec,
)
from jarvis_persistence.models import (
    ConfigurationModel,
    ConfigurationPrivateRefModel,
    ConfigurationRevisionModel,
    EventModel,
    IdempotencyRecordModel,
)

pytestmark = pytest.mark.integration
ACTOR = UUID("10000000-0000-0000-0000-000000000003")


@pytest_asyncio.fixture
async def registry(database_url: str) -> AsyncIterator[RegistryService]:
    engine = create_async_engine(
        database_url, connect_args={"options": "-c role=jarvis_v1_api"}, hide_parameters=True
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield RegistryService(factory, allowed_endpoints=("https://example.test/v1",))
    finally:
        await engine.dispose()


def write(spec: RegistrySpec, **values: object) -> RegistryWrite:
    return RegistryWrite.model_validate(
        {
            "key": f"test-{uuid7().hex}",
            "display_name": "Integration configuration",
            "idempotency_key": str(uuid7()),
            "spec": spec,
            **values,
        }
    )


async def create(registry: RegistryService, spec: RegistrySpec, **values: object) -> RegistryRecord:
    return await registry.write(
        spec.kind, write(spec, **values), actor_id=ACTOR, correlation_id=str(uuid7())
    )


async def profile(registry: RegistryService) -> RegistryRecord:
    provider = await create(registry, ProviderSpec(provider_kind="demo"))
    return await create(
        registry,
        ModelProfileSpec(
            provider_revision_id=provider.revision_id,
            model_identifier="demo-model",
            purposes=("planning",),
            context_limit=4096,
            output_limit=1024,
        ),
    )


async def test_six_kinds_historical_envelopes_and_revision_pagination(
    registry: RegistryService,
) -> None:
    model = await profile(registry)
    specs: list[RegistrySpec] = [
        WorkerSpec(),
        ProviderSpec(provider_kind="demo"),
        model.spec,
        RoutePolicySpec(
            candidates=(RouteCandidate(profile_revision_id=model.revision_id),),
            purposes=("planning",),
        ),
        RetryRegistrySpec(rules=()),
        PermissionPolicySpec(),
    ]
    for spec in specs:
        first = await create(registry, spec)
        body = write(
            spec,
            key=first.key,
            display_name="Retired configuration",
            enabled=False,
            archived=True,
            expected_version=first.version,
        )
        second = await registry.write(
            spec.kind, body, actor_id=ACTOR, correlation_id=str(uuid7()), configuration_id=first.id
        )
        assert second.version == first.version + 1
        assert second.content_hash != first.content_hash
        async with registry.sessions() as session:
            stored = await session.get(ConfigurationRevisionModel, second.revision_id)
            assert stored is not None
            ConfigurationRevision.model_validate(
                {
                    "id": stored.id,
                    "configuration_id": first.id,
                    "kind": spec.kind,
                    "key": first.key,
                    "revision": stored.revision,
                    "spec": stored.spec_json,
                    "content_hash": stored.content_hash,
                    "created_at": stored.created_at,
                }
            )
        assert not second.enabled and second.archived
        assert await registry.get_revision(first.revision_id) == first
        assert (await registry.get(spec.kind, first.id)).revision_id == second.revision_id
        page = await registry.revisions(spec.kind, first.id, limit=1)
        assert page.items == (first,) and page.next_after == first.revision_id
        assert (await registry.revisions(spec.kind, first.id, after=page.next_after)).items == (
            second,
        )
        assert (await registry.list(spec.kind)).items


async def test_actor_idempotency_concurrent_writes_and_global_events(
    registry: RegistryService,
) -> None:
    body = write(WorkerSpec())
    results = await asyncio.gather(
        *(
            registry.write("worker", body, actor_id=ACTOR, correlation_id="registry-race")
            for _ in range(4)
        )
    )
    assert all(item == results[0] for item in results)
    async with registry.sessions() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(ConfigurationRevisionModel)
                .where(ConfigurationRevisionModel.configuration_id == results[0].id)
            )
            == 1
        )
        events = list(
            await session.scalars(
                select(EventModel).where(EventModel.correlation_id == "registry-race")
            )
        )
        assert any(event.type == "config.created" for event in events)
    changed = body.model_copy(update={"display_name": "Changed"})
    with pytest.raises(ApiProblemError, match="idempotency_conflict"):
        await registry.write("worker", changed, actor_id=ACTOR, correlation_id="conflict")
    first = results[0]
    updates = [write(WorkerSpec(), key=first.key, expected_version=first.version) for _ in range(2)]
    outcomes = await asyncio.gather(
        *(
            registry.write(
                "worker",
                item,
                actor_id=ACTOR,
                correlation_id="concurrent-update",
                configuration_id=first.id,
            )
            for item in updates
        ),
        return_exceptions=True,
    )
    assert sum(isinstance(item, RegistryRecord) for item in outcomes) == 1
    assert (
        sum(
            isinstance(item, ApiProblemError) and item.code == "registry.version_conflict"
            for item in outcomes
        )
        == 1
    )


async def test_private_ref_write_only_rotation_clear_and_validation(
    registry: RegistryService,
) -> None:
    spec = ProviderSpec(
        provider_kind="openai", base_url="https://example.test/v1", locality="remote"
    )
    first = await create(registry, spec, secret_ref="file:integration.env#OPENAI_API_KEY")
    assert first.secret_status == "configured"
    assert "integration.env" not in first.model_dump_json()
    async with registry.sessions() as session:
        private = await session.get(ConfigurationPrivateRefModel, first.revision_id)
        assert private and private.secret_ref == "file:integration.env#OPENAI_API_KEY"
        public = await session.get(ConfigurationRevisionModel, first.revision_id)
        assert public and "integration.env" not in str(public.spec_json)
    second = await registry.write(
        spec.kind,
        write(spec, key=first.key, expected_version=first.version),
        actor_id=ACTOR,
        correlation_id="carry-ref",
        configuration_id=first.id,
    )
    assert second.secret_status == "configured"
    third = await registry.write(
        spec.kind,
        write(spec, key=first.key, expected_version=second.version, clear_secret=True),
        actor_id=ACTOR,
        correlation_id="clear-ref",
        configuration_id=first.id,
    )
    assert third.secret_status == "missing"
    report = await registry.validate(
        spec.kind, first.id, idempotency_key=str(uuid7()), actor_id=ACTOR, correlation_id="validate"
    )
    assert not report.valid and report.health == "misconfigured" and not report.network_checked
    assert (await registry.get(spec.kind, first.id)).health == "misconfigured"
    assert (await registry.get_revision(first.revision_id)).secret_status == "configured"


@pytest.mark.parametrize("field", ["display_name", "description", "key", "idempotency_key"])
async def test_credential_canaries_rejected_before_any_storage(
    registry: RegistryService, field: str
) -> None:
    canary = "sk-proj-" + "syntheticnevervalidregistrycanary0123456789"
    body = write(WorkerSpec(), **{field: canary})
    with pytest.raises(ApiProblemError) as caught:
        await registry.write("worker", body, actor_id=ACTOR, correlation_id="unsafe-config")
    assert canary not in str(caught.value) and canary not in caught.value.message
    async with registry.sessions() as session:
        for table in (
            "control.configuration_revisions",
            "control.idempotency_records",
            "event_store.events",
        ):
            # Use parameter binding; never interpolate an input canary into SQL.
            count = await session.scalar(
                text(f"SELECT count(*) FROM {table} t WHERE row_to_json(t)::text LIKE :pattern"),
                {"pattern": f"%{canary}%"},
            )
            assert count == 0


async def test_secret_update_rejection_preserves_current_and_historical_state(
    registry: RegistryService,
) -> None:
    spec = ProviderSpec(
        provider_kind="openai", base_url="https://example.test/v1", locality="remote"
    )
    original = await create(registry, spec, secret_ref="secret:original-reference")
    canary = "sk-proj-" + "syntheticupdatecanary0000000000000000000"
    changed = write(
        spec,
        key=original.key,
        expected_version=original.version,
        description=canary,
        secret_ref="secret:new-reference",
    )
    with pytest.raises(ApiProblemError, match="unsafe_input"):
        await registry.write(
            spec.kind,
            changed,
            actor_id=ACTOR,
            correlation_id="unsafe-update",
            configuration_id=original.id,
        )
    assert await registry.get(spec.kind, original.id) == original
    assert (await registry.revisions(spec.kind, original.id)).items == (original,)
    async with registry.sessions() as session:
        private = await session.get(ConfigurationPrivateRefModel, original.revision_id)
        assert private and private.secret_ref == "secret:original-reference"
        assert (
            await session.scalar(
                select(IdempotencyRecordModel.id).where(
                    IdempotencyRecordModel.key == changed.idempotency_key
                )
            )
            is None
        )
        assert (
            await session.scalar(
                select(EventModel.event_id).where(EventModel.correlation_id == "unsafe-update")
            )
            is None
        )


async def test_endpoint_foreign_kind_and_inactive_reference_denied(
    registry: RegistryService,
) -> None:
    with pytest.raises(ApiProblemError, match="endpoint_denied"):
        await create(
            registry, ProviderSpec(provider_kind="ollama", base_url="http://127.0.0.1:9999")
        )
    worker = await create(registry, WorkerSpec())
    with pytest.raises(ApiProblemError, match="invalid_reference"):
        await create(
            registry,
            ModelProfileSpec(
                provider_revision_id=worker.revision_id,
                model_identifier="demo",
                purposes=("planning",),
                context_limit=4096,
                output_limit=100,
            ),
        )
    provider = await create(registry, ProviderSpec(provider_kind="demo"), enabled=False)
    with pytest.raises(ApiProblemError, match="inactive_reference"):
        await create(
            registry,
            ModelProfileSpec(
                provider_revision_id=provider.revision_id,
                model_identifier="demo",
                purposes=("planning",),
                context_limit=4096,
                output_limit=100,
            ),
        )


async def test_api_role_immutable_revision_and_private_refs(registry: RegistryService) -> None:
    row = await create(registry, WorkerSpec())
    for table in ("control.configuration_revisions", "control.configuration_private_refs"):
        async with registry.sessions.begin() as session:
            assert await session.scalar(text("SELECT current_user")) == "jarvis_v1_api"
            with pytest.raises(DBAPIError):
                async with session.begin_nested():
                    await session.execute(text(f"DELETE FROM {table}"))
    async with registry.sessions.begin() as session:
        with pytest.raises(DBAPIError):
            async with session.begin_nested():
                await session.execute(
                    text("UPDATE control.configuration_revisions SET spec_json='{}' WHERE id=:id"),
                    {"id": row.revision_id},
                )


async def test_demo_validation_is_honest_and_duplicate_is_read_only(
    registry: RegistryService,
) -> None:
    row = await create(registry, ProviderSpec(provider_kind="demo"))
    key = str(uuid7())
    report = await registry.validate(
        row.spec.kind, row.id, idempotency_key=key, actor_id=ACTOR, correlation_id=key
    )
    again = await registry.validate(
        row.spec.kind, row.id, idempotency_key=key, actor_id=ACTOR, correlation_id=key
    )
    assert report == again and report.valid and report.demo
    assert report.health == "unknown" and not report.network_checked
    async with registry.sessions() as session:
        assert (
            await session.scalar(
                select(func.count()).select_from(EventModel).where(EventModel.correlation_id == key)
            )
            == 1
        )


async def test_legacy_binding_path_masking_and_profile_capability_compatibility(
    registry: RegistryService,
) -> None:
    model = await profile(registry)
    assert isinstance(model.spec, ModelProfileSpec)
    updated_spec = model.spec.model_copy(
        update={"structured_json": True, "tool_calls": True, "streaming": True}
    )
    updated = await registry.write(
        "model_profile",
        write(updated_spec, key=model.key, expected_version=model.version),
        actor_id=ACTOR,
        correlation_id="profile-features",
        configuration_id=model.id,
    )
    route = await create(
        registry,
        RoutePolicySpec(
            candidates=(RouteCandidate(profile_revision_id=updated.revision_id),),
            purposes=("planning",),
            required_capabilities=("structured_json", "tool_calls", "streaming"),
        ),
    )
    assert route.spec.kind == "route_policy"
    worker = await create(
        registry,
        WorkerSpec(
            adapter_kind="openhands_ssh_v1",
            execution_host_label="synthetic.internal",
            model_binding=ModelBinding(
                mode="worker_managed", allowed_profile_revision_ids=(updated.revision_id,)
            ),
        ),
        deployment_ref="secret:local-worker-manifest",
    )
    assert isinstance(worker.spec, WorkerSpec)
    assert worker.spec.deployment_configured
    assert worker.spec.execution_host_label == "Server-managed execution host"
    assert "local-worker-manifest" not in worker.model_dump_json()
    report = await registry.validate(
        "worker",
        worker.id,
        idempotency_key=str(uuid7()),
        actor_id=ACTOR,
        correlation_id="legacy-validation",
    )
    assert report.valid and not report.network_checked and report.health == "unknown"
    with pytest.raises(ApiProblemError, match="incompatible_profile"):
        await create(
            registry,
            RoutePolicySpec(
                candidates=(RouteCandidate(profile_revision_id=model.revision_id),),
                required_capabilities=("structured_json",),
                purposes=("planning",),
            ),
        )


async def test_registry_refuses_ambiguous_private_updates_and_identity_changes(
    registry: RegistryService,
) -> None:
    row = await create(registry, WorkerSpec())
    cases = [
        ("worker", write(WorkerSpec(), expected_version=2), None, "version_conflict"),
        ("worker", write(WorkerSpec(), key=row.key), None, "duplicate_key"),
        ("worker", write(WorkerSpec(), expected_version=row.version), row.id, "immutable_key"),
        ("provider_connection", write(WorkerSpec()), None, "kind_mismatch"),
        ("worker", write(WorkerSpec(), secret_ref="secret:test-locator"), None, "invalid_secret"),
        (
            "worker",
            write(WorkerSpec(), deployment_ref="secret:test-locator"),
            None,
            "invalid_deployment",
        ),
    ]
    for kind, body, identity, error in cases:
        with pytest.raises(ApiProblemError, match=error):
            await registry.write(
                body.spec.kind if kind == "worker" else "provider_connection",
                body,
                actor_id=ACTOR,
                correlation_id="invalid-update",
                configuration_id=identity,
            )
    provider = ProviderSpec(
        provider_kind="openai", base_url="https://example.test/v1", locality="remote"
    )
    with pytest.raises(ApiProblemError, match="invalid_secret"):
        await create(registry, provider, secret_ref="secret:integration", clear_secret=True)
    with pytest.raises(ApiProblemError, match="incompatible_locality"):
        remote = await create(registry, provider)
        await create(
            registry,
            ModelProfileSpec(
                provider_revision_id=remote.revision_id,
                model_identifier="test",
                purposes=("planning",),
                context_limit=1000,
                output_limit=100,
                locality="local",
            ),
        )


async def test_pre_m3_immutable_rows_are_not_exposed_as_typed_registry(
    registry: RegistryService,
) -> None:
    before = await create(registry, WorkerSpec())
    async with registry.sessions.begin() as session:
        identity = ConfigurationModel(
            id=uuid7(),
            kind="worker",
            key=f"old-{uuid7().hex}",
            display_name="Pre-M3 reference",
            enabled=True,
        )
        session.add(identity)
        await session.flush()
        revision = ConfigurationRevisionModel(
            id=uuid7(),
            configuration_id=identity.id,
            revision=1,
            schema_version="1.0",
            spec_json={"adapter": "legacy-reference"},
            content_hash="0" * 64,
        )
        session.add(revision)
        await session.flush()
        identity.current_revision_id = revision.id
    after = await create(registry, WorkerSpec())
    page = await registry.list("worker", after=before.id, limit=1)
    assert page.items == (after,)
    assert page.next_after is None
    with pytest.raises(ApiProblemError, match="unsupported_revision"):
        await registry.get_revision(revision.id)
    async with registry.sessions() as session:
        unchanged = await session.get(ConfigurationRevisionModel, revision.id)
        assert unchanged and unchanged.spec_json == {"adapter": "legacy-reference"}


@pytest.mark.parametrize(
    "provider_kind,unsupported", [("openai", {"seed": 1}), ("ollama", {"reasoning_effort": "low"})]
)
async def test_provider_specific_parameters_reject_create_update_and_validate(
    registry: RegistryService,
    provider_kind: str,
    unsupported: dict[str, object],
) -> None:
    provider = await create(
        registry,
        ProviderSpec.model_validate(
            {
                "provider_kind": provider_kind,
                "base_url": "https://example.test/v1",
                "locality": "remote",
            }
        ),
    )
    valid = ModelProfileSpec(
        provider_revision_id=provider.revision_id,
        model_identifier="parameter-test",
        purposes=("utility",),
        context_limit=1000,
        output_limit=100,
        locality="remote",
        parameters={"temperature": 0.5, "top_p": 0.9},
    )
    invalid = ModelProfileSpec.model_validate({**valid.model_dump(), "parameters": unsupported})
    with pytest.raises(ApiProblemError, match="incompatible_parameters") as rejected:
        await create(registry, invalid)
    assert rejected.value.status_code == 422
    original = await create(registry, valid)
    with pytest.raises(ApiProblemError, match="incompatible_parameters"):
        await registry.write(
            "model_profile",
            write(invalid, key=original.key, expected_version=original.version),
            actor_id=ACTOR,
            correlation_id="unsupported-parameter-update",
            configuration_id=original.id,
        )
    assert await registry.get("model_profile", original.id) == original
    # Simulate a previously persisted profile so explicit validation remains defensive.
    async with registry.sessions.begin() as session:
        envelope = {
            "spec": invalid.model_dump(mode="json"),
            "display_name": original.display_name,
            "description": "",
            "enabled": True,
            "archived": False,
        }
        revision = ConfigurationRevisionModel(
            id=uuid7(),
            configuration_id=original.id,
            revision=2,
            schema_version="1.0",
            spec_json=envelope,
            content_hash=sha256_digest(
                {
                    "kind": "model_profile",
                    "key": original.key,
                    "revision": 2,
                    "schema_version": "1.0",
                    "spec": envelope,
                }
            ),
        )
        session.add(revision)
        await session.flush()
        identity = await session.get(ConfigurationModel, original.id)
        assert identity is not None
        identity.current_revision_id = revision.id
        identity.version = 2
    report = await registry.validate(
        "model_profile",
        original.id,
        idempotency_key=str(uuid7()),
        actor_id=ACTOR,
        correlation_id="validate-unsupported-parameters",
    )
    assert not report.valid and report.health == "misconfigured" and not report.network_checked
