/* Generated from authoritative Pydantic contracts. Do not edit. */

export type CorrelationId = string;
export type Amount = number | string | null;
export type Currency = string;
export type Status = "exact" | "estimated" | "unknown" | "not_applicable";
export type CreatedAt = string;
export type Demo = boolean;
export type Id = string;
export type LatencyMs = number;
export type NodeId = string | null;
export type Outcome = "completed" | "failed" | "unknown" | "denied" | "require_approval";
export type CachedPerMillion = number | string | null;
export type Currency1 = string;
export type EffectiveAt = string | null;
export type InputPerMillion = number | string | null;
export type OutputPerMillion = number | string | null;
export type Source = string;
export type Status1 = "known" | "unknown" | "not_applicable";
export type ProfileRevisionId = string;
export type ProjectId = string | null;
export type ProviderRevisionId = string;
export type RequestId = string | null;
export type RouteRevisionId = string | null;
export type RunId = string | null;
export type TaskId = string | null;
export type CachedTokens = number | null;
export type InputTokens = number | null;
export type OutputTokens = number | null;
export type Provenance = "exact" | "estimated" | "unknown";
export type TotalTokens = number | null;
export type Items = AccountingRecord[];
export type NextAfter = string | null;
export type Code = string;
export type JsonValue = unknown;
export type Message = string;
export type RequestId1 = string;
export type CreatedAt1 = string;
export type Id1 = string;
export type Kind = string;
export type MediaType = string;
export type RedactionClassification = "public" | "owner" | "sensitive" | "redacted";
export type RunId1 = string | null;
export type Sha256 = string;
export type SizeBytes = number;
export type StorageKey = string;
export type TaskAttemptId = string | null;
export type ConfigurationId = string;
export type ContentHash = string;
export type CreatedAt2 = string;
export type Id2 = string;
export type Key = string;
export type ConfigurationKind =
  | "worker"
  | "provider_connection"
  | "model_profile"
  | "route_policy"
  | "retry_policy"
  | "permission_policy"
  | "branch_policy"
  | "project_settings";
export type Revision = number;
export type SchemaVersion = "1.0";
export type CreatedAt3 = string;
export type ExternalId = string | null;
export type FenceGeneration = number;
export type Id3 = string;
export type IdempotencyKey = string;
export type Kind1 = string;
export type RequestDigest = string;
export type Result = {
  [k: string]: JsonValue;
} | null;
export type RunId2 = string;
export type EffectStatus =
  "prepared" | "dispatched" | "running" | "succeeded" | "failed" | "cancel_requested" | "cancelled" | "unknown";
export type TaskAttemptId1 = string | null;
export type UpdatedAt = string;
export type After = number;
export type HighWatermark = number;
export type ArtifactId = string;
export type Relation = string;
export type ArtifactRefs = ArtifactReference[];
export type EventCategory =
  | "auth"
  | "config"
  | "thread"
  | "job"
  | "run"
  | "graph"
  | "node"
  | "task"
  | "worker"
  | "model"
  | "tool"
  | "file"
  | "command"
  | "test"
  | "review"
  | "git"
  | "approval"
  | "artifact"
  | "failure"
  | "system";
export type CausationEventId = string | null;
export type CorrelationId1 = string;
export type EventId = string;
export type GlobalPosition = number;
export type IdempotencyKey1 = string | null;
export type Message1 = string;
export type EventMode = "real" | "demo";
export type OccurredAt = string;
export type RecordedAt = string;
export type RunSequence = number | null;
export type SchemaVersion1 = "1.0";
export type JobId = string | null;
export type NodeExecutionId = string | null;
export type ProjectId1 = string | null;
export type RunId3 = string | null;
export type TaskAttemptId2 = string | null;
export type TaskId1 = string | null;
export type ThreadId = string | null;
export type WorkflowNodeId = string | null;
export type EventSeverity = "debug" | "info" | "success" | "warning" | "error" | "critical";
export type HostId = string | null;
export type InstanceId = string | null;
export type Kind2 = string;
export type Name = string;
export type SourceSequence = number | null;
export type SpanId = string;
export type TraceId = string;
export type Type = string;
export type EventVisibility = "owner" | "operator" | "internal";
export type Items1 = NormalizedEvent[];
export type NextAfter1 = number | null;
export type EarliestPosition = number | null;
export type LatestPosition = number | null;
export type Reason = "cursor_expired" | "unsupported_schema" | "run_sequence_gap";
export type BudgetScope = string;
export type FailureClass =
  | "code.build_failure"
  | "infrastructure.timeout"
  | "unknown"
  | "code.implementation_failure"
  | "code.test_failure"
  | "code.review_failure"
  | "code.git_conflict"
  | "infrastructure.worker_unavailable"
  | "infrastructure.worker_transport"
  | "infrastructure.service_unavailable"
  | "provider.rate_limited"
  | "provider.transient"
  | "provider.contract_failure"
  | "configuration.invalid"
  | "security.policy_denied"
  | "approval.rejected"
  | "orchestration.runtime_error"
  | "user.cancelled";
