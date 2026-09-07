/* Generated from authoritative Pydantic contracts. Do not edit. */

export type Code = string;
export type JsonValue = unknown;
export type Message = string;
export type RequestId = string;
export type CreatedAt = string;
export type Id = string;
export type Kind = string;
export type MediaType = string;
export type RedactionClassification = "public" | "owner" | "sensitive" | "redacted";
export type RunId = string | null;
export type Sha256 = string;
export type SizeBytes = number;
export type StorageKey = string;
export type TaskAttemptId = string | null;
export type ConfigurationId = string;
export type ContentHash = string;
export type CreatedAt1 = string;
export type Id1 = string;
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
export type CreatedAt2 = string;
export type ExternalId = string | null;
export type FenceGeneration = number;
export type Id2 = string;
export type IdempotencyKey = string;
export type Kind1 = string;
export type RequestDigest = string;
export type Result = {
  [k: string]: JsonValue;
} | null;
export type RunId1 = string;
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
export type CorrelationId = string;
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
export type ProjectId = string | null;
export type RunId2 = string | null;
export type TaskAttemptId2 = string | null;
export type TaskId = string | null;
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
export type Items = NormalizedEvent[];
export type NextAfter = number | null;
export type EarliestPosition = number | null;
export type LatestPosition = number | null;
export type Reason = "cursor_expired" | "unsupported_schema" | "run_sequence_gap";
export type BudgetScope = string;
export type FailureClass =
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
export type Id3 = string;
export type Key1 = string;
export type RequestDigest1 = string;
export type ResponseStatus = number | null;
export type Scope = string;
export type State = "started" | "completed" | "failed";
export type CreatedAt3 = string;
export type Id4 = string;
export type Objective = string;
export type ProjectId1 = string;
export type JobStatus = "draft" | "queued" | "active" | "waiting" | "completed" | "failed" | "blocked" | "cancelled";
export type ThreadId1 = string | null;
export type UpdatedAt1 = string;
export type Version = number;
export type AcquiredAt = string;
export type ExpiresAt = string;
export type Generation = number;
export type Id5 = string;
export type OwnerInstanceId = string;
export type ReleasedAt = string | null;
export type RunId3 = string;
export type Service = "jarvis-api";
export type Status = "ok";
export type Version1 = "0.1.0";
export type Password = string;
export type Username = string;
export type Revoked = boolean;
export type ArtifactRefs1 = ArtifactReference[];
export type CausationEventId1 = string | null;
export type CorrelationId1 = string;
export type IdempotencyKey2 = string | null;
export type Message2 = string;
export type OccurredAt1 = string;
export type SchemaVersion2 = "1.0";
export type Type1 = string;
export type Database = "ready" | "unavailable" | "migration_required";
export type Status1 = "ready" | "not_ready";
export type ExhaustionAction = "fail" | "block" | "approval";
export type InitialDelayMs = number;
export type MaxRetries = number;
export type Multiplier = number;
export type Rules = RetryRule[];
export type SchemaVersion3 = "1.0";
export type ClaimableAt = string;
export type ConfigSnapshotId = string;
export type CreatedAt4 = string;
export type DesiredRunState = "running" | "paused" | "cancelled";
export type Id6 = string;
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
export type UpdatedAt2 = string;
export type Version2 = number;
export type WorkflowVersionId = string;
export type CreatedAt5 = string;
export type Id7 = string;
export type IdempotencyKey3 = string;
export type RunCommandKind = "pause" | "resume" | "cancel" | "instruction" | "retry";
export type RequestDigest2 = string;
export type RunId4 = string;
export type Sequence = number;
export type CommandStatus = "pending" | "applying" | "applied" | "rejected" | "superseded";
export type CommandId = string;
export type Duplicate = boolean;
export type RequestDigest3 = string;
export type RunId5 = string;
export type SchemaVersion4 = "1.0";
export type Sequence1 = number;
export type ExpectedRunVersion = number | null;
export type IdempotencyKey4 = string;
export type RunId6 = string;
export type SchemaVersion5 = "1.0";
export type CreatedAt6 = string;
export type Id8 = string;
export type ContentHash1 = string;
export type Key2 = string;
export type RevisionId = string;
export type ResolvedRevisions = ResolvedRevision[];
export type SchemaVersion6 = "1.0";
export type SnapshotHash = string;
export type WorkflowContentHash = string;
export type WorkflowVersionId1 = string;
export type LastEventAt = string | null;
export type LastEventPosition = number;
export type LastRunSequence = number;
export type ReadCursor = number;
export type RunId7 = string;
export type Status2 = string;
export type AbsoluteExpiresAt = string;
export type CsrfToken = string;
export type IdleExpiresAt = string;
export type Id9 = string;
export type Role = "owner";
export type Username1 = string;
export type AcceptanceCriteria = string[];
export type CreatedAt7 = string;
export type Id10 = string;
export type Key3 = string;
export type RunId8 = string;
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
export type UpdatedAt3 = string;
export type Version3 = number;
export type Weight = number;
export type AttemptNumber = number;
export type BaseSha = string | null;
export type CompletedAt = string | null;
export type Id11 = string;
export type ResultSha = string | null;
export type StartedAt = string | null;
export type AttemptStatus =
  "queued" | "running" | "verifying" | "reviewing" | "succeeded" | "failed" | "cancelled" | "unknown";
