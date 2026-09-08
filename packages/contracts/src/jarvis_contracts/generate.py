"""Generate the authoritative JSON Schema consumed by TypeScript."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from jarvis_contracts.api import (
    ApiErrorResponse,
    EventPage,
    EventStreamReset,
    LivenessResponse,
    LoginRequest,
    LogoutResponse,
    ReadinessResponse,
    RunEventSnapshotResponse,
    SessionResponse,
)
from jarvis_contracts.base import ContractModel
from jarvis_contracts.commands import IdempotencyContract, RunCommandReceipt, RunCommandRequest
from jarvis_contracts.configuration import ConfigurationRevision, RunConfigurationSnapshot
from jarvis_contracts.entities import (
    ArtifactMetadata,
    Effect,
    Job,
    Lease,
    Run,
    RunCommand,
    Task,
    TaskAttempt,
)
from jarvis_contracts.events import NewEvent, NormalizedEvent
from jarvis_contracts.failures import (
    FailureClassification,
    FailureEvidence,
    FailureRecord,
    RetryPolicySpec,
)
from jarvis_contracts.registry import (
    AccountingPage,
    ProviderChunk,
    ProviderRequest,
    ProviderResult,
    RegistryPage,
    RegistryRecord,
    RegistryWrite,
    RoutePreviewRequest,
    RouteResolution,
    ValidationReport,
)
from jarvis_contracts.runtime_api import (
    CommandPage,
    JobCreate,
    JobPage,
    NodePage,
    ProjectCreate,
    ProjectPage,
    RunControl,
    RunPage,
)
from jarvis_contracts.workflow import WorkflowSpec, WorkflowVersionContract
from jarvis_contracts.workflow_api import (
    WorkflowArchiveRequest,
    WorkflowCommand,
    WorkflowCreateRequest,
    WorkflowDocument,
    WorkflowDraftWrite,
    WorkflowNewDraft,
    WorkflowResolvedSnapshot,
    WorkflowTemplatePage,
    WorkflowValidateRequest,
    WorkflowValidationReport,
    WorkflowVersionPage,
)
from jarvis_contracts.workflow_nodes import (
    ApprovalConfig,
    ArchitectConfig,
    DispatchConfig,
    FanoutConfig,
    FinalizeConfig,
    IntegrateConfig,
    JoinConfig,
    NodeTypePage,
    OrganizerConfig,
    PublishConfig,
    ReviewerConfig,
    RouterConfig,
    VerifyConfig,
    WorkerConfig,
)


class JarvisContractBundle(ContractModel):
    runtime_commands: CommandPage
    runtime_nodes: NodePage
    project_create: ProjectCreate | None = None
    project_page: ProjectPage | None = None
    job_create: JobCreate | None = None
    job_page: JobPage | None = None
    run_control: RunControl | None = None
    run_page: RunPage | None = None
    workflow_create: WorkflowCreateRequest | None = None
    workflow_command: WorkflowCommand | None = None
    workflow_draft_write: WorkflowDraftWrite | None = None
    workflow_validate_request: WorkflowValidateRequest | None = None
    workflow_new_draft: WorkflowNewDraft | None = None
    workflow_archive_request: WorkflowArchiveRequest | None = None
    workflow_document: WorkflowDocument | None = None
    workflow_template_page: WorkflowTemplatePage | None = None
    workflow_version_page: WorkflowVersionPage | None = None
    workflow_validation: WorkflowValidationReport | None = None
    workflow_snapshot: WorkflowResolvedSnapshot | None = None
    workflow_node_types: NodeTypePage | None = None
    workflow_node_configs: (
        OrganizerConfig
        | ArchitectConfig
        | DispatchConfig
        | WorkerConfig
        | VerifyConfig
        | ReviewerConfig
        | IntegrateConfig
        | RouterConfig
        | FanoutConfig
        | JoinConfig
        | ApprovalConfig
        | PublishConfig
        | FinalizeConfig
        | None
    ) = None
    registry_write: RegistryWrite | None = None
    registry_record: RegistryRecord | None = None
    registry_page: RegistryPage | None = None
    validation_report: ValidationReport | None = None
    route_preview: RoutePreviewRequest | None = None
    route_resolution: RouteResolution | None = None
    provider_request: ProviderRequest | None = None
    provider_result: ProviderResult | None = None
    provider_chunk: ProviderChunk | None = None
    accounting_page: AccountingPage | None = None
    api_error: ApiErrorResponse | None = None
    login_request: LoginRequest | None = None
    session_response: SessionResponse | None = None
    logout_response: LogoutResponse | None = None
    liveness_response: LivenessResponse | None = None
    readiness_response: ReadinessResponse | None = None
    event_page: EventPage | None = None
    event_stream_reset: EventStreamReset | None = None
    run_event_snapshot: RunEventSnapshotResponse | None = None
    workflow_spec: WorkflowSpec | None = None
    workflow_version: WorkflowVersionContract | None = None
    new_event: NewEvent | None = None
    normalized_event: NormalizedEvent | None = None
    failure_evidence: FailureEvidence | None = None
    failure_classification: FailureClassification | None = None
    failure_record: FailureRecord | None = None
    retry_policy: RetryPolicySpec | None = None
    run_command_request: RunCommandRequest | None = None
    run_command_receipt: RunCommandReceipt | None = None
    idempotency: IdempotencyContract | None = None
    configuration_revision: ConfigurationRevision | None = None
    run_configuration_snapshot: RunConfigurationSnapshot | None = None
    job: Job | None = None
    run: Run | None = None
    task: Task | None = None
    task_attempt: TaskAttempt | None = None
    run_command: RunCommand | None = None
    lease: Lease | None = None
    effect: Effect | None = None
    artifact: ArtifactMetadata | None = None


def schema_bytes() -> bytes:
    schema = JarvisContractBundle.model_json_schema(by_alias=True)
    schema["$id"] = "https://jarvis.local/contracts/v1/jarvis-contracts.schema.json"
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    return (json.dumps(schema, indent=2, sort_keys=True) + "\n").encode()


def output_path() -> Path:
    return Path(__file__).resolve().parents[2] / "generated" / "jarvis-contracts.schema.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    path = output_path()
    expected = schema_bytes()
    if args.check:
        if not path.exists() or path.read_bytes() != expected:
            raise SystemExit("generated JSON Schema is stale; run jarvis-contracts")
        print("Python contract schema: current")
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(expected)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