export type Code1 = string;
export type ConsumesSemanticAttempt = boolean;
export type Retryable = boolean;
export type Summary = string;
export type Code2 = string;
export type ProviderRateLimited = boolean;
export type ProviderTransient = boolean;
export type SecurityPolicyDenied = boolean;
export type Summary1 = string;
export type UserCancelled = boolean;
export type VerifierFailed = boolean;
export type WorkerTransportFailed = boolean;
export type DetailArtifactId = string | null;
export type Id4 = string;
export type Key1 = string;
export type RequestDigest1 = string;
export type ResponseStatus = number | null;
export type Scope = string;
export type State = "started" | "completed" | "failed";
export type CreatedAt4 = string;
export type Id5 = string;
export type Objective = string;
export type ProjectId2 = string;
export type JobStatus = "draft" | "queued" | "active" | "waiting" | "completed" | "failed" | "blocked" | "cancelled";
export type ThreadId1 = string | null;
export type UpdatedAt1 = string;
export type Version = number;
export type AcquiredAt = string;
export type ExpiresAt = string;
export type Generation = number;
export type Id6 = string;
export type OwnerInstanceId = string;
export type ReleasedAt = string | null;
export type RunId4 = string;
export type Service = "jarvis-api";
export type Status2 = "ok";
export type Version1 = "0.1.0";
export type Password = string;
export type Username = string;
export type Revoked = boolean;
export type ArtifactRefs1 = ArtifactReference[];
export type CausationEventId1 = string | null;
export type CorrelationId2 = string;
export type IdempotencyKey2 = string | null;
export type Message2 = string;
export type OccurredAt1 = string;
export type SchemaVersion2 = "1.0";
export type Type1 = string;
export type Demo1 = boolean;
export type Index = number;
export type Demo2 = boolean;
export type Code3 = string;
export type Message3 = string;
export type RequestId2 = string | null;
export type RetryAfterSeconds = number | null;
export type Retryable1 = boolean;
export type FinishReason = "stop" | "length" | "tool_calls" | "cancelled" | "failed";
export type LatencyMs1 = number;
export type ModelIdentifier = string;
export type ProfileRevisionId1 = string;
export type ProviderKind = "openai" | "ollama" | "demo";
export type ProviderRevisionId1 = string;
export type RequestId3 = string | null;
export type Structured = {
  [k: string]: JsonValue;
} | null;
export type Text = string;
export type Id7 = string;
export type Name1 = string;
export type ToolCalls = ProviderToolCall[];
export type Text1 = string;
export type CorrelationId3 = string;
export type DataClassification = "public" | "internal" | "confidential" | "restricted";
export type NodeId1 = string | null;
export type OutputTokens1 = number;
export type ProjectId3 = string | null;
export type Purpose = string;
export type RunId5 = string | null;
export type StructuredSchema = {
  [k: string]: JsonValue;
} | null;
export type TaskId2 = string | null;
export type Text2 = string;
export type Description = string;
export type Name2 = string;
/**
 * @maxItems 32
 */
export type Tools = ProviderTool[];
export type Database = "ready" | "unavailable" | "migration_required";
export type Status3 = "ready" | "not_ready";
export type Archived = boolean;
export type CircuitState = "closed" | "open" | "half_open";
export type ContentHash1 = string;
export type CreatedAt5 = string;
export type CreatedBy = string | null;
export type Description1 = string;
export type DisplayName = string;
export type Enabled = boolean;
export type Health = "healthy" | "degraded" | "unavailable" | "misconfigured" | "unknown";
export type Id8 = string;
export type Key2 = string;
export type Revision1 = number;
export type RevisionId = string;
export type SecretLabel = string | null;
export type SecretStatus = "configured" | "missing" | "not_required";
export type Spec1 =
  WorkerSpec | ProviderSpec | ModelProfileSpec | RoutePolicySpec | RetryRegistrySpec | PermissionPolicySpec;
export type AdapterKind = "demo" | "openhands_ssh_v1";
/**
 * @maxItems 64
 */
export type Capabilities = string[];
export type DeploymentConfigured = boolean;
export type ExecutionHostLabel = string;
export type Kind3 = "worker";
export type MaxConcurrency = number;
/**
 * @maxItems 100
 */
export type AllowedProfileRevisionIds = string[];
export type Mode = "none" | "control_plane" | "worker_managed";
export type ConnectSeconds = number;
export type HeartbeatSeconds = number;
export type RunSeconds = number;
export type BaseUrl = string | null;
export type CooldownSeconds = number;
export type FailureThreshold = number;
export type FailureWindowSeconds = number;
export type AllowedData = ("public" | "internal" | "confidential" | "restricted")[];
export type Paid = boolean;
export type RemoteAllowed = boolean;
export type Kind4 = "provider_connection";
export type Locality = "local" | "local_lan" | "remote";
export type ProviderKind1 = "openai" | "ollama" | "demo";
export type RetryPolicyRevisionId = string | null;
/**
 * @maxItems 64
 */
export type Capabilities1 = string[];
export type ContextLimit = number;
export type Kind5 = "model_profile";
export type Locality1 = "local" | "local_lan" | "remote";
export type ModelIdentifier1 = string;
export type OutputLimit = number;
export type ProviderRevisionId2 = string;
/**
 * @minItems 1
 * @maxItems 32
 */
