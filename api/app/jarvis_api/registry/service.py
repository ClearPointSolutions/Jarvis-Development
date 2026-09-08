"""Transactional registry; private locators never cross the response boundary."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import JsonValue, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from uuid6 import uuid7

from jarvis_api.errors import ApiProblemError
from jarvis_api.events.normalizer import EventIntent, EventNormalizer, EventWriter
from jarvis_api.events.redaction import RecursiveRedactor
from jarvis_contracts.base import canonical_json
from jarvis_contracts.enums import EventMode, EventSeverity, EventVisibility
from jarvis_contracts.events import EventSource
from jarvis_contracts.registry import (
    REGISTRY_SPEC_ADAPTER,
    ModelProfileSpec,
    ProviderSpec,
    RegistryKind,
    RegistryPage,
    RegistryRecord,
    RegistrySpec,
    RegistryWrite,
    RoutePolicySpec,
    ValidationReport,
    WorkerSpec,
)
from jarvis_persistence.models import (
    ConfigurationModel,
    ConfigurationPrivateRefModel,
    ConfigurationRevisionModel,
    EventGlobalCounterModel,
    ProviderHealthModel,
)
from jarvis_persistence.repositories import (
    EventRepository,
    IdempotencyConflictError,
    IdempotencyRepository,
)


def _problem(status: int, code: str, message: str) -> ApiProblemError:
    return ApiProblemError(status, f"registry.{code}", message)


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _safe_strings(value: JsonValue) -> None:
    if isinstance(value, str):
        if RecursiveRedactor().redact_text(value)[1]:
            raise _problem(422, "unsafe_input", "Credential-like configuration input is rejected")
    elif isinstance(value, list):
        for item in value:
            _safe_strings(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            if key != "clear_secret" and RecursiveRedactor().redact({key: None}).count:
                raise _problem(422, "unsafe_input", "Credential-like field names are rejected")
            _safe_strings(key)
            _safe_strings(item)


class RegistryService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        allowed_endpoints: tuple[str, ...] = (),
        instance_id: str = "registry-api",
    ) -> None:
        self.sessions = session_factory
        self.allowed_endpoints = frozenset(value.rstrip("/") for value in allowed_endpoints)
        self.instance_id = instance_id
        self.writer = EventWriter(
            repository=EventRepository(),
            normalizer=EventNormalizer(
                redactor=RecursiveRedactor(),
                artifact_sink=None,
                inline_bytes=32768,
                max_bytes=65536,
            ),
        )

    async def _lock(self, session: AsyncSession) -> None:
        row = await session.scalar(select(EventGlobalCounterModel).with_for_update())
        if row is None:
            raise _problem(503, "unavailable", "Registry storage is unavailable")

    async def _identity(
        self, session: AsyncSession, kind: RegistryKind, identity: UUID, *, lock: bool = False
    ) -> ConfigurationModel:
        statement = select(ConfigurationModel).where(
            ConfigurationModel.id == identity, ConfigurationModel.kind == kind
        )
        row = await session.scalar(statement.with_for_update() if lock else statement)
        if row is None:
            raise _problem(404, "not_found", "Configuration was not found")
        return row

    async def _record(
        self,
        session: AsyncSession,
        identity: ConfigurationModel,
        revision: ConfigurationRevisionModel,
    ) -> RegistryRecord:
        envelope = revision.spec_json
        required = {"spec", "display_name", "description", "enabled", "archived"}
        if set(envelope) != required or revision.schema_version != "1.0":
            raise _problem(
                422, "unsupported_revision", "Revision predates the typed registry schema"
            )
        try:
            spec = REGISTRY_SPEC_ADAPTER.validate_python(envelope["spec"])
        except ValidationError:
            raise _problem(
                422, "unsupported_revision", "Revision has an unsupported specification"
            ) from None
        private = await session.get(ConfigurationPrivateRefModel, revision.id)
        health = await session.get(ProviderHealthModel, revision.id)
        worker_runtime = None
        worker_health = None
        if isinstance(spec, WorkerSpec):
            from sqlalchemy import func

            from jarvis_contracts.registry import WorkerRuntimeFacts
            from jarvis_persistence.models import (
                WorkerHealthModel,
                WorkerInvocationModel,
                WorkerLeaseModel,
                WorkerSlotModel,
            )

            worker_health = await session.get(WorkerHealthModel, revision.id)
            count, heartbeat = (
                await session.execute(
                    select(
                        func.count(WorkerLeaseModel.slot_id).filter(
                            WorkerLeaseModel.released_at.is_(None)
                        ),
                        func.max(WorkerLeaseModel.renewed_at),
                    )
                    .join(WorkerSlotModel, WorkerLeaseModel.slot_id == WorkerSlotModel.id)
                    .where(WorkerSlotModel.worker_id == identity.id)
                )
            ).one()
            stalled = await session.scalar(
                select(func.bool_or(WorkerInvocationModel.possibly_stalled))
                .join(WorkerLeaseModel, WorkerInvocationModel.lease_id == WorkerLeaseModel.id)
                .join(WorkerSlotModel, WorkerLeaseModel.slot_id == WorkerSlotModel.id)
                .where(
                    WorkerSlotModel.worker_id == identity.id,
                    WorkerLeaseModel.released_at.is_(None),
                )
            )
            worker_runtime = WorkerRuntimeFacts(
                slots_in_use=count,
                last_heartbeat_at=heartbeat,
                possibly_stalled=bool(stalled),
                validated_at=worker_health.observed_at if worker_health else None,
                validation_issues=tuple(
                    worker_health.report_json.get("health", {}).get("issues", [])
                )
                if worker_health
                else (),
            )
        status = "not_required"
        if isinstance(spec, ProviderSpec):
            if private and private.secret_ref:
                status = "configured"
            elif spec.provider_kind == "openai":
                status = "missing"
        return RegistryRecord.model_validate(
            {
                "id": identity.id,
                "revision_id": revision.id,
                "revision": revision.revision,
                "version": revision.revision,
                "key": identity.key,
                "display_name": envelope["display_name"],
                "description": envelope["description"],
                "enabled": envelope["enabled"],
                "archived": envelope["archived"],
                "spec": spec,
                "content_hash": revision.content_hash,
                "created_at": identity.created_at,
                "updated_at": revision.created_at,
                "created_by": revision.created_by,
                "secret_status": status,
                "secret_label": "Server-managed credential" if status == "configured" else None,
                "health": worker_health.report_json["health"]["status"]
                if worker_health
                else health.status
                if health
                else "unknown",
                "worker_runtime": worker_runtime,
                "circuit_state": health.circuit_state if health else "closed",
            }
        )

    async def _revision(
        self,
        session: AsyncSession,
        revision_id: UUID,
        kind: RegistryKind | None = None,
        *,
        active: bool = False,
    ) -> RegistryRecord:
        revision = await session.get(ConfigurationRevisionModel, revision_id)
        identity = (
            await session.get(ConfigurationModel, revision.configuration_id) if revision else None
        )
        if revision is None or identity is None or (kind and identity.kind != kind):
            raise _problem(422, "invalid_reference", "Referenced revision has an incompatible kind")
        result = await self._record(session, identity, revision)
        if active and (
            not result.enabled or result.archived or not identity.enabled or identity.archived_at
        ):
            raise _problem(
                422, "inactive_reference", "Referenced configuration is disabled or archived"
            )
        return result

    async def get_revision(self, revision_id: UUID) -> RegistryRecord:
        async with self.sessions() as session:
            return await self._revision(session, revision_id)

    async def get(self, kind: RegistryKind, identity: UUID) -> RegistryRecord:
        async with self.sessions() as session:
            row = await self._identity(session, kind, identity)
            if row.current_revision_id is None:
                raise _problem(503, "unavailable", "Configuration has no current revision")
            return await self._revision(session, row.current_revision_id)

    async def list(
        self, kind: RegistryKind, after: UUID | None = None, limit: int = 50
    ) -> RegistryPage:
        async with self.sessions() as session:
            statement = (
                select(ConfigurationModel)
                .join(
                    ConfigurationRevisionModel,
                    ConfigurationRevisionModel.id == ConfigurationModel.current_revision_id,
                )
                .where(
                    ConfigurationModel.kind == kind,
                    ConfigurationRevisionModel.spec_json["spec"].is_not(None),
                    ConfigurationRevisionModel.spec_json["display_name"].is_not(None),
                    ConfigurationRevisionModel.spec_json["description"].is_not(None),
                    ConfigurationRevisionModel.spec_json["enabled"].is_not(None),
                    ConfigurationRevisionModel.spec_json["archived"].is_not(None),
                )
            )
            if after:
                statement = statement.where(ConfigurationModel.id > after)
            rows = list(
                await session.scalars(statement.order_by(ConfigurationModel.id).limit(limit + 1))
            )
            items = [
                await self._revision(session, row.current_revision_id)
                for row in rows[:limit]
                if row.current_revision_id is not None
            ]
            return RegistryPage(
                items=tuple(items), next_after=rows[limit - 1].id if len(rows) > limit else None
            )

    async def revisions(
        self, kind: RegistryKind, identity: UUID, after: UUID | None = None, limit: int = 50
    ) -> RegistryPage:
        async with self.sessions() as session:
            row = await self._identity(session, kind, identity)
            statement = select(ConfigurationRevisionModel).where(
                ConfigurationRevisionModel.configuration_id == identity
            )
            if after:
                statement = statement.where(ConfigurationRevisionModel.id > after)
            revisions = list(
                await session.scalars(
                    statement.order_by(ConfigurationRevisionModel.id).limit(limit + 1)
                )
            )
            items = [await self._record(session, row, revision) for revision in revisions[:limit]]
            return RegistryPage(
                items=tuple(items),
                next_after=revisions[limit - 1].id if len(revisions) > limit else None,
            )

    async def _compatible(self, session: AsyncSession, spec: RegistrySpec) -> None:
        if isinstance(spec, ProviderSpec):
            if spec.base_url and spec.base_url not in self.allowed_endpoints:
                raise _problem(
                    422, "endpoint_denied", "Endpoint is not in the server-managed allowlist"
                )
            if spec.retry_policy_revision_id:
                await self._revision(
                    session, spec.retry_policy_revision_id, "retry_policy", active=True
                )
        if isinstance(spec, ModelProfileSpec):
            provider = await self._revision(
                session, spec.provider_revision_id, "provider_connection", active=True
            )
            assert isinstance(provider.spec, ProviderSpec)
            parameter_names = {
                "openai": {"temperature", "top_p", "reasoning_effort"},
                "ollama": {"temperature", "top_p", "seed", "keep_alive"},
                "demo": {"temperature", "top_p", "reasoning_effort", "seed", "keep_alive"},
            }
            if set(spec.parameters) - parameter_names[provider.spec.provider_kind]:
                raise _problem(
                    422,
                    "incompatible_parameters",
                    "Model parameters are not supported by the configured provider",
                )
            if provider.spec.locality != spec.locality:
                raise _problem(
                    422, "incompatible_locality", "Model and provider locality must agree"
                )
        if isinstance(spec, WorkerSpec):
            for revision_id in spec.model_binding.allowed_profile_revision_ids:
                profile = await self._revision(session, revision_id, "model_profile", active=True)
                await self._compatible(session, profile.spec)
        if isinstance(spec, RoutePolicySpec):
            for candidate in spec.candidates:
                profile = await self._revision(
                    session, candidate.profile_revision_id, "model_profile", active=True
                )
                assert isinstance(profile.spec, ModelProfileSpec)
                await self._compatible(session, profile.spec)
                capabilities = set(profile.spec.capabilities)
                for capability in ("structured_json", "tool_calls", "streaming"):
                    if getattr(profile.spec, capability):
                        capabilities.add(capability)
                if not set(spec.required_capabilities) <= capabilities or not set(
                    spec.purposes
                ) <= set(profile.spec.purposes):
                    raise _problem(
                        422,
                        "incompatible_profile",
                        "Candidate lacks route capabilities or purposes",
                    )
                provider = await self._revision(
                    session, profile.spec.provider_revision_id, "provider_connection", active=True
                )
                assert isinstance(provider.spec, ProviderSpec)
                if profile.spec.locality == "remote" and not spec.allow_remote:
                    raise _problem(
                        422,
                        "incompatible_egress",
                        "Remote candidate requires explicit route permission",
                    )

    async def _audit(
        self,
        session: AsyncSession,
        kind: RegistryKind,
        identity: UUID,
        revision_id: UUID,
        actor_id: UUID,
        correlation_id: str,
        action: str,
    ) -> None:
        await self.writer.append(
            session,
            EventIntent(
                occurred_at=datetime.now(UTC),
                type=f"config.{action}",
                severity=EventSeverity.INFO,
                mode=EventMode.REAL,
                visibility=EventVisibility.OWNER,
                source=EventSource(kind="api", name="registry", instance_id=self.instance_id),
                correlation_id=correlation_id,
                data={
                    "configuration_id": str(identity),
                    "revision_id": str(revision_id),
                    "kind": kind,
                    "actor_id": str(actor_id),
                    "action": action,
                },
            ),
        )

    async def write(
        self,
        kind: RegistryKind,
        body: RegistryWrite,
        *,
        actor_id: UUID,
        correlation_id: str,
        configuration_id: UUID | None = None,
    ) -> RegistryRecord:
        if body.spec.kind != kind:
            raise _problem(422, "kind_mismatch", "Configuration kind does not match the route")
        public = body.model_dump(mode="json", exclude={"secret_ref", "deployment_ref"})
        _safe_strings(public)
        if body.secret_ref and (
            not isinstance(body.spec, ProviderSpec) or body.spec.provider_kind == "demo"
        ):
            raise _problem(422, "invalid_secret", "This configuration cannot use a credential")
        if body.clear_secret and body.secret_ref:
            raise _problem(422, "invalid_secret", "Credential update is ambiguous")
        if body.deployment_ref and (
            not isinstance(body.spec, WorkerSpec) or body.spec.adapter_kind == "demo"
        ):
            raise _problem(
                422, "invalid_deployment", "This configuration cannot use a deployment locator"
            )
        # Every user-visible field is credential checked, including the opaque locator text.
        for locator in (body.secret_ref, body.deployment_ref):
            if locator:
                _safe_strings(locator)
        digest = _digest(body.model_dump(mode="json"))
        async with self.sessions.begin() as session:
            await self._lock(session)
            scope = f"registry:{actor_id}:{kind}:{configuration_id or 'create'}"
            try:
                idem, fresh = await IdempotencyRepository().begin(
                    session, scope=scope, key=body.idempotency_key, request_digest=digest
                )
            except IdempotencyConflictError:
                raise _problem(
                    409, "idempotency_conflict", "Idempotency key was reused with changed input"
                ) from None
            if not fresh:
                return RegistryRecord.model_validate(idem.response_json)
            await self._compatible(session, body.spec)
            previous_private = None
            now = datetime.now(UTC)
            if configuration_id is None:
                if body.expected_version != 0:
                    raise _problem(
                        409, "version_conflict", "New configurations require version zero"
                    )
                if await session.scalar(
                    select(ConfigurationModel.id).where(
                        ConfigurationModel.kind == kind, ConfigurationModel.key == body.key
                    )
                ):
                    raise _problem(409, "duplicate_key", "Configuration key is already in use")
                identity = ConfigurationModel(
                    id=uuid7(), kind=kind, key=body.key, version=0, created_at=now
                )
                session.add(identity)
            else:
                identity = await self._identity(session, kind, configuration_id, lock=True)
                if body.key != identity.key:
                    raise _problem(422, "immutable_key", "Configuration keys are immutable")
                if identity.version != body.expected_version:
                    raise _problem(
                        409, "version_conflict", "Configuration has changed; reload before saving"
                    )
                if identity.current_revision_id:
                    previous_private = await session.get(
                        ConfigurationPrivateRefModel, identity.current_revision_id
                    )
            secret = (
                None
                if body.clear_secret
                else body.secret_ref or (previous_private.secret_ref if previous_private else None)
            )
            deployment = body.deployment_ref or (
                previous_private.deployment_ref if previous_private else None
            )
            if isinstance(body.spec, WorkerSpec) and body.spec.adapter_kind == "demo":
                deployment = None
            if isinstance(body.spec, ProviderSpec) and body.spec.provider_kind == "demo" and secret:
                raise _problem(422, "invalid_secret", "Clear the credential before selecting DEMO")
            spec = body.spec.model_dump(mode="json")
            if isinstance(body.spec, WorkerSpec):
                spec["deployment_configured"] = bool(deployment)
                label = body.spec.execution_host_label
                if re.search(
                    r"(?:[/\\]|\b\d{1,3}(?:\.\d{1,3}){3}\b|[a-z0-9-]+\.[a-z]{2,}\b|@|:)",
                    label,
                    re.I,
                ):
                    spec["execution_host_label"] = "Server-managed execution host"
            envelope = {
                "spec": spec,
                "display_name": body.display_name,
                "description": body.description,
                "enabled": body.enabled,
                "archived": body.archived,
            }
            identity.display_name = body.display_name
            identity.description = body.description
            identity.enabled = body.enabled
            identity.archived_at = now if body.archived else None
            identity.version += 1
            identity.updated_at = now
            revision = ConfigurationRevisionModel(
                id=uuid7(),
                configuration_id=identity.id,
                revision=identity.version,
                schema_version="1.0",
                spec_json=envelope,
                content_hash=_digest(
                    {
                        "kind": kind,
                        "key": identity.key,
                        "revision": identity.version,
                        "schema_version": "1.0",
                        "spec": envelope,
                    }
                ),
                created_by=actor_id,
                created_at=now,
            )
            await session.flush()
            session.add(revision)
            await session.flush()
            identity.current_revision_id = revision.id
            session.add(
                ConfigurationPrivateRefModel(
                    revision_id=revision.id, secret_ref=secret, deployment_ref=deployment
                )
            )
            await session.flush()
            result = await self._record(session, identity, revision)
            await self._audit(
                session,
                kind,
                identity.id,
                revision.id,
                actor_id,
                correlation_id,
                "created" if configuration_id is None else "revised",
            )
            idem.state = "completed"
            idem.response_json = result.model_dump(mode="json")
            idem.response_status = 200
            idem.completed_at = now
            return result

    async def validate(
        self,
        kind: RegistryKind,
        identity: UUID,
        *,
        idempotency_key: str,
        actor_id: UUID,
        correlation_id: str,
    ) -> ValidationReport:
        _safe_strings(idempotency_key)
        async with self.sessions.begin() as session:
            await self._lock(session)
            row = await self._identity(session, kind, identity, lock=True)
            if row.current_revision_id is None:
                raise _problem(503, "unavailable", "Configuration has no current revision")
            try:
                idem, fresh = await IdempotencyRepository().begin(
                    session,
                    scope=f"validate:{actor_id}:{identity}",
                    key=idempotency_key,
                    request_digest=_digest({"id": str(identity)}),
                )
            except IdempotencyConflictError:
                raise _problem(409, "idempotency_conflict", "Idempotency key conflicts") from None
            if not fresh:
                return ValidationReport.model_validate(idem.response_json)
            record = await self._revision(session, row.current_revision_id)
            issues: list[str] = []
            try:
                await self._compatible(session, record.spec)
            except ApiProblemError:
                issues.append("Configuration references or endpoint policy require attention")
            if record.secret_status == "missing":
                issues.append("A server-managed credential reference is required")
            if (
                isinstance(record.spec, WorkerSpec)
                and record.spec.adapter_kind != "demo"
                and not record.spec.deployment_configured
            ):
                issues.append("A server-managed deployment reference is required")
            if not record.enabled or record.archived:
                issues.append("Configuration is disabled or archived")
            demo = isinstance(record.spec, ProviderSpec) and record.spec.provider_kind == "demo"
            report = ValidationReport(
                valid=not issues,
                health="misconfigured" if issues else "unknown",
                issues=tuple(issues),
                network_checked=False,
                demo=demo,
            )
            if isinstance(record.spec, ProviderSpec):
                health = await session.get(ProviderHealthModel, record.revision_id)
                if health is None:
                    health = ProviderHealthModel(revision_id=record.revision_id)
                    session.add(health)
                health.status = report.health
                health.observed_at = datetime.now(UTC)
            await self._audit(
                session, kind, identity, record.revision_id, actor_id, correlation_id, "validated"
            )
            idem.state = "completed"
            idem.response_json = report.model_dump(mode="json")
            idem.response_status = 200
            idem.completed_at = datetime.now(UTC)
            return report
