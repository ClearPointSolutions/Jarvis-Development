"""Transactional canonical workflow drafts, publications and immutable bindings."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import JsonValue, ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from uuid6 import uuid7

from jarvis_api.errors import ApiProblemError
from jarvis_api.events.normalizer import EventIntent
from jarvis_api.registry.service import RegistryService, _safe_strings
from jarvis_contracts.base import canonical_json, sha256_digest
from jarvis_contracts.enums import EventMode, EventSeverity, EventVisibility
from jarvis_contracts.events import EventSource
from jarvis_contracts.registry import ModelProfileSpec, ProviderSpec, RoutePolicySpec, WorkerSpec
from jarvis_contracts.workflow import (
    COMPILER_VERSION,
    MAX_JSON_DEPTH,
    MAX_WORKFLOW_BYTES,
    WorkflowSpec,
)
from jarvis_contracts.workflow_api import (
    WorkflowArchiveRequest,
    WorkflowAuditData,
    WorkflowCommand,
    WorkflowCreateRequest,
    WorkflowDocument,
    WorkflowDraftWrite,
    WorkflowIssue,
    WorkflowLayout,
    WorkflowNewDraft,
    WorkflowResolvedRevision,
    WorkflowResolvedSnapshot,
    WorkflowTemplatePage,
    WorkflowTemplateRecord,
    WorkflowValidateRequest,
    WorkflowValidationReport,
    WorkflowVersionPage,
    WorkflowVersionRecord,
)
from jarvis_orchestrator.workflows import normalize_workflow, validate_workflow
from jarvis_orchestrator.workflows.validation import effective_policy
from jarvis_persistence.models import (
    IdempotencyRecordModel,
    WorkflowRevisionReferenceModel,
    WorkflowTemplateModel,
    WorkflowVersionModel,
)
from jarvis_persistence.repositories import IdempotencyConflictError, IdempotencyRepository


def problem(status: int, code: str, message: str, **details: Any) -> ApiProblemError:
    return ApiProblemError(status, f"workflow.{code}", message, details=details)


def safe_workflow_input(value: dict[str, JsonValue]) -> None:
    """Bound every JSON dimension before recursive schema/graph work."""
    stack: list[tuple[JsonValue, int]] = [(value, 0)]
    count = 0
    while stack:
        item, depth = stack.pop()
        count += 1
        if depth > MAX_JSON_DEPTH or count > 100000:
            raise problem(422, "resource_limit", "Workflow JSON nesting or item limit exceeded")
        if isinstance(item, dict):
            stack.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            stack.extend((child, depth + 1) for child in item)
        elif isinstance(item, float) and not math.isfinite(item):
            raise problem(422, "unsafe_input", "Workflow numbers must be finite")
        elif isinstance(item, str) and (item.startswith("secret:") or item.startswith("file:")):
            raise problem(422, "unsafe_input", "Private server references are not workflow data")
    if len(canonical_json(value)) > MAX_WORKFLOW_BYTES:
        raise problem(413, "resource_limit", "Workflow JSON exceeds 1 MiB")
    try:
        _safe_strings(value)
    except ApiProblemError:
        raise problem(422, "unsafe_input", "Credential-like workflow input is rejected") from None


def template_record(row: WorkflowTemplateModel) -> WorkflowTemplateRecord:
    return WorkflowTemplateRecord(
        id=row.id,
        key=row.key,
        name=row.name,
        description=row.description,
        version=row.version,
        archived=row.archived_at is not None,
        current_draft_version_id=row.current_draft_version_id,
        current_published_version_id=row.current_published_version_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def version_record(row: WorkflowVersionModel) -> WorkflowVersionRecord:
    try:
        spec = WorkflowSpec.model_validate(row.spec_json)
        layout = WorkflowLayout.model_validate(row.layout_json)
        return WorkflowVersionRecord(
            id=row.id,
            workflow_template_id=row.workflow_template_id,
            version=row.version,
            spec=spec,
            layout=layout,
            content_hash=row.content_hash,
            compiler_version=row.compiler_version,
            published=row.published_at is not None,
            created_at=row.created_at,
            published_at=row.published_at,
            snapshot_hash=row.snapshot_hash,
        )
    except ValidationError:
        raise problem(
            422, "unsupported_version", "Workflow version predates the executable schema"
        ) from None


class WorkflowService:
    def __init__(
        self, sessions: async_sessionmaker[AsyncSession], registry: RegistryService
    ) -> None:
        self.sessions = sessions
        self.registry = registry

    async def _template(
        self, session: AsyncSession, identity: UUID, actor: UUID
    ) -> WorkflowTemplateModel:
        row = await session.scalar(
            select(WorkflowTemplateModel).where(
                WorkflowTemplateModel.id == identity,
                WorkflowTemplateModel.owner_user_id == actor,
            )
        )
        if row is None:
            raise problem(404, "not_found", "Workflow was not found")
        return row

    async def _version(
        self, session: AsyncSession, template: WorkflowTemplateModel, identity: UUID | None
    ) -> WorkflowVersionModel:
        row = await session.get(WorkflowVersionModel, identity) if identity else None
        if row is None or row.workflow_template_id != template.id:
            raise problem(404, "version_not_found", "Workflow version was not found")
        return row

    async def _document(
        self, session: AsyncSession, row: WorkflowTemplateModel, version_id: UUID | None = None
    ) -> WorkflowDocument:
        version = await self._version(
            session,
            row,
            version_id or row.current_draft_version_id or row.current_published_version_id,
        )
        return WorkflowDocument(template=template_record(row), version=version_record(version))

    async def list_templates(
        self, actor: UUID, after: UUID | None = None, limit: int = 50
    ) -> WorkflowTemplatePage:
        async with self.sessions() as session:
            query = select(WorkflowTemplateModel).where(
                WorkflowTemplateModel.owner_user_id == actor
            )
            if after:
                query = query.where(WorkflowTemplateModel.id > after)
            rows = list(
                await session.scalars(query.order_by(WorkflowTemplateModel.id).limit(limit + 1))
            )
            return WorkflowTemplatePage(
                items=tuple(template_record(r) for r in rows[:limit]),
                next_after=rows[limit - 1].id if len(rows) > limit else None,
            )

    async def get(
        self,
        identity: UUID,
        actor: UUID,
        *,
        version_id: UUID | None = None,
        published: bool = False,
    ) -> WorkflowDocument:
        async with self.sessions() as session:
            row = await self._template(session, identity, actor)
            if published:
                if row.current_published_version_id is None:
                    raise problem(404, "version_not_found", "Workflow has no published version")
                version_id = row.current_published_version_id
            return await self._document(session, row, version_id)

    async def versions(
        self, identity: UUID, actor: UUID, after: UUID | None = None, limit: int = 50
    ) -> WorkflowVersionPage:
        async with self.sessions() as session:
            await self._template(session, identity, actor)
            query = select(WorkflowVersionModel).where(
                WorkflowVersionModel.workflow_template_id == identity
            )
            if after:
                query = query.where(WorkflowVersionModel.id > after)
            rows = list(
                await session.scalars(query.order_by(WorkflowVersionModel.id).limit(limit + 1))
            )
            return WorkflowVersionPage(
                items=tuple(version_record(r) for r in rows[:limit]),
                next_after=rows[limit - 1].id if len(rows) > limit else None,
            )

    async def _audit(
        self,
        session: AsyncSession,
        row: WorkflowTemplateModel,
        actor: UUID,
        correlation: str,
        action: Literal["created", "revised", "validated", "published", "archived", "restored"],
        version: WorkflowVersionModel | None = None,
        valid: bool | None = None,
        observed_hash: str | None = None,
    ) -> None:
        data = WorkflowAuditData(
            template_id=row.id,
            version_id=version.id if version else None,
            actor_id=actor,
            action=action,
            valid=valid,
            content_hash=version.content_hash if version else observed_hash,
        )
        await self.registry.writer.append(
            session,
            EventIntent(
                occurred_at=datetime.now(UTC),
                type=f"workflow.{action}",
                severity=EventSeverity.INFO,
                mode=EventMode.REAL,
                visibility=EventVisibility.OWNER,
                source=EventSource(
                    kind="api", name="workflow-studio", instance_id=self.registry.instance_id
                ),
                correlation_id=correlation,
                data=data.model_dump(mode="json"),
            ),
        )

    async def _idempotency(
        self,
        session: AsyncSession,
        body: WorkflowCommand | WorkflowCreateRequest,
        actor: UUID,
        action: str,
        identity: UUID | None,
    ) -> tuple[IdempotencyRecordModel, bool]:
        try:
            return await IdempotencyRepository().begin(
                session,
                scope=f"workflow:{actor}:{action}:{identity or 'new'}",
                key=body.idempotency_key,
                request_digest=sha256_digest(body),
            )
        except IdempotencyConflictError:
            raise problem(
                409, "idempotency_conflict", "Idempotency key was reused with changed input"
            ) from None

    @staticmethod
    def _expected(
        row: WorkflowTemplateModel, body: WorkflowCommand, *, allow_archived: bool = False
    ) -> None:
        if row.version != body.expected_version:
            raise problem(409, "version_conflict", "Workflow changed; reopen it before saving")
        if row.archived_at and not allow_archived:
            raise problem(409, "archived", "Restore the workflow before editing or publishing")

    @staticmethod
    def _touch(row: WorkflowTemplateModel) -> None:
        row.version += 1
        row.updated_at = datetime.now(UTC)

    async def _new_version(
        self,
        session: AsyncSession,
        row: WorkflowTemplateModel,
        spec: WorkflowSpec,
        layout: WorkflowLayout,
    ) -> WorkflowVersionModel:
        latest = await session.scalar(
            select(func.max(WorkflowVersionModel.version)).where(
                WorkflowVersionModel.workflow_template_id == row.id
            )
        )
        version = WorkflowVersionModel(
            id=uuid7(),
            workflow_template_id=row.id,
            version=(latest or 0) + 1,
            spec_version=spec.spec_version,
            compiler_version=COMPILER_VERSION,
            spec_json=spec.canonical_payload(),
            layout_json=layout.model_dump(mode="json"),
            content_hash=spec.content_hash,
        )
        session.add(version)
        await session.flush()
        row.current_draft_version_id = version.id
        return version

    async def create(
        self, body: WorkflowCreateRequest, actor: UUID, correlation: str
    ) -> WorkflowDocument:
        safe_workflow_input(body.model_dump(mode="json"))
        async with self.sessions.begin() as session:
            await self.registry._lock(session)
            idem, fresh = await self._idempotency(session, body, actor, "create", None)
            if not fresh:
                return WorkflowDocument.model_validate(idem.response_json)
            if await session.scalar(
                select(WorkflowTemplateModel.id).where(WorkflowTemplateModel.key == body.key)
            ):
                raise problem(409, "duplicate_key", "Workflow key is already in use")
            row = WorkflowTemplateModel(
                id=uuid7(),
                owner_user_id=actor,
                key=body.key,
                name=body.name,
                description=body.description,
                version=1,
            )
            session.add(row)
            await session.flush()
            spec = normalize_workflow(
                WorkflowSpec.model_validate(
                    {
                        "key": body.key,
                        "name": body.name,
                        "description": body.description,
                        "entrypoint": "finish",
                        "nodes": [
                            {"id": "finish", "type": "finalize", "label": "Finish", "config": {}}
                        ],
                        "edges": [],
                        "outputs": {"result_path": "$.final"},
                    }
                )
            )
            version = await self._new_version(session, row, spec, WorkflowLayout())
            row.updated_at = datetime.now(UTC)
            await session.flush()
            await self._audit(session, row, actor, correlation, "created", version)
            result = await self._document(session, row)
            idem.response_json = result.model_dump(mode="json")
            return result

    async def new_draft(
        self, identity: UUID, body: WorkflowNewDraft, actor: UUID, correlation: str
    ) -> WorkflowDocument:
        safe_workflow_input(body.model_dump(mode="json"))
        async with self.sessions.begin() as session:
            await self.registry._lock(session)
            row = await self._template(session, identity, actor)
            idem, fresh = await self._idempotency(session, body, actor, "new-draft", identity)
            if not fresh:
                return WorkflowDocument.model_validate(idem.response_json)
            self._expected(row, body)
            if row.current_draft_version_id:
                raise problem(
                    409, "draft_exists", "Open the existing draft before creating another"
                )
            source = await self._version(
                session, row, body.source_version_id or row.current_published_version_id
            )
            old = version_record(source)
            version = await self._new_version(session, row, old.spec, old.layout)
            self._touch(row)
            await session.flush()
            await self._audit(session, row, actor, correlation, "revised", version)
            result = await self._document(session, row)
            idem.response_json = result.model_dump(mode="json")
            return result

    async def save(
        self, identity: UUID, body: WorkflowDraftWrite, actor: UUID, correlation: str
    ) -> WorkflowDocument:
        safe_workflow_input(body.model_dump(mode="json", by_alias=True))
        if set(body.layout.nodes) - {n.id for n in body.spec.nodes}:
            raise problem(422, "invalid_layout", "Layout references an unknown node")
        async with self.sessions.begin() as session:
            await self.registry._lock(session)
            row = await self._template(session, identity, actor)
            idem, fresh = await self._idempotency(session, body, actor, "save", identity)
            if not fresh:
                return WorkflowDocument.model_validate(idem.response_json)
            self._expected(row, body)
            if body.spec.key != row.key or body.spec.spec_version != "1.1":
                raise problem(
                    422, "invalid_identity", "Keep the template key and supported spec version"
                )
            version = await self._version(session, row, row.current_draft_version_id)
            if version.published_at:
                raise problem(
                    409, "immutable", "Published versions are immutable; create a new draft"
                )
            # Keep invalid semantic drafts for correction; publication owns executable validation.
            version.spec_json = body.spec.canonical_payload()
            version.layout_json = body.layout.model_dump(mode="json")
            version.content_hash = body.spec.content_hash
            row.name = body.spec.name
            row.description = body.spec.description
            self._touch(row)
            await session.flush()
            await self._audit(session, row, actor, correlation, "revised", version)
            result = await self._document(session, row)
            idem.response_json = result.model_dump(mode="json")
            return result

    async def _resolve(
        self, session: AsyncSession, spec: WorkflowSpec
    ) -> tuple[WorkflowResolvedSnapshot, list[WorkflowIssue]]:
        revisions: dict[UUID, WorkflowResolvedRevision] = {}
        issues: list[WorkflowIssue] = []

        async def visit(revision_id: UUID, node_id: str, expected: str | None = None) -> None:
            if revision_id in revisions:
                if expected and revisions[revision_id].spec.kind != expected:
                    issues.append(
                        WorkflowIssue(
                            code="reference.kind",
                            message="Revision kind is incompatible",
                            node_id=node_id,
                        )
                    )
                return
            try:
                record = await self.registry._revision(session, revision_id, active=True)
            except ApiProblemError:
                issues.append(
                    WorkflowIssue(
                        code="reference.unavailable",
                        message="Referenced revision is missing, disabled or archived",
                        node_id=node_id,
                    )
                )
                return
            if expected and record.spec.kind != expected:
                issues.append(
                    WorkflowIssue(
                        code="reference.kind",
                        message="Revision kind is incompatible",
                        node_id=node_id,
                    )
                )
                return
            revisions[revision_id] = WorkflowResolvedRevision(
                revision_id=record.revision_id,
                configuration_id=record.id,
                key=record.key,
                revision=record.revision,
                display_name=record.display_name,
                description=record.description,
                enabled=record.enabled,
                archived=record.archived,
                spec=record.spec,
                content_hash=record.content_hash,
            )
            child = record.spec
            if isinstance(child, RoutePolicySpec):
                for candidate in child.candidates:
                    await visit(candidate.profile_revision_id, node_id, "model_profile")
            elif isinstance(child, ModelProfileSpec):
                await visit(child.provider_revision_id, node_id, "provider_connection")
            elif isinstance(child, WorkerSpec):
                for profile_id in child.model_binding.allowed_profile_revision_ids:
                    await visit(profile_id, node_id, "model_profile")
            elif isinstance(child, ProviderSpec) and child.retry_policy_revision_id:
                await visit(child.retry_policy_revision_id, node_id, "retry_policy")

        for node in spec.nodes:
            policy = effective_policy(spec, node)
            if policy.worker_selector:
                await visit(policy.worker_selector.revision_id, node.id, "worker")
            for reference, kind in (
                (policy.model_route_ref, "route_policy"),
                (policy.retry_policy_ref, "retry_policy"),
                (policy.permission_policy_ref, "permission_policy"),
            ):
                if reference:
                    await visit(reference, node.id, kind)
        return WorkflowResolvedSnapshot(
            workflow_content_hash=spec.content_hash, revisions=tuple(revisions.values())
        ), issues

    async def _evaluate(
        self, session: AsyncSession, raw: dict[str, JsonValue], layout_raw: dict[str, JsonValue]
    ) -> tuple[WorkflowValidationReport, WorkflowSpec | None, WorkflowResolvedSnapshot | None]:
        safe_workflow_input({"spec": raw, "layout": layout_raw})
        try:
            spec = normalize_workflow(WorkflowSpec.model_validate(raw))
        except (ValidationError, ValueError):
            return validate_workflow(raw), None, None
        snapshot, issues = await self._resolve(session, spec)
        report = validate_workflow(spec, snapshot)
        try:
            layout = WorkflowLayout.model_validate(layout_raw)
            for node_id in sorted(set(layout.nodes) - {n.id for n in spec.nodes}):
                issues.append(
                    WorkflowIssue(
                        code="layout.unknown_node",
                        message="Layout references an unknown node",
                        node_id=node_id,
                    )
                )
        except ValidationError:
            issues.append(
                WorkflowIssue(
                    code="layout.invalid",
                    message="Layout must contain bounded finite positions and viewport only",
                    path="layout",
                )
            )
        all_issues = (*report.issues, *issues)
        return (
            WorkflowValidationReport(
                valid=not all_issues,
                issues=all_issues,
                content_hash=spec.content_hash,
                snapshot_hash=snapshot.snapshot_hash,
            ),
            spec,
            snapshot,
        )

    async def validate(
        self, identity: UUID, body: WorkflowValidateRequest, actor: UUID, correlation: str
    ) -> WorkflowValidationReport:
        safe_workflow_input(body.model_dump(mode="json"))
        async with self.sessions.begin() as session:
            await self.registry._lock(session)
            row = await self._template(session, identity, actor)
            idem, fresh = await self._idempotency(session, body, actor, "validate", identity)
            if not fresh:
                return WorkflowValidationReport.model_validate(idem.response_json)
            self._expected(row, body, allow_archived=True)
            report, _, _ = await self._evaluate(session, body.spec, body.layout)
            await self._audit(
                session,
                row,
                actor,
                correlation,
                "validated",
                valid=report.valid,
                observed_hash=report.content_hash,
            )
            idem.response_json = report.model_dump(mode="json")
            return report

    async def publish(
        self, identity: UUID, body: WorkflowCommand, actor: UUID, correlation: str
    ) -> WorkflowDocument:
        safe_workflow_input(body.model_dump(mode="json"))
        async with self.sessions.begin() as session:
            await self.registry._lock(session)
            row = await self._template(session, identity, actor)
            idem, fresh = await self._idempotency(session, body, actor, "publish", identity)
            if not fresh:
                return WorkflowDocument.model_validate(idem.response_json)
            self._expected(row, body)
            version = await self._version(session, row, row.current_draft_version_id)
            if version.published_at:
                raise problem(409, "immutable", "Published versions are immutable")
            report, spec, snapshot = await self._evaluate(
                session, version.spec_json, version.layout_json
            )
            if not report.valid or spec is None or snapshot is None:
                raise problem(
                    422,
                    "validation_failed",
                    "Workflow validation failed",
                    validation=report.model_dump(mode="json"),
                )
            if spec.key != row.key or spec.spec_version != "1.1":
                raise problem(
                    422, "invalid_identity", "Workflow identity or version is unsupported"
                )
            # Persist FK bindings while still a draft; publication freezes both sets.
            for revision in snapshot.revisions:
                session.add(
                    WorkflowRevisionReferenceModel(
                        workflow_version_id=version.id, revision_id=revision.revision_id
                    )
                )
            await session.flush()
            version.spec_json = spec.canonical_payload()
            version.content_hash = spec.content_hash
            version.resolved_snapshot_json = snapshot.model_dump(mode="json")
            version.snapshot_hash = snapshot.snapshot_hash
            version.compiler_version = COMPILER_VERSION
            version.published_at = datetime.now(UTC)
            await session.flush()
            row.current_draft_version_id = None
            row.current_published_version_id = version.id
            self._touch(row)
            await session.flush()
            await self._audit(session, row, actor, correlation, "published", version)
            result = await self._document(session, row, version.id)
            idem.response_json = result.model_dump(mode="json")
            return result

    async def archive(
        self, identity: UUID, body: WorkflowArchiveRequest, actor: UUID, correlation: str
    ) -> WorkflowTemplateRecord:
        safe_workflow_input(body.model_dump(mode="json"))
        async with self.sessions.begin() as session:
            await self.registry._lock(session)
            row = await self._template(session, identity, actor)
            idem, fresh = await self._idempotency(session, body, actor, "archive", identity)
            if not fresh:
                return WorkflowTemplateRecord.model_validate(idem.response_json)
            self._expected(row, body, allow_archived=True)
            row.archived_at = datetime.now(UTC) if body.archived else None
            self._touch(row)
            await session.flush()
            await self._audit(
                session, row, actor, correlation, "archived" if body.archived else "restored"
            )
            result = template_record(row)
            idem.response_json = result.model_dump(mode="json")
            return result