export type Purposes = [string, ...string[]];
export type Streaming = boolean;
export type StructuredJson = boolean;
export type ToolCalls1 = boolean;
export type UsageReporting = "exact" | "partial" | "none";
export type AllowRemote = boolean;
export type AllowUnknownHealth = boolean;
export type AllowedData1 = ("public" | "internal" | "confidential" | "restricted")[];
/**
 * @minItems 1
 * @maxItems 32
 */
export type Candidates = [RouteCandidate, ...RouteCandidate[]];
export type Priority = number;
export type ProfileRevisionId2 = string;
export type FailoverClasses = FailureClass[];
export type Kind6 = "route_policy";
/**
 * @minItems 1
 * @maxItems 32
 */
export type Purposes1 = [string, ...string[]];
export type RequiredCapabilities = string[];
export type AllowPaid = boolean;
export type MaxCallCost = number | string | null;
export type MaxInputTokens = number;
export type MaxOutputTokens = number;
export type MaxRunCost = number | string | null;
export type OnExceeded = "deny" | "require_approval";
export type Kind7 = "retry_policy";
export type AllowFailover = boolean;
export type ExhaustionAction = "fail" | "block" | "approval";
export type InitialDelayMs = number;
export type Jitter = "none" | "deterministic";
export type MaxDelayMs = number;
export type MaxRetries = number;
export type Multiplier = number;
export type Rules = RetryRule[];
export type SchemaVersion3 = "1.0";
export type AllowedCapabilities = string[];
export type ApprovalRequiredActions = string[];
export type Browser = "allow" | "deny" | "require_approval";
export type DeniedCapabilities = string[];
export type DestructiveAction = "deny" | "require_approval";
export type Docker = "allow" | "deny" | "require_approval";
export type FilesystemScopes = string[];
export type Git = "allow" | "deny" | "require_approval";
export type Kind8 = "permission_policy";
export type Network = "allow" | "deny" | "require_approval";
export type RemoteProvider = "allow" | "deny" | "require_approval";
export type SensitiveAction = "deny" | "require_approval";
export type Shell = "allow" | "deny" | "require_approval";
export type UnknownAction = "deny" | "require_approval";
export type UpdatedAt2 = string;
export type Version2 = number;
export type Items2 = RegistryRecord[];
export type NextAfter2 = string | null;
export type Archived1 = boolean;
export type ClearSecret = boolean;
export type DeploymentRef = string | null;
export type Description2 = string;
export type DisplayName1 = string;
export type Enabled1 = boolean;
export type ExpectedVersion = number;
export type IdempotencyKey3 = string;
export type Key3 = string;
export type SecretRef = string | null;
export type Spec2 =
  WorkerSpec | ProviderSpec | ModelProfileSpec | RoutePolicySpec | RetryRegistrySpec | PermissionPolicySpec;
export type Rules1 = RetryRule[];
export type SchemaVersion4 = "1.0";
export type FailedProfileRevisionIds = string[];
export type Capabilities2 = string[];
export type DataClassification1 = "public" | "internal" | "confidential" | "restricted";
export type InputTokens1 = number;
export type OutputTokens2 = number;
export type Purpose1 = string;
export type RunSpend = number | string | null;
export type RouteRevisionId1 = string;
export type Eligible = boolean;
export type ProfileRevisionId3 = string;
export type Reasons = string[];
export type Candidates1 = CandidateDecision[];
export type Decision = "allow" | "deny" | "require_approval";
export type Demo3 = boolean;
export type Reasons1 = string[];
export type RouteRevisionId2 = string;
export type SelectedProfileRevisionId = string | null;
export type SelectedProviderRevisionId = string | null;
export type SnapshotHash = string;
export type ClaimableAt = string;
export type ConfigSnapshotId = string;
export type CreatedAt6 = string;
export type DesiredRunState = "running" | "paused" | "cancelled";
export type Id9 = string;
export type JobId1 = string;
export type LanggraphThreadId = string;
export type RunNumber = number;
export type RunStatus =
  | "queued"
  | "claiming"
  | "running"
  | "pause_requested"
  | "paused"
  | "approval_required"
  | "cancel_requested"
  | "completed"
  | "failed"
  | "blocked"
  | "cancelled";