export type TaskId1 = string;
export type AcceptsRuntimeInstructions = boolean;
export type ActionType = string | null;
export type ExpiresInSeconds = number | null;
export type RequiredGrantFrom = string | null;
export type MaxConcurrency = number | null;
export type ModelRouteRef = string | null;
export type PermissionPolicyRef = string | null;
export type RetryPolicyRef = string | null;
export type TimeoutSeconds = number | null;
export type Verification1 = {
  [k: string]: JsonValue;
} | null;
export type WorkerSelector = string | null;
export type Description = string;
export type Fallback = boolean;
export type From = string;
export type Id12 = string;
export type IterationKey = string | null;
export type WorkflowEdgeKind = "always" | "on_result" | "retry" | "iterate";
export type MaxIterations = number | null;
export type Priority = number;
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
export type Key4 = string;
export type Name1 = string;
/**
 * @minItems 1
 * @maxItems 500
 */
export type Nodes = [WorkflowNode, ...WorkflowNode[]];
export type Id13 = string;
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
export type ContentHash2 = string;
export type Id14 = string;
export type Published = boolean;
export type SpecVersion1 = "1.0";
export type Version4 = number;
export type WorkflowTemplateId = string;

export interface JarvisContractBundle {
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
  readiness_response?: ReadinessResponse | null;
  retry_policy?: RetryPolicySpec | null;
  run?: Run | null;
  run_command?: RunCommand | null;
  run_command_receipt?: RunCommandReceipt | null;
  run_command_request?: RunCommandRequest | null;
  run_configuration_snapshot?: RunConfigurationSnapshot | null;
  run_event_snapshot?: RunEventSnapshotResponse | null;
  session_response?: SessionResponse | null;
  task?: Task | null;
  task_attempt?: TaskAttempt | null;
  workflow_spec?: WorkflowSpec | null;
  workflow_version?: WorkflowVersionContract | null;
}
export interface ApiErrorResponse {
  error: ApiErrorDetail;
}
export interface ApiErrorDetail {
  code: Code;
  details?: Details;
  message: Message;
  request_id: RequestId;
}
export interface Details {
  [k: string]: JsonValue;
}
export interface ArtifactMetadata {
  created_at: CreatedAt;
  id: Id;
  kind: Kind;
  media_type: MediaType;
  redaction_classification: RedactionClassification;
  run_id?: RunId;
  sha256: Sha256;
  size_bytes: SizeBytes;
  storage_key: StorageKey;
  task_attempt_id?: TaskAttemptId;
}
export interface ConfigurationRevision {
  configuration_id: ConfigurationId;
  content_hash: ContentHash;
  created_at: CreatedAt1;
  id: Id1;
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
  created_at: CreatedAt2;
  external_id?: ExternalId;
  fence_generation: FenceGeneration;
  id: Id2;
  idempotency_key: IdempotencyKey;
  kind: Kind1;
  request_digest: RequestDigest;
  result?: Result;
  run_id: RunId1;
  status: EffectStatus;
  task_attempt_id?: TaskAttemptId1;
  updated_at: UpdatedAt;
}
export interface EventPage {
  after: After;
  high_watermark: HighWatermark;
  items: Items;
  next_after?: NextAfter;
}
export interface NormalizedEvent {
  artifact_refs?: ArtifactRefs;
  category: EventCategory;
  causation_event_id?: CausationEventId;
  correlation_id: CorrelationId;
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
  project_id?: ProjectId;
  run_id?: RunId2;
  task_attempt_id?: TaskAttemptId2;
  task_id?: TaskId;
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
  id: Id3;
}
export interface IdempotencyContract {
  key: Key1;
  request_digest: RequestDigest1;
  response_status?: ResponseStatus;
  scope: Scope;
  state: State;
}
export interface Job {
  created_at: CreatedAt3;
  id: Id4;
  objective: Objective;
  project_id: ProjectId1;
  status: JobStatus;
  thread_id?: ThreadId1;
  updated_at: UpdatedAt1;
  version: Version;
}
export interface Lease {
  acquired_at: AcquiredAt;
  expires_at: ExpiresAt;
  generation: Generation;
  id: Id5;
  owner_instance_id: OwnerInstanceId;
  released_at?: ReleasedAt;
  run_id: RunId3;
}
export interface LivenessResponse {
  service?: Service;
  status?: Status;
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
  correlation_id: CorrelationId1;
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
export interface ReadinessResponse {
  database: Database;
  status: Status1;
}
export interface RetryPolicySpec {
  rules: Rules;
  schema_version?: SchemaVersion3;
}
export interface RetryRule {
  exhaustion_action: ExhaustionAction;
  failure_class: FailureClass;
  initial_delay_ms?: InitialDelayMs;
  max_retries: MaxRetries;
  multiplier?: Multiplier;
}
export interface Run {
  claimable_at: ClaimableAt;
  config_snapshot_id: ConfigSnapshotId;
  created_at: CreatedAt4;
  desired_state: DesiredRunState;
  id: Id6;
  job_id: JobId1;
  langgraph_thread_id: LanggraphThreadId;
  run_number: RunNumber;
  status: RunStatus;
  updated_at: UpdatedAt2;
  version: Version2;
  workflow_version_id: WorkflowVersionId;
}
export interface RunCommand {
  created_at: CreatedAt5;
  id: Id7;
  idempotency_key: IdempotencyKey3;
  kind: RunCommandKind;
  payload: Payload;
  request_digest: RequestDigest2;
  run_id: RunId4;
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
  run_id: RunId5;
  schema_version?: SchemaVersion4;
  sequence: Sequence1;
  status: CommandStatus;
}
export interface RunCommandRequest {
  expected_run_version?: ExpectedRunVersion;
  idempotency_key: IdempotencyKey4;
  kind: RunCommandKind;
  payload?: Payload1;
  run_id: RunId6;
  schema_version?: SchemaVersion5;
}
export interface Payload1 {
  [k: string]: JsonValue;
}
export interface RunConfigurationSnapshot {
  created_at: CreatedAt6;
  effective_spec: EffectiveSpec;
  id: Id8;
  resolved_revisions: ResolvedRevisions;
  schema_version?: SchemaVersion6;
  snapshot_hash: SnapshotHash;
  workflow_content_hash: WorkflowContentHash;
  workflow_version_id: WorkflowVersionId1;
}
export interface EffectiveSpec {
  [k: string]: JsonValue;
}
export interface ResolvedRevision {
  content_hash: ContentHash1;
  key: Key2;
  kind: ConfigurationKind;
  revision_id: RevisionId;
}
export interface RunEventSnapshotResponse {
  last_event_at: LastEventAt;
  last_event_position: LastEventPosition;
  last_run_sequence: LastRunSequence;
  read_cursor: ReadCursor;
  run_id: RunId7;
  status: Status2;
}
export interface SessionResponse {
  absolute_expires_at: AbsoluteExpiresAt;
  csrf_token: CsrfToken;
  idle_expires_at: IdleExpiresAt;
  user: SessionUser;
}
export interface SessionUser {
  id: Id9;
  role?: Role;
  username: Username1;
}
export interface Task {
  acceptance_criteria: AcceptanceCriteria;
  created_at: CreatedAt7;
  id: Id10;
  key: Key3;
  run_id: RunId8;
  status: TaskStatus;
  title: Title;
  updated_at: UpdatedAt3;
  verification: Verification;
  version: Version3;
  weight?: Weight;
}
export interface Verification {
  [k: string]: JsonValue;
}
export interface TaskAttempt {
  attempt_number: AttemptNumber;
  base_sha?: BaseSha;
  completed_at?: CompletedAt;
  id: Id11;
  result_sha?: ResultSha;
  started_at?: StartedAt;
  status: AttemptStatus;
  task_id: TaskId1;
}
export interface WorkflowSpec {
  defaults?: NodePolicy;
  description?: Description;
  edges: Edges;
  entrypoint: Entrypoint;
  key: Key4;
  name: Name1;
  nodes: Nodes;
  outputs: WorkflowOutputs;
  spec_version?: SpecVersion;
}
export interface NodePolicy {
  accepts_runtime_instructions?: AcceptsRuntimeInstructions;
  approval?: ApprovalPolicy | null;
  max_concurrency?: MaxConcurrency;
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
  id: Id12;
  iteration_key?: IterationKey;
  kind: WorkflowEdgeKind;
  max_iterations?: MaxIterations;
  priority?: Priority;
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
  id: Id13;
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
  content_hash: ContentHash2;
  id: Id14;
  layout: Layout;
  published: Published;
  spec: WorkflowSpec;
  spec_version?: SpecVersion1;
  version: Version4;
  workflow_template_id: WorkflowTemplateId;
}
export interface Layout {
  [k: string]: JsonValue;
}
