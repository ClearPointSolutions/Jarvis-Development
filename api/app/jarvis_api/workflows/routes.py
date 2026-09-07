"""Workflow CRUD and publication, owner-only and protected by the M2 boundary."""

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Query, Request

from jarvis_api.auth.dependencies import CsrfPrincipal, CurrentPrincipal
from jarvis_api.auth.service import AuthPrincipal
from jarvis_api.errors import ApiProblemError, request_id
from jarvis_api.workflows.service import WorkflowService
from jarvis_contracts.workflow_api import (
    WorkflowArchiveRequest,
    WorkflowCommand,
    WorkflowCreateRequest,
    WorkflowDocument,
    WorkflowDraftWrite,
    WorkflowNewDraft,
    WorkflowTemplatePage,
    WorkflowTemplateRecord,
    WorkflowValidateRequest,
    WorkflowValidationReport,
    WorkflowVersionPage,
)
from jarvis_contracts.workflow_nodes import NodeTypePage, node_type_page

router = APIRouter(prefix="/api/v1/workflow-templates", tags=["workflows"])


def service(request: Request, principal: AuthPrincipal) -> WorkflowService:
    if principal.role != "owner":
        raise ApiProblemError(403, "workflow.forbidden", "Owner access is required")
    return cast(WorkflowService, request.app.state.workflow_service)


@router.get("", response_model=WorkflowTemplatePage, operation_id="list_workflows")
async def list_workflows(
    request: Request,
    principal: CurrentPrincipal,
    after: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> WorkflowTemplatePage:
    return await service(request, principal).list_templates(principal.user_id, after, limit)


@router.post("", response_model=WorkflowDocument, operation_id="create_workflow")
async def create_workflow(
    request: Request, body: WorkflowCreateRequest, principal: CsrfPrincipal
) -> WorkflowDocument:
    return await service(request, principal).create(body, principal.user_id, request_id(request))


@router.get("/node-types", response_model=NodeTypePage, operation_id="workflow_node_types")
async def workflow_node_types(request: Request, principal: CurrentPrincipal) -> NodeTypePage:
    service(request, principal)
    return node_type_page()


@router.get("/{id}", response_model=WorkflowDocument, operation_id="get_workflow")
async def get_workflow(request: Request, id: UUID, principal: CurrentPrincipal) -> WorkflowDocument:
    return await service(request, principal).get(id, principal.user_id)


@router.put("/{id}", response_model=WorkflowTemplateRecord, operation_id="archive_workflow")
async def archive_workflow(
    request: Request, id: UUID, body: WorkflowArchiveRequest, principal: CsrfPrincipal
) -> WorkflowTemplateRecord:
    return await service(request, principal).archive(
        id, body, principal.user_id, request_id(request)
    )


@router.post("/{id}/draft", response_model=WorkflowDocument, operation_id="create_workflow_draft")
async def create_workflow_draft(
    request: Request, id: UUID, body: WorkflowNewDraft, principal: CsrfPrincipal
) -> WorkflowDocument:
    return await service(request, principal).new_draft(
        id, body, principal.user_id, request_id(request)
    )


@router.put("/{id}/draft", response_model=WorkflowDocument, operation_id="save_workflow_draft")
async def save_workflow_draft(
    request: Request, id: UUID, body: WorkflowDraftWrite, principal: CsrfPrincipal
) -> WorkflowDocument:
    return await service(request, principal).save(id, body, principal.user_id, request_id(request))


@router.post(
    "/{id}/validate",
    response_model=WorkflowValidationReport,
    operation_id="validate_workflow_draft",
)
async def validate_workflow_draft(
    request: Request, id: UUID, body: WorkflowValidateRequest, principal: CsrfPrincipal
) -> WorkflowValidationReport:
    return await service(request, principal).validate(
        id, body, principal.user_id, request_id(request)
    )


@router.post("/{id}/publish", response_model=WorkflowDocument, operation_id="publish_workflow")
async def publish_workflow(
    request: Request, id: UUID, body: WorkflowCommand, principal: CsrfPrincipal
) -> WorkflowDocument:
    return await service(request, principal).publish(
        id, body, principal.user_id, request_id(request)
    )


@router.get(
    "/{id}/versions", response_model=WorkflowVersionPage, operation_id="list_workflow_versions"
)
async def list_workflow_versions(
    request: Request,
    id: UUID,
    principal: CurrentPrincipal,
    after: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> WorkflowVersionPage:
    return await service(request, principal).versions(id, principal.user_id, after, limit)


@router.get(
    "/{id}/versions/{version_id}",
    response_model=WorkflowDocument,
    operation_id="get_workflow_version",
)
async def get_workflow_version(
    request: Request, id: UUID, version_id: UUID, principal: CurrentPrincipal
) -> WorkflowDocument:
    return await service(request, principal).get(id, principal.user_id, version_id=version_id)


@router.get(
    "/{id}/published", response_model=WorkflowDocument, operation_id="get_published_workflow"
)
async def get_published_workflow(
    request: Request, id: UUID, principal: CurrentPrincipal
) -> WorkflowDocument:
    return await service(request, principal).get(id, principal.user_id, published=True)