export type UpdatedAt3 = string;
export type Version3 = number;
export type WorkflowVersionId = string;
export type CreatedAt7 = string;
export type Id10 = string;
export type IdempotencyKey4 = string;
export type RunCommandKind = "pause" | "resume" | "cancel" | "instruction" | "retry";
export type RequestDigest2 = string;
export type RunId6 = string;
export type Sequence = number;
export type CommandStatus = "pending" | "applying" | "applied" | "rejected" | "superseded";
export type CommandId = string;
export type Duplicate = boolean;
export type RequestDigest3 = string;
export type RunId7 = string;
export type SchemaVersion5 = "1.0";
export type Sequence1 = number;
export type ExpectedRunVersion = number | null;
export type IdempotencyKey5 = string;
export type RunId8 = string;
export type SchemaVersion6 = "1.0";
export type CreatedAt8 = string;
export type Id11 = string;
export type ContentHash2 = string;
export type Key4 = string;
export type RevisionId1 = string;
export type ResolvedRevisions = ResolvedRevision[];
export type SchemaVersion7 = "1.0";
export type SnapshotHash1 = string;
export type WorkflowContentHash = string;
export type WorkflowVersionId1 = string;
export type LastEventAt = string | null;
export type LastEventPosition = number;
export type LastRunSequence = number;
export type ReadCursor = number;
export type RunId9 = string;
export type Status4 = string;
export type AbsoluteExpiresAt = string;
export type CsrfToken = string;
export type IdleExpiresAt = string;
export type Id12 = string;
export type Role = "owner";
export type Username1 = string;
export type AcceptanceCriteria = string[];
export type CreatedAt9 = string;
export type Id13 = string;
export type Key5 = string;
export type RunId10 = string;
export type TaskStatus =
  | "pending"
  | "ready"
  | "running"
  | "waiting"
  | "approval_required"
  | "succeeded"
  | "failed"
  | "blocked"
  | "cancelled"
  | "skipped";
export type Title = string;
export type UpdatedAt4 = string;
export type Version4 = number;
export type Weight = number;
export type AttemptNumber = number;
export type BaseSha = string | null;
export type CompletedAt = string | null;
export type Id14 = string;
export type ResultSha = string | null;
export type StartedAt = string | null;
export type AttemptStatus =
  "queued" | "running" | "verifying" | "reviewing" | "succeeded" | "failed" | "cancelled" | "unknown";
export type TaskId3 = string;
export type Demo4 = boolean;
export type Health1 = "healthy" | "degraded" | "unavailable" | "misconfigured" | "unknown";
export type Issues = string[];
export type NetworkChecked = boolean;
export type Valid = boolean;
export type AcceptsRuntimeInstructions = boolean;
export type ActionType = string | null;
export type ExpiresInSeconds = number | null;
export type RequiredGrantFrom = string | null;
export type MaxConcurrency1 = number | null;
export type ModelRouteRef = string | null;
export type PermissionPolicyRef = string | null;
export type RetryPolicyRef = string | null;
export type TimeoutSeconds = number | null;
export type Verification1 = {
  [k: string]: JsonValue;
} | null;
export type WorkerSelector = string | null;
export type Description3 = string;
export type Fallback = boolean;
export type From = string;
export type Id15 = string;
export type IterationKey = string | null;
export type WorkflowEdgeKind = "always" | "on_result" | "retry" | "iterate";
export type MaxIterations = number | null;
export type Priority1 = number;
export type ProgressPath = string | null;
export type RetryClass = string | null;
export type To = string;
export type Args = Predicate[];
export type PredicateOperator = "eq" | "neq" | "in" | "exists" | "lt" | "lte" | "gt" | "gte" | "and" | "or" | "not";
export type Path = string | null;
/**
 * @maxItems 2000
 */
export type Edges = WorkflowEdge[];
export type Entrypoint = string;
export type Key6 = string;
export type Name3 = string;
/**
 * @minItems 1
 * @maxItems 500
 */
export type Nodes = [WorkflowNode, ...WorkflowNode[]];
export type Id16 = string;
export type Label = string;
export type WorkflowNodeType =
  | "organizer"
  | "architect"
  | "task_dispatch"
  | "worker"
  | "verify"
  | "reviewer"
  | "integrate"
  | "router"
  | "fanout"
  | "join"
  | "approval"
  | "github_publish"
  | "finalize";
export type ResultPath = string;
export type SpecVersion = "1.0";
export type CompilerVersion = string;
export type ContentHash3 = string;
export type Id17 = string;
export type Published = boolean;
export type SpecVersion1 = "1.0";
export type Version5 = number;
export type WorkflowTemplateId = string;

export interface JarvisContractBundle {
  accounting_page?: AccountingPage | null;
  api_error?: ApiErrorResponse | null;
  artifact?: ArtifactMetadata | null;
  configuration_revision?: ConfigurationRevision | null;
  effect?: Effect | null;
  event_page?: EventPage | null;
  event_stream_reset?: EventStreamReset | null;
  failure_classification?: FailureClassification | null;
  failure_evidence?: FailureEvidence | null;
  failure_record?: FailureRecord | null;
  idempotency?: IdempotencyContract | null;
  job?: Job | null;
  lease?: Lease | null;
  liveness_response?: LivenessResponse | null;
  login_request?: LoginRequest | null;
  logout_response?: LogoutResponse | null;
  new_event?: NewEvent | null;
  normalized_event?: NormalizedEvent | null;
  provider_chunk?: ProviderChunk | null;
  provider_request?: ProviderRequest | null;
  provider_result?: ProviderResult | null;
  readiness_response?: ReadinessResponse | null;
  registry_page?: RegistryPage | null;
  registry_record?: RegistryRecord | null;
  registry_write?: RegistryWrite | null;
  retry_policy?: RetryPolicySpec | null;
  route_preview?: RoutePreviewRequest | null;
  route_resolution?: RouteResolution | null;
  run?: Run | null;
  run_command?: RunCommand | null;
  run_command_receipt?: RunCommandReceipt | null;
  run_command_request?: RunCommandRequest | null;
  run_configuration_snapshot?: RunConfigurationSnapshot | null;
  run_event_snapshot?: RunEventSnapshotResponse | null;
  session_response?: SessionResponse | null;
  task?: Task | null;
  task_attempt?: TaskAttempt | null;
  validation_report?: ValidationReport | null;
  workflow_spec?: WorkflowSpec | null;
  workflow_version?: WorkflowVersionContract | null;
}
export interface AccountingPage {
  items: Items;
  next_after?: NextAfter;
}
export interface AccountingRecord {
  correlation_id: CorrelationId;
  cost: Cost;
  created_at: CreatedAt;
  demo?: Demo;
  id: Id;
  latency_ms: LatencyMs;
  node_id?: NodeId;
  outcome: Outcome;
  pricing: Pricing;
  profile_revision_id: ProfileRevisionId;
  project_id?: ProjectId;
  provider_revision_id: ProviderRevisionId;
  request_id?: RequestId;
  route_revision_id?: RouteRevisionId;
  run_id?: RunId;
  task_id?: TaskId;
  usage: Usage;
}
export interface Cost {
  amount?: Amount;
  currency?: Currency;
  status?: Status;
}
export interface Pricing {
  cached_per_million?: CachedPerMillion;
  currency?: Currency1;
  effective_at?: EffectiveAt;
  input_per_million?: InputPerMillion;
  output_per_million?: OutputPerMillion;
  source?: Source;
  status?: Status1;
}
export interface Usage {
  cached_tokens?: CachedTokens;
  input_tokens?: InputTokens;
  output_tokens?: OutputTokens;
  provenance?: Provenance;
  total_tokens?: TotalTokens;
}
export interface ApiErrorResponse {
  error: ApiErrorDetail;
}
export interface ApiErrorDetail {
  code: Code;
  details?: Details;
  message: Message;
  request_id: RequestId1;
}
export interface Details {
  [k: string]: JsonValue;
}
export interface ArtifactMetadata {
  created_at: CreatedAt1;
  id: Id1;
  kind: Kind;
  media_type: MediaType;
  redaction_classification: RedactionClassification;
  run_id?: RunId1;
  sha256: Sha256;
  size_bytes: SizeBytes;
  storage_key: StorageKey;
  task_attempt_id?: TaskAttemptId;
}
export interface ConfigurationRevision {
  configuration_id: ConfigurationId;
  content_hash: ContentHash;
  created_at: CreatedAt2;
  id: Id2;
  key: Key;
  kind: ConfigurationKind;
  revision: Revision;
  schema_version?: SchemaVersion;
  spec: Spec;
}
export interface Spec {
  [k: string]: JsonValue;
}
export interface Effect {
  created_at: CreatedAt3;
  external_id?: ExternalId;
  fence_generation: FenceGeneration;
  id: Id3;
  idempotency_key: IdempotencyKey;
  kind: Kind1;
  request_digest: RequestDigest;
  result?: Result;
  run_id: RunId2;
  status: EffectStatus;
  task_attempt_id?: TaskAttemptId1;
  updated_at: UpdatedAt;
}
export interface EventPage {
  after: After;
  high_watermark: HighWatermark;
  items: Items1;
  next_after?: NextAfter1;
}
export interface NormalizedEvent {
  artifact_refs?: ArtifactRefs;
  category: EventCategory;
  causation_event_id?: CausationEventId;
  correlation_id: CorrelationId1;
  data: Data;
  event_id: EventId;
  global_position: GlobalPosition;
  idempotency_key?: IdempotencyKey1;
  message: Message1;
  mode: EventMode;
  occurred_at: OccurredAt;
  recorded_at: RecordedAt;
  run_sequence?: RunSequence;
  schema_version?: SchemaVersion1;
  scope?: EventScope;
  severity: EventSeverity;
  source: EventSource;
  trace?: EventTrace | null;
  type: Type;
  visibility: EventVisibility;
}
export interface ArtifactReference {
  artifact_id: ArtifactId;
  relation: Relation;
}
export interface Data {
  [k: string]: JsonValue;
}
export interface EventScope {
  job_id?: JobId;
  node_execution_id?: NodeExecutionId;
  project_id?: ProjectId1;
  run_id?: RunId3;
  task_attempt_id?: TaskAttemptId2;
  task_id?: TaskId1;
  thread_id?: ThreadId;
  workflow_node_id?: WorkflowNodeId;
}
export interface EventSource {
  host_id?: HostId;
  instance_id?: InstanceId;
  kind: Kind2;
  name: Name;
  source_sequence?: SourceSequence;
}
export interface EventTrace {
  span_id: SpanId;
  trace_id: TraceId;
}
export interface EventStreamReset {
  earliest_position?: EarliestPosition;
  latest_position?: LatestPosition;
  reason: Reason;
}
export interface FailureClassification {
  budget_scope: BudgetScope;
  class: FailureClass;
  code: Code1;
  consumes_semantic_attempt: ConsumesSemanticAttempt;
  retryable: Retryable;
  summary: Summary;
}
export interface FailureEvidence {
  code?: Code2;
  explicit_class?: FailureClass | null;
  provider_rate_limited?: ProviderRateLimited;
  provider_transient?: ProviderTransient;
  security_policy_denied?: SecurityPolicyDenied;
  summary?: Summary1;
  user_cancelled?: UserCancelled;
  verifier_failed?: VerifierFailed;
  worker_transport_failed?: WorkerTransportFailed;
}
export interface FailureRecord {
  classification: FailureClassification;
  detail_artifact_id?: DetailArtifactId;
  id: Id4;
}
export interface IdempotencyContract {
  key: Key1;
  request_digest: RequestDigest1;
  response_status?: ResponseStatus;
  scope: Scope;
  state: State;
}
export interface Job {
  created_at: CreatedAt4;
  id: Id5;
  objective: Objective;
  project_id: ProjectId2;
  status: JobStatus;
  thread_id?: ThreadId1;
  updated_at: UpdatedAt1;
  version: Version;
}
export interface Lease {
  acquired_at: AcquiredAt;
  expires_at: ExpiresAt;
  generation: Generation;
  id: Id6;
  owner_instance_id: OwnerInstanceId;
  released_at?: ReleasedAt;
  run_id: RunId4;
}
export interface LivenessResponse {
  service?: Service;
  status?: Status2;
  version?: Version1;
}
export interface LoginRequest {
  password: Password;
  username: Username;
}
export interface LogoutResponse {
  revoked: Revoked;
}
/**
 * Validated event before database ordering fields are allocated.
 */
export interface NewEvent {
  artifact_refs?: ArtifactRefs1;
  category: EventCategory;
  causation_event_id?: CausationEventId1;
  correlation_id: CorrelationId2;
  data: Data1;
  idempotency_key?: IdempotencyKey2;
  message: Message2;
  mode: EventMode;
  occurred_at: OccurredAt1;
  schema_version?: SchemaVersion2;
  scope?: EventScope;
  severity: EventSeverity;
  source: EventSource;
  trace?: EventTrace | null;
  type: Type1;
  visibility: EventVisibility;
}
export interface Data1 {
  [k: string]: JsonValue;
}
export interface ProviderChunk {
  demo?: Demo1;
  index: Index;
  result?: ProviderResult | null;
  text?: Text1;
}
export interface ProviderResult {
  demo?: Demo2;
  failure?: ProviderFailure | null;
  finish_reason?: FinishReason;
  latency_ms?: LatencyMs1;
  model_identifier: ModelIdentifier;
  profile_revision_id: ProfileRevisionId1;
  provider_kind: ProviderKind;
  provider_revision_id: ProviderRevisionId1;
  request_id?: RequestId3;
  structured?: Structured;
  text?: Text;
  tool_calls?: ToolCalls;
  usage?: Usage;
}
export interface ProviderFailure {
  code: Code3;
  failure_class: FailureClass;
  message: Message3;
  request_id?: RequestId2;
  retry_after_seconds?: RetryAfterSeconds;
  retryable: Retryable1;
}
export interface ProviderToolCall {
  arguments: Arguments;
  id: Id7;
  name: Name1;
}
export interface Arguments {
  [k: string]: JsonValue;
}
export interface ProviderRequest {
  correlation_id: CorrelationId3;
  data_classification?: DataClassification;
  node_id?: NodeId1;
  output_tokens: OutputTokens1;
  project_id?: ProjectId3;
  purpose: Purpose;
  run_id?: RunId5;
  structured_schema?: StructuredSchema;
  task_id?: TaskId2;
  text: Text2;
  tools?: Tools;
}
export interface ProviderTool {
  description?: Description;
  name: Name2;
  parameters: Parameters;
}
export interface Parameters {
  [k: string]: JsonValue;
}
export interface ReadinessResponse {
  database: Database;
  status: Status3;
}
export interface RegistryPage {
  items: Items2;
  next_after?: NextAfter2;
}
export interface RegistryRecord {
  archived: Archived;
  circuit_state?: CircuitState;
  content_hash: ContentHash1;
  created_at: CreatedAt5;
  created_by?: CreatedBy;
  description: Description1;
  display_name: DisplayName;
  enabled: Enabled;
  health?: Health;
  id: Id8;
  key: Key2;
  revision: Revision1;
  revision_id: RevisionId;
  secret_label?: SecretLabel;
  secret_status?: SecretStatus;
  spec: Spec1;
  updated_at: UpdatedAt2;
  version: Version2;
}
export interface WorkerSpec {
  adapter_kind?: AdapterKind;
  capabilities?: Capabilities;
  deployment_configured?: DeploymentConfigured;
  execution_host_label?: ExecutionHostLabel;
  kind?: Kind3;
  labels?: Labels;
  max_concurrency?: MaxConcurrency;
  model_binding?: ModelBinding;
  timeouts?: TimeoutPolicy;
}
export interface Labels {
  /**
   * This interface was referenced by `Labels`'s JSON-Schema definition
   * via the `patternProperty` "^[a-z][a-z0-9_.-]{0,63}$".
   */
  [k: string]: string;
}
export interface ModelBinding {
  allowed_profile_revision_ids?: AllowedProfileRevisionIds;
  mode?: Mode;
}
export interface TimeoutPolicy {
  connect_seconds?: ConnectSeconds;
  heartbeat_seconds?: HeartbeatSeconds;
  run_seconds?: RunSeconds;
}
export interface ProviderSpec {
  base_url?: BaseUrl;
  circuit?: CircuitPolicy;
  egress?: EgressPolicy;
  kind?: Kind4;
  locality?: Locality;
  provider_kind: ProviderKind1;
  retry_policy_revision_id?: RetryPolicyRevisionId;
  timeouts?: TimeoutPolicy;
}
export interface CircuitPolicy {
  cooldown_seconds?: CooldownSeconds;
  failure_threshold?: FailureThreshold;
  failure_window_seconds?: FailureWindowSeconds;
}
export interface EgressPolicy {
  allowed_data?: AllowedData;
  paid?: Paid;
  remote_allowed?: RemoteAllowed;
}
export interface ModelProfileSpec {
  capabilities?: Capabilities1;
  context_limit: ContextLimit;
  kind?: Kind5;
  locality?: Locality1;
  model_identifier: ModelIdentifier1;
  output_limit: OutputLimit;
  parameters?: Parameters1;
  pricing?: Pricing;
  provider_revision_id: ProviderRevisionId2;
  purposes: Purposes;
  streaming?: Streaming;
  structured_json?: StructuredJson;
  tool_calls?: ToolCalls1;
  usage_reporting?: UsageReporting;
}
export interface Parameters1 {
  [k: string]: JsonValue;
}
export interface RoutePolicySpec {
  allow_remote?: AllowRemote;
  allow_unknown_health?: AllowUnknownHealth;
  allowed_data?: AllowedData1;
  candidates: Candidates;
  failover_classes?: FailoverClasses;
  kind?: Kind6;
  purposes: Purposes1;
  required_capabilities?: RequiredCapabilities;
  spend?: SpendPolicy;
}
export interface RouteCandidate {
  priority?: Priority;
  profile_revision_id: ProfileRevisionId2;
}
export interface SpendPolicy {
  allow_paid?: AllowPaid;
  max_call_cost?: MaxCallCost;
  max_input_tokens?: MaxInputTokens;
  max_output_tokens?: MaxOutputTokens;
  max_run_cost?: MaxRunCost;
  on_exceeded?: OnExceeded;
}
export interface RetryRegistrySpec {
  kind?: Kind7;
  rules: Rules;
  schema_version?: SchemaVersion3;
}
export interface RetryRule {
  allow_failover?: AllowFailover;
  exhaustion_action: ExhaustionAction;
  failure_class: FailureClass;
  initial_delay_ms?: InitialDelayMs;
  jitter?: Jitter;
  max_delay_ms?: MaxDelayMs;
  max_retries: MaxRetries;
  multiplier?: Multiplier;
}
export interface PermissionPolicySpec {
  allowed_capabilities?: AllowedCapabilities;
  approval_required_actions?: ApprovalRequiredActions;
  browser?: Browser;
  denied_capabilities?: DeniedCapabilities;
  destructive_action?: DestructiveAction;
  docker?: Docker;
  filesystem_scopes?: FilesystemScopes;
  git?: Git;
  kind?: Kind8;
  network?: Network;
  remote_provider?: RemoteProvider;
  sensitive_action?: SensitiveAction;
  shell?: Shell;
  unknown_action?: UnknownAction;
}
export interface RegistryWrite {
  archived?: Archived1;
  clear_secret?: ClearSecret;
  deployment_ref?: DeploymentRef;
  description?: Description2;
  display_name: DisplayName1;
  enabled?: Enabled1;
  expected_version?: ExpectedVersion;
  idempotency_key: IdempotencyKey3;
  key: Key3;
  secret_ref?: SecretRef;
  spec: Spec2;
}
export interface RetryPolicySpec {
  rules: Rules1;
  schema_version?: SchemaVersion4;
}
export interface RoutePreviewRequest {
  failed_profile_revision_ids?: FailedProfileRevisionIds;
  failure_class?: FailureClass | null;
  requirements: RouteRequirements;
  route_revision_id: RouteRevisionId1;
}
export interface RouteRequirements {
  capabilities?: Capabilities2;
  data_classification?: DataClassification1;
  input_tokens?: InputTokens1;
  output_tokens?: OutputTokens2;
  purpose: Purpose1;
  run_spend?: RunSpend;
}
export interface RouteResolution {
  candidates?: Candidates1;
  decision?: Decision;
  demo?: Demo3;
  reasons?: Reasons1;
  route_revision_id: RouteRevisionId2;
  selected_profile_revision_id?: SelectedProfileRevisionId;
  selected_provider_revision_id?: SelectedProviderRevisionId;
  snapshot_hash: SnapshotHash;
}
export interface CandidateDecision {
  eligible: Eligible;
  profile_revision_id: ProfileRevisionId3;
  reasons?: Reasons;
}
export interface Run {
  claimable_at: ClaimableAt;
  config_snapshot_id: ConfigSnapshotId;
  created_at: CreatedAt6;
  desired_state: DesiredRunState;
  id: Id9;
  job_id: JobId1;
  langgraph_thread_id: LanggraphThreadId;
  run_number: RunNumber;
  status: RunStatus;
  updated_at: UpdatedAt3;
  version: Version3;
  workflow_version_id: WorkflowVersionId;
}
export interface RunCommand {
  created_at: CreatedAt7;
  id: Id10;
  idempotency_key: IdempotencyKey4;
  kind: RunCommandKind;
  payload: Payload;
  request_digest: RequestDigest2;
  run_id: RunId6;
  sequence: Sequence;
  status: CommandStatus;
}
export interface Payload {
  [k: string]: JsonValue;
}
export interface RunCommandReceipt {
  command_id: CommandId;
  duplicate?: Duplicate;
  request_digest: RequestDigest3;
  run_id: RunId7;
  schema_version?: SchemaVersion5;
  sequence: Sequence1;
  status: CommandStatus;
}
export interface RunCommandRequest {
  expected_run_version?: ExpectedRunVersion;
  idempotency_key: IdempotencyKey5;
  kind: RunCommandKind;
  payload?: Payload1;
  run_id: RunId8;
  schema_version?: SchemaVersion6;
}
export interface Payload1 {
  [k: string]: JsonValue;
}
export interface RunConfigurationSnapshot {
  created_at: CreatedAt8;
  effective_spec: EffectiveSpec;
  id: Id11;
  resolved_revisions: ResolvedRevisions;
  schema_version?: SchemaVersion7;
  snapshot_hash: SnapshotHash1;
  workflow_content_hash: WorkflowContentHash;
  workflow_version_id: WorkflowVersionId1;
}
export interface EffectiveSpec {
  [k: string]: JsonValue;
}
export interface ResolvedRevision {
  content_hash: ContentHash2;
  key: Key4;
  kind: ConfigurationKind;
  revision_id: RevisionId1;
}
export interface RunEventSnapshotResponse {
  last_event_at: LastEventAt;
  last_event_position: LastEventPosition;
  last_run_sequence: LastRunSequence;
  read_cursor: ReadCursor;
  run_id: RunId9;
  status: Status4;
}
export interface SessionResponse {
  absolute_expires_at: AbsoluteExpiresAt;
  csrf_token: CsrfToken;
  idle_expires_at: IdleExpiresAt;
  user: SessionUser;
}
export interface SessionUser {
  id: Id12;
  role?: Role;
  username: Username1;
}
export interface Task {
  acceptance_criteria: AcceptanceCriteria;
  created_at: CreatedAt9;
  id: Id13;
  key: Key5;
  run_id: RunId10;
  status: TaskStatus;
  title: Title;
  updated_at: UpdatedAt4;
  verification: Verification;
  version: Version4;
  weight?: Weight;
}
export interface Verification {
  [k: string]: JsonValue;
}
export interface TaskAttempt {
  attempt_number: AttemptNumber;
  base_sha?: BaseSha;
  completed_at?: CompletedAt;
  id: Id14;
  result_sha?: ResultSha;
  started_at?: StartedAt;
  status: AttemptStatus;
  task_id: TaskId3;
}
export interface ValidationReport {
  demo?: Demo4;
  health?: Health1;
  issues?: Issues;
  network_checked?: NetworkChecked;
  valid: Valid;
}
export interface WorkflowSpec {
  defaults?: NodePolicy;
  description?: Description3;
  edges: Edges;
  entrypoint: Entrypoint;
  key: Key6;
  name: Name3;
  nodes: Nodes;
  outputs: WorkflowOutputs;
  spec_version?: SpecVersion;
}
export interface NodePolicy {
  accepts_runtime_instructions?: AcceptsRuntimeInstructions;
  approval?: ApprovalPolicy | null;
  max_concurrency?: MaxConcurrency1;
  model_route_ref?: ModelRouteRef;
  permission_policy_ref?: PermissionPolicyRef;
  retry_policy_ref?: RetryPolicyRef;
  timeout_seconds?: TimeoutSeconds;
  verification?: Verification1;
  worker_selector?: WorkerSelector;
}
export interface ApprovalPolicy {
  action_type?: ActionType;
  expires_in_seconds?: ExpiresInSeconds;
  required_grant_from?: RequiredGrantFrom;
}
export interface WorkflowEdge {
  fallback?: Fallback;
  from: From;
  id: Id15;
  iteration_key?: IterationKey;
  kind: WorkflowEdgeKind;
  max_iterations?: MaxIterations;
  priority?: Priority1;
  progress_path?: ProgressPath;
  retry_class?: RetryClass;
  to: To;
  when?: Predicate | null;
}
export interface Predicate {
  args?: Args;
  op: PredicateOperator;
  path?: Path;
  value?: unknown;
}
export interface WorkflowNode {
  config: Config;
  id: Id16;
  label: Label;
  policy?: NodePolicy;
  type: WorkflowNodeType;
}
export interface Config {
  [k: string]: JsonValue;
}
export interface WorkflowOutputs {
  result_path: ResultPath;
}
export interface WorkflowVersionContract {
  compiler_version: CompilerVersion;
  content_hash: ContentHash3;
  id: Id17;
  layout: Layout;
  published: Published;
  spec: WorkflowSpec;
  spec_version?: SpecVersion1;
  version: Version5;
  workflow_template_id: WorkflowTemplateId;
}
export interface Layout {
  [k: string]: JsonValue;
}
