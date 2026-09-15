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
export type Decision = "approved" | "rejected";
export type ExpectedRunVersion = number;
export type IdempotencyKey = string;
export type RequestDigest = string;
export type ActionType = string;
export type ActorId = string | null;
export type CreatedAt1 = string;
export type DecidedAt = string | null;
export type Decision1 = "pending" | "approved" | "rejected" | "expired" | "cancelled";
export type ExpiresAt = string | null;
export type Id1 = string;
export type NodeId1 = string;
export type RequestDigest1 = string;
export type RunId1 = string;
export type Items1 = ApprovalView[];
export type CreatedAt2 = string;
export type Id2 = string;
export type Kind = string;
export type MediaType = string;
export type RedactionClassification = "public" | "owner" | "sensitive" | "redacted";
export type RunId2 = string | null;
export type Sha256 = string;
export type SizeBytes = number;
export type StorageKey = string;
export type TaskAttemptId = string | null;
export type ConfigurationId = string;
export type ContentHash = string;
export type CreatedAt3 = string;
export type Id3 = string;
export type Key = string;
export type ConfigurationKind =
  | "worker"
  | "provider_connection"
  | "model_profile"
  | "route_policy"
  | "retry_policy"
  | "permission_policy"
  | "branch_policy"
  | "project_settings"
  | "execution_profile";
export type Revision = number;
export type SchemaVersion = "1.0";
export type Decision2 = "approved" | "rejected";
export type DecisionId = string;
export type ExpectedRunVersion1 = number;
export type IdempotencyKey1 = string;
export type Decision3 = string;
export type Id4 = string;
export type DependencyDigest = string;
export type FinishedAt = string | null;
export type Id5 = string;
export type ImageId = string;
export type LifecycleScripts = "denied";
export type LockfileDigest = string;
export type LockfilePath = string;
export type OutputArtifactId = string | null;
export type OutputTruncated = boolean;
export type ProfileDigest = string;
export type ProfileRevisionId1 = string;
export type RegistryHosts = string[];
export type SnapshotId = string;
export type SourceSha = string;
export type StartedAt = string;
export type Status2 = "prepared" | "failed" | "unknown";
/**
 * @maxItems 40
 */
export type Constraints = string[];
export type ExpectedVersion = number;
export type IdempotencyKey2 = string;
export type Objective = string;
export type CreatedAt4 = string;
export type ExternalId = string | null;
export type FenceGeneration = number;
export type Id6 = string;
export type IdempotencyKey3 = string;
export type Kind1 = string;
export type RequestDigest2 = string;
export type Result = {
  [k: string]: JsonValue;
} | null;
export type RunId3 = string;
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
export type IdempotencyKey4 = string | null;
export type Message1 = string;
export type EventMode = "real" | "demo";
export type OccurredAt = string;
export type RecordedAt = string;
export type RunSequence = number | null;
export type SchemaVersion1 = "1.0";
export type JobId = string | null;
export type NodeExecutionId = string | null;
export type ProjectId1 = string | null;
export type RunId4 = string | null;
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
export type Items2 = NormalizedEvent[];
export type NextAfter1 = number | null;
export type EarliestPosition = number | null;
export type LatestPosition = number | null;
export type Reason = "cursor_expired" | "unsupported_schema" | "run_sequence_gap";
export type CacheMaxMb = number;
export type LifecycleScripts1 = "deny";
export type Lockfiles = ("requirements.lock" | "package-lock.json")[];
export type Manager = "none" | "pip" | "npm";
export type RegistryAllowlist = string[];
export type RequireIntegrity = boolean;
export type RequireLockfile = boolean;
export type ImageReference = string;
export type Kind3 = "execution_profile";
export type MaxFiles = number;
export type MaxSourceBytes = number;
export type DenyHost = true;
export type DenyLan = true;
export type DenyMetadata = true;
export type DenyPublicInternet = true;
export type Preparation = "none" | "registry_allowlist";
export type Verification = "none" | "application_loopback";
export type ProfileKey = "python-pytest-v1" | "node-build-v1" | "browser-acceptance-v1";
export type ProfileVersion = "1.0";
/**
 * @minItems 1
 */
export type ProjectTypes = ["python" | "node" | "full_stack", ...("python" | "node" | "full_stack")[]];
export type CpuCount = number;
export type MemoryMb = number;
export type OutputBytes = number;
export type Pids = number;
export type TimeoutSeconds = number;
export type WorkspaceMb = number;
/**
 * @minItems 1
 * @maxItems 64
 */
export type SourceFormats = [string, ...string[]];
/**
 * @minItems 1
 * @maxItems 32
 */
export type SupportedCommands = [string, ...string[]];
export type Items3 = ExecutionProfileSpec[];
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
export type Id7 = string;
export type Key1 = string;
export type RequestDigest3 = string;
export type ResponseStatus = number | null;
export type Scope = string;
export type State = "started" | "completed" | "failed";
export type BaseSha = string;
export type Branch = string;
export type ExpiresAt1 = string | null;
export type Generation = number;
export type HeadSha = string;
export type LeaseOwner = string | null;
export type ReleasedAt = string | null;
export type RepositoryId = string;
export type SnapshotArtifactId = string | null;
export type Items4 = IntegrationHeadView[];
export type NextAfter2 = string | null;
export type CreatedAt5 = string;
export type Id8 = string;
export type Objective1 = string;
export type ProjectId2 = string;
export type JobStatus = "draft" | "queued" | "active" | "waiting" | "completed" | "failed" | "blocked" | "cancelled";
export type ThreadId1 = string | null;
export type UpdatedAt1 = string;
export type Version = number;
export type Ci = "success" | "failure";
export type Clock = string;
export type DelaySeconds = number;
export type Health = "healthy" | "degraded" | "unavailable" | "unknown";
export type Scenario = "canonical" | "infrastructure" | "review" | "provider";
export type Seed = number;
export type IdempotencyKey5 = string;
export type Mode = "real" | "demo";
export type Objective2 = string;
export type Priority = number;
export type WorkflowVersionId = string;
export type Id9 = string;
export type Objective3 = string;
export type ProjectId3 = string;
export type Status3 = string;
export type Items5 = JobView[];
export type NextAfter3 = string | null;
export type AcquiredAt = string;
export type ExpiresAt2 = string;
export type Generation1 = number;
export type Id10 = string;
export type OwnerInstanceId = string;
export type ReleasedAt1 = string | null;
export type RunId5 = string;
export type Service = "jarvis-api";
export type Status4 = "ok";
export type Version1 = "0.1.0";
export type Password = string;
export type Username = string;
export type Revoked = boolean;
export type CompletedAt = string | null;
export type CreatedAt6 = string;
export type Action = "explain" | "propose" | "clarify" | "wait" | "complete";
export type Lifecycle = "active" | "idle" | "waiting_for_approval" | "blocked" | "completed";
export type Message2 = string;
export type ScheduledWakeupAt = string | null;
/**
 * @maxItems 8
 */
export type WorkItems =
  | []
  | [WorkItemProposal]
  | [WorkItemProposal, WorkItemProposal]
  | [WorkItemProposal, WorkItemProposal, WorkItemProposal]
  | [WorkItemProposal, WorkItemProposal, WorkItemProposal, WorkItemProposal]
  | [WorkItemProposal, WorkItemProposal, WorkItemProposal, WorkItemProposal, WorkItemProposal]
  | [WorkItemProposal, WorkItemProposal, WorkItemProposal, WorkItemProposal, WorkItemProposal, WorkItemProposal]
  | [
      WorkItemProposal,
      WorkItemProposal,
      WorkItemProposal,
      WorkItemProposal,
      WorkItemProposal,
      WorkItemProposal,
      WorkItemProposal
    ]
  | [
      WorkItemProposal,
      WorkItemProposal,
      WorkItemProposal,
      WorkItemProposal,
      WorkItemProposal,
      WorkItemProposal,
      WorkItemProposal,
      WorkItemProposal
    ];
/**
 * @minItems 1
 * @maxItems 20
 */
export type AcceptanceCriteria =
  | [string]
  | [string, string]
  | [string, string, string]
  | [string, string, string, string]
  | [string, string, string, string, string]
  | [string, string, string, string, string, string]
  | [string, string, string, string, string, string, string]
  | [string, string, string, string, string, string, string, string]
  | [string, string, string, string, string, string, string, string, string]
  | [string, string, string, string, string, string, string, string, string, string]
  | [string, string, string, string, string, string, string, string, string, string, string]
  | [string, string, string, string, string, string, string, string, string, string, string, string]
  | [string, string, string, string, string, string, string, string, string, string, string, string, string]
  | [string, string, string, string, string, string, string, string, string, string, string, string, string, string]
  | [
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string
    ]
  | [
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string
    ]
  | [
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string
    ]
  | [
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string
    ]
  | [
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string
    ]
  | [
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string
    ];
/**
 * @maxItems 20
 */
export type Dependencies =
  | []
  | [string]
  | [string, string]
  | [string, string, string]
  | [string, string, string, string]
  | [string, string, string, string, string]
  | [string, string, string, string, string, string]
  | [string, string, string, string, string, string, string]
  | [string, string, string, string, string, string, string, string]
  | [string, string, string, string, string, string, string, string, string]
  | [string, string, string, string, string, string, string, string, string, string]
  | [string, string, string, string, string, string, string, string, string, string, string]
  | [string, string, string, string, string, string, string, string, string, string, string, string]
  | [string, string, string, string, string, string, string, string, string, string, string, string, string]
  | [string, string, string, string, string, string, string, string, string, string, string, string, string, string]
  | [
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string
    ]
  | [
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string
    ]
  | [
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string
    ]
  | [
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string
    ]
  | [
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string
    ]
  | [
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string
    ];
export type Key2 = string;
export type Objective4 = string;
export type Priority1 = number;
export type Title = string;
export type DirectiveVersion = number;
export type FailureCode = string | null;
export type Id11 = string;
export type ModelCallId = string | null;
export type Status5 = "queued" | "running" | "applied" | "stale" | "failed";
export type TeamVersion = number;
export type Items6 = ManagementTurnView[];
export type NextAfter4 = string | null;
export type Enabled = boolean;
export type ExpectedVersion1 = number;
export type IdempotencyKey6 = string;
export type Action1 = "pause" | "resume" | "drain" | "safe_point" | "cancel";
export type ExpectedVersion2 = number;
export type IdempotencyKey7 = string;
export type Instruction = string | null;
export type Currency2 = string;
export type MaxActiveJobs = number;
export type MaxCalls = number;
export type MaxCost = number | string | null;
export type MaxInputTokens = number;
export type MaxIterations = number;
export type MaxNewWorkItems = number;
export type MaxOutputTokens = number;
export type MaxWallSeconds = number;
export type Timezone = "UTC";
export type WindowSeconds = number;
export type Scope1 = "mission" | "team" | "global";
export type Instruction1 = string | null;
export type Scope2 = "mission" | "team" | "global";
export type State1 = "open" | "paused" | "draining" | "cancelling";
export type Version2 = number;
export type Autonomous = boolean;
/**
 * @maxItems 40
 */
export type Constraints1 = string[];
export type IdempotencyKey8 = string;
export type Mode1 = "demo" | "real";
export type Objective5 = string;
export type ProjectId4 = string;
export type TeamTemplateRevisionId = string;
export type AllowPaidInference = boolean;
export type Body = string;
export type ExpectedVersion3 = number;
export type IdempotencyKey9 = string;
export type Body1 = string;
export type CreatedAt7 = string;
export type DirectiveVersion1 = number;
export type Disposition = "queued" | "delivered" | "stale" | "failed";
export type Id12 = string;
export type Identity = string;
export type ManagementTurnId = string | null;
export type Role = "user" | "manager" | "system";
export type Sequence = number;
export type Items7 = MissionMessageView[];
export type NextAfter5 = number | null;
export type ActiveWorkDirectiveVersion = number | null;
export type Autonomous1 = boolean;
export type Constraints2 = string[];
export type CreatedAt8 = string;
export type DirectiveVersion2 = number;
export type Id13 = string;
export type Lifecycle1 =
  | "active"
  | "idle"
  | "waiting_for_capacity"
  | "waiting_for_approval"
  | "blocked"
  | "paused"
  | "cancelling"
  | "cancelled"
  | "completed"
  | "archived";
export type Mode2 = "demo" | "real";
export type NextAction = string | null;
export type NextActionBasis = string | null;
export type Objective6 = string;
export type PaidUnattendedAvailable = boolean;
export type ProjectId5 = string;
export type TeamVersion1 = number;
export type UpdatedAt2 = string;
export type Timezone1 = "UTC";
export type UnknownLiability = boolean;
export type WindowSeconds1 = number;
export type WindowStartedAt = string;
export type UserActionRequired = string | null;
export type Version3 = number;
export type WaitingReason = string | null;
export type Items8 = MissionView[];
export type NextAfter6 = string | null;
export type ExpectedVersion4 = number;
export type IdempotencyKey10 = string;
export type TeamTemplateRevisionId1 = string;
export type Active = boolean;
export type ContentHash1 = string;
export type CreatedAt9 = string;
export type Id14 = string;
export type MaxActiveAssignments = number;
export type MaxExecutionSeconds = number;
export type MaxInferenceCalls = number;
export type ReserveManagementSlots = number;
export type ReserveReviewSlots = number;
export type DeveloperRoleRevisionId = string;
export type DeveloperWorkerRevisionId = string;
export type EligibleWorkerRevisionIds = string[];
export type EscalationPolicyRevisionId = string | null;
export type ManagerProfileRevisionId = string;
export type ManagerRoleRevisionId = string;
/**
 * @minItems 1
 * @maxItems 64
 */
export type AllowedTools = [string, ...string[]];
export type Key3 = string;
export type MayExecute = boolean;
export type MayReview = boolean;
export type ModelRouteRevisionId = string;
export type PermissionPolicyRevisionId = string;
/**
 * @maxItems 32
 */
export type RequiredCapabilities = string[];
export type RoleRevisionId = string;
/**
 * @minItems 1
 * @maxItems 16
 */
export type WorkerPoolRevisionIds =
  | [string]
  | [string, string]
  | [string, string, string]
  | [string, string, string, string]
  | [string, string, string, string, string]
  | [string, string, string, string, string, string]
  | [string, string, string, string, string, string, string]
  | [string, string, string, string, string, string, string, string]
  | [string, string, string, string, string, string, string, string, string]
  | [string, string, string, string, string, string, string, string, string, string]
  | [string, string, string, string, string, string, string, string, string, string, string]
  | [string, string, string, string, string, string, string, string, string, string, string, string]
  | [string, string, string, string, string, string, string, string, string, string, string, string, string]
  | [string, string, string, string, string, string, string, string, string, string, string, string, string, string]
  | [
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string
    ]
  | [
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string
    ];
export type Members = TeamMemberSpec[];
export type ReviewerProfileRevisionId = string;
export type ReviewerRoleRevisionId = string;
export type TeamTemplateRevisionId2 = string;
export type WorkerPoolSnapshotHash = string | null;
export type WorkflowVersionId1 = string;
export type Version4 = number;
export type Items9 = MissionTeamVersionView[];
export type NextAfter7 = string | null;
export type CreatedAt10 = string;
export type DeduplicationKey = string;
export type DirectiveVersion3 = number;
export type Id15 = string;
export type Kind4 = "user_direction" | "job_completed" | "job_failed" | "approval_decided" | "deadline";
export type ManagementTurnId1 = string | null;
export type ScheduledFor = string;
export type SourceEventCursor = number | null;
export type Status6 = "pending" | "claimed" | "turn_queued" | "committed" | "stale" | "failed";
export type Items10 = MissionWakeupView[];
export type NextAfter8 = string | null;
export type ArtifactRefs1 = ArtifactReference[];
export type CausationEventId1 = string | null;
export type CorrelationId2 = string;
export type IdempotencyKey11 = string | null;
export type Message3 = string;
export type OccurredAt1 = string;
export type SchemaVersion2 = "1.0";
export type Type1 = string;
/**
 * @maxItems 3
 */
export type ExecutionProfileRevisionIds = [] | [string] | [string, string] | [string, string, string];
export type IdempotencyKey12 = string;
export type Name1 = string;
export type ProjectType = "python" | "node" | "full_stack";
export type Slug = string;
export type ExecutionProfileRevisionIds1 = string[];
export type Id16 = string;
export type Name2 = string;
export type ProjectType1 = "python" | "node" | "full_stack";
export type Slug1 = string;
export type Items11 = ProjectView[];
export type NextAfter9 = string | null;
export type Demo1 = boolean;
export type Index = number;
export type Demo2 = boolean;
export type Code3 = string;
export type Message4 = string;
export type RequestId2 = string | null;
export type RetryAfterSeconds = number | null;
export type Retryable1 = boolean;
export type FinishReason = "stop" | "length" | "tool_calls" | "cancelled" | "failed";
export type LatencyMs1 = number;
export type ModelIdentifier = string;
export type ProfileRevisionId2 = string;
export type ProviderKind = "openai" | "ollama" | "demo";
export type ProviderRevisionId1 = string;
export type RequestId3 = string | null;
export type Structured = {
  [k: string]: JsonValue;
} | null;
export type Text = string;
export type Id17 = string;
export type Name3 = string;
export type ToolCalls = ProviderToolCall[];
export type Text1 = string;
export type CorrelationId3 = string;
export type DataClassification = "public" | "internal" | "confidential" | "restricted";
export type NodeId2 = string | null;
export type OutputTokens1 = number;
export type ProjectId6 = string | null;
export type Purpose = string;
export type RunId6 = string | null;
export type StructuredSchema = {
  [k: string]: JsonValue;
} | null;
export type TaskId2 = string | null;
export type Text2 = string;
export type Description = string;
export type Name4 = string;
/**
 * @maxItems 32
 */
export type Tools = ProviderTool[];
export type Api = "ready";
export type Database = "ready" | "unavailable" | "migration_required";
export type Execution = "not_evaluated";
export type SchemaRevision = "ready" | "migration_required";
export type Scope3 = "control_plane";
export type Status7 = "ready" | "not_ready";
export type Archived = boolean;
export type CircuitState = "closed" | "open" | "half_open";
export type ContentHash2 = string;
export type CreatedAt11 = string;
export type CreatedBy = string | null;
export type Description1 = string;
export type DisplayName = string;
export type Enabled1 = boolean;
export type Health1 = "healthy" | "degraded" | "unavailable" | "misconfigured" | "unknown";
export type Id18 = string;
export type Key4 = string;
export type Revision1 = number;
export type RevisionId = string;
export type SecretLabel = string | null;
export type SecretStatus = "configured" | "missing" | "not_required";
export type Spec1 =
  | AgentRoleSpec
  | TeamTemplateSpec
  | WorkerSpec
  | ProviderSpec
  | ModelProfileSpec
  | RoutePolicySpec
  | RetryRegistrySpec
  | PermissionPolicySpec
  | ExecutionProfileSpec
  | WorkerPoolSpec;
export type Instructions = string;
export type Kind5 = "agent_role";
export type Purpose1 = string;
export type Responsibility = "manager" | "developer" | "reviewer" | "specialist";
export type DeveloperRoleRevisionId1 = string;
export type DeveloperWorkerRevisionId1 = string;
export type EscalationPolicyRevisionId1 = string | null;
export type Kind6 = "team_template";
export type ManagerProfileRevisionId1 = string;
export type ManagerRoleRevisionId1 = string;
/**
 * @maxItems 32
 */
export type Members1 = TeamMemberSpec[];
export type Mode3 = "demo" | "real";
export type ReviewerProfileRevisionId1 = string;
export type ReviewerRoleRevisionId1 = string;
export type WorkflowVersionId2 = string;
export type AdapterKind = "demo" | "openhands_ssh_v1";
/**
 * @maxItems 64
 */
export type Capabilities = string[];
export type DeploymentConfigured = boolean;
export type ExecutionHostLabel = string;
/**
 * @maxItems 32
 */
export type ExecutionProfileRevisionIds2 = string[];
export type Kind7 = "worker";
export type MaxConcurrency = number;
/**
 * @maxItems 100
 */
export type AllowedProfileRevisionIds = string[];
export type Mode4 = "none" | "control_plane" | "worker_managed";
export type ObservedBuildDigest = string | null;
export type ObservedWrapperVersion = string | null;
/**
 * @maxItems 256
 */
export type PermittedProjectIds = string[];
export type PhysicalResourceId = string | null;
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
export type Kind8 = "provider_connection";
export type Locality = "local" | "local_lan" | "remote";
export type ProviderKind1 = "openai" | "ollama" | "demo";
export type RetryPolicyRevisionId = string | null;
/**
 * @maxItems 64
 */
export type Capabilities1 = string[];
export type ContextLimit = number;
export type Kind9 = "model_profile";
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
export type Priority2 = number;
export type ProfileRevisionId3 = string;
export type FailoverClasses = FailureClass[];
export type Kind10 = "route_policy";
/**
 * @minItems 1
 * @maxItems 32
 */
export type Purposes1 = [string, ...string[]];
export type RequiredCapabilities1 = string[];
export type AllowPaid = boolean;
export type MaxCallCost = number | string | null;
export type MaxInputTokens1 = number;
export type MaxOutputTokens1 = number;
export type MaxRunCost = number | string | null;
export type OnExceeded = "deny" | "require_approval";
export type Kind11 = "retry_policy";
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
export type Kind12 = "permission_policy";
export type Network = "allow" | "deny" | "require_approval";
export type RemoteProvider = "allow" | "deny" | "require_approval";
export type SensitiveAction = "deny" | "require_approval";
export type Shell = "allow" | "deny" | "require_approval";
export type UnknownAction = "deny" | "require_approval";
export type HealthFreshnessSeconds = number;
export type Kind13 = "worker_pool";
/**
 * @maxItems 256
 */
export type PermittedProjectIds1 = string[];
/**
 * @maxItems 32
 */
export type RequiredCapabilities2 = string[];
/**
 * @minItems 1
 * @maxItems 128
 */
export type WorkerRevisionIds = [string, ...string[]];
export type UpdatedAt3 = string;
export type Version5 = number;
export type ExclusiveWorkspace = boolean;
export type LastHeartbeatAt = string | null;
export type PossiblyStalled = boolean;
export type SlotsInUse = number;
export type ValidatedAt = string | null;
export type ValidationIssues = string[];
export type Items12 = RegistryRecord[];
export type NextAfter10 = string | null;
export type Archived1 = boolean;
export type ClearSecret = boolean;
export type DeploymentRef = string | null;
export type Description2 = string;
export type DisplayName1 = string;
export type Enabled2 = boolean;
export type ExpectedVersion5 = number;
export type IdempotencyKey13 = string;
export type Key5 = string;
export type SecretRef = string | null;
export type Spec2 =
  | AgentRoleSpec
  | TeamTemplateSpec
  | WorkerSpec
  | ProviderSpec
  | ModelProfileSpec
  | RoutePolicySpec
  | RetryRegistrySpec
  | PermissionPolicySpec
  | ExecutionProfileSpec
  | WorkerPoolSpec;
export type ContextDigest = string;
export type Coverage = "complete" | "sufficient" | "insufficient";
export type CreatedAt12 = string;
export type ContentDigest = string;
export type EndLine = number;
export type Path = string;
export type Provenance1 = "source" | "manifest" | "test" | "brief" | "directive" | "decision" | "outcome";
export type StartLine = number;
/**
 * @maxItems 512
 */
export type Entries = RepositoryContextEntry[];
export type Id19 = string;
/**
 * @maxItems 512
 */
export type OmittedPaths = string[];
export type RepositoryId1 = string;
export type RunId7 = string;
export type Selection = "full" | "bounded";
export type SelectionPolicy = string;
export type SourceSha1 = string;
export type TreeSha = string;
export type Rules1 = RetryRule[];
export type SchemaVersion4 = "1.0";
export type CriterionIndex = number;
export type SourcePath = string;
export type Summary2 = string;
/**
 * @maxItems 64
 */
export type Findings = ReviewFinding[];
export type FinishedAt1 = string;
export type Id20 = string;
export type ReviewedHeadSha = string;
export type ReviewedSnapshotId = string;
export type ReviewerRevision = string;
export type SnapshotDigest = string;
export type StartedAt1 = string;
export type Summary3 = string;
export type TaskAttemptId3 = string;
export type TaskId3 = string;
export type Verdict = "PASS" | "FAIL";
/**
 * @minItems 1
 * @maxItems 64
 */
export type AcceptanceCriteria1 = [string, ...string[]];
/**
 * @maxItems 32
 */
export type ArchitectureArtifactIds = string[];
export type ConfigSnapshotId = string;
export type FailureHistoryArtifactId = string;
export type Objective7 = string;
/**
 * @maxItems 100
 */
export type PriorFeedbackArtifactIds = string[];
export type BaseSha1 = string;
export type Branch1 = string;
export type ContentDigest1 = string;
export type CreatedAt13 = string;
export type CumulativeDiffArtifactId = string;
export type FileCount = number;
export type GitStatus = "clean";
export type HeadSha1 = string;
export type Id21 = string;
export type LatestBaseSha = string;
export type LatestDiffArtifactId = string;
export type Lfs = "absent";
export type ManifestArtifactId = string;
export type RepositoryId2 = string;
export type RunId8 = string;
export type SourceArtifactId = string;
export type Submodules = "absent";
export type TaskAttemptId4 = string;
export type TreeSha1 = string;
export type WorkerResultId = string;
export type TaskAttemptId5 = string;
export type TaskId4 = string;
export type TaskTitle = string;
/**
 * @minItems 1
 * @maxItems 32
 */
export type VerificationArtifactIds = [string, ...string[]];
export type WorkflowVersionId3 = string;
export type FailedProfileRevisionIds = string[];
export type Capabilities2 = string[];
export type DataClassification1 = "public" | "internal" | "confidential" | "restricted";
export type InputTokens1 = number;
export type OutputTokens2 = number;
export type Purpose2 = string;
export type RunSpend = number | string | null;
export type RouteRevisionId1 = string;
export type Eligible = boolean;
export type ProfileRevisionId4 = string;
export type Reasons = string[];
export type Candidates1 = CandidateDecision[];
export type Decision4 = "allow" | "deny" | "require_approval";
export type Demo3 = boolean;
export type Reasons1 = string[];
export type RouteRevisionId2 = string;
export type SelectedProfileRevisionId = string | null;
export type SelectedProviderRevisionId = string | null;
export type SnapshotHash = string;
export type ClaimableAt = string;
export type ConfigSnapshotId1 = string;
export type CreatedAt14 = string;
export type DesiredRunState = "running" | "paused" | "cancelled";
export type Id22 = string;
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
export type UpdatedAt4 = string;
export type Version6 = number;
export type WorkflowVersionId4 = string;
export type CreatedAt15 = string;
export type Id23 = string;
export type IdempotencyKey14 = string;
export type RunCommandKind = "pause" | "resume" | "cancel" | "instruction" | "retry";
export type RequestDigest4 = string;
export type RunId9 = string;
export type Sequence1 = number;
export type CommandStatus = "pending" | "applying" | "applied" | "rejected" | "superseded";
export type CommandId = string;
export type Duplicate = boolean;
export type RequestDigest5 = string;
export type RunId10 = string;
export type SchemaVersion5 = "1.0";
export type Sequence2 = number;
export type ExpectedRunVersion2 = number | null;
export type IdempotencyKey15 = string;
export type RunId11 = string;
export type SchemaVersion6 = "1.0";
export type CreatedAt16 = string;
export type Id24 = string;
export type ContentHash3 = string;
export type Key6 = string;
export type RevisionId1 = string;
export type ResolvedRevisions = ResolvedRevision[];
export type SchemaVersion7 = "1.0";
export type SnapshotHash1 = string;
export type WorkflowContentHash = string;
export type WorkflowVersionId5 = string;
export type ExpectedRunVersion3 = number;
export type IdempotencyKey16 = string;
export type Instruction2 = string | null;
export type LastEventAt = string | null;
export type LastEventPosition = number;
export type LastRunSequence = number;
export type ReadCursor = number;
export type RunId12 = string;
export type Status8 = string;
export type ClaimableAt1 = string;
export type CompletedAt1 = string | null;
export type CurrentNode = string | null;
export type DesiredState = string;
export type Id25 = string;
export type JobId2 = string;
export type LastEventAt1 = string | null;
export type LastEventPosition1 = number;
export type LastRunSequence1 = number;
export type Mode5 = string;
export type ProjectId7 = string;
export type Recovering = boolean;
export type ResultSummary = string | null;
export type RetryOfRunId = string | null;
export type RunNumber1 = number;
export type StartedAt2 = string | null;
export type Status9 = string;
export type ThreadId2 = string;
export type Version7 = number;
export type WorkflowVersionId6 = string;
export type Items13 = RunView[];
export type NextAfter11 = string | null;
export type Duplicate1 = boolean;
export type EffectId = string;
export type EffectStatus1 = "dispatched" | "running" | "cancel_requested" | "unknown";
export type QueuedForInspection = boolean;
export type RunId13 = string;
export type EffectId1 = string;
export type ExpectedRunVersion4 = number;
export type IdempotencyKey17 = string;
export type Calls = number;
export type Currency3 = string;
export type KnownSubtotal = number | string;
export type Status10 = "exact" | "estimated" | "unknown" | "not_applicable";
export type Total = number | string | null;
export type UnknownCalls = number;
export type Currencies = CurrencyUsage[];
export type KnownTokens = number;
export type Provenance2 = "exact" | "estimated" | "unknown";
export type TotalTokens1 = number | null;
export type UnknownUsageCalls = number;
export type WorkerUsage = "unavailable";
export type AppliedAt = string | null;
export type Id26 = string;
export type Kind14 = string;
export type Sequence3 = number;
export type Status11 = string;
export type Items14 = CommandView[];
export type NextAfter12 = number | null;
export type CompletedAt2 = string | null;
export type ExecutionNumber = number;
export type Id27 = string;
export type StartedAt3 = string | null;
export type Status12 = string;
export type TaskAttemptId6 = string | null;
export type TaskId5 = string | null;
export type WorkflowNodeId1 = string;
export type Items15 = NodeView[];
export type NextAfter13 = string | null;
export type Id28 = string;
export type Number = number;
export type SnapshotDigest1 = string | null;
export type Status13 = string;
export type Attempts = AttemptView[];
export type Dependencies1 = string[];
export type Id29 = string;
export type Key7 = string;
export type Status14 = string;
export type Title1 = string;
export type Weight = number;
export type Items16 = TaskView[];
export type NextAfter14 = string | null;
export type AbsoluteExpiresAt = string;
export type CsrfToken = string;
export type IdleExpiresAt = string;
export type Id30 = string;
export type Role1 = "owner";
export type Username1 = string;
export type AcceptingInstances = number;
export type ControlPlane = "healthy";
export type Database1 = "healthy";
export type Execution1 = "ready" | "configured_unverified" | "not_ready" | "unconfigured";
export type ExecutionReasons = string[];
export type ExpiredActiveLeases = number;
export type HeartbeatStaleAfterSeconds = number;
export type LastHeartbeatAt1 = string | null;
export type ObservedAt = string;
export type Orchestrator = "healthy" | "stale" | "unknown";
export type Provider = "configured_unverified" | "missing" | "stale" | "demo_only";
export type RepositoryBinding = "configured" | "missing" | "stale" | "demo_only";
export type RuntimeManifest = "configured" | "missing" | "stale" | "demo_only";
export type RuntimeManifestSha256 = string | null;
export type RuntimeMode = "real" | "demo" | "unknown";
export type VerificationBroker = "configured_unverified" | "missing" | "stale" | "demo_only";
export type Worker = "configured_unverified" | "missing" | "stale" | "demo_only";
export type AcceptanceCriteria2 = string[];
export type CreatedAt17 = string;
export type Id31 = string;
export type Key8 = string;
export type RunId14 = string;
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
export type Title2 = string;
export type UpdatedAt5 = string;
export type Version8 = number;
export type Weight1 = number;
export type AttemptNumber = number;
export type BaseSha2 = string | null;
export type CompletedAt3 = string | null;
export type Id32 = string;
export type ResultSha = string | null;
export type StartedAt4 = string | null;
export type AttemptStatus =
  "queued" | "running" | "verifying" | "reviewing" | "succeeded" | "failed" | "cancelled" | "unknown";
export type TaskId6 = string;
export type Demo4 = boolean;
export type Health2 = "healthy" | "degraded" | "unavailable" | "misconfigured" | "unknown";
export type Issues = string[];
export type NetworkChecked = boolean;
export type Valid = boolean;
/**
 * @minItems 1
 * @maxItems 64
 */
export type Argv = [string, ...string[]];
/**
 * @minItems 1
 * @maxItems 8
 */
export type ExpectedExitCodes =
  | [number]
  | [number, number]
  | [number, number, number]
  | [number, number, number, number]
  | [number, number, number, number, number]
  | [number, number, number, number, number, number]
  | [number, number, number, number, number, number, number]
  | [number, number, number, number, number, number, number, number];
export type Kind15 = "argv";
export type MaxOutputBytes = number;
export type Parser =
  "exit_code" | "pytest" | "vitest" | "playwright" | "typescript" | "next" | "eslint" | "ruff" | "mypy";
export type ProfileRevisionId5 = string | null;
export type Purpose3 = "build" | "unit" | "browser" | "quality" | "integration";
export type RequireNonemptySuite = boolean;
export type RequiredCheckId = string | null;
export type TimeoutSeconds1 = number;
export type WorkingRootPolicy = "adapter_confirmed_root";
export type CommandDigest = string | null;
export type Cwd = string;
export type DependencyDigest1 = string | null;
/**
 * @maxItems 16
 */
export type EnvironmentKeys =
  | []
  | [string]
  | [string, string]
  | [string, string, string]
  | [string, string, string, string]
  | [string, string, string, string, string]
  | [string, string, string, string, string, string]
  | [string, string, string, string, string, string, string]
  | [string, string, string, string, string, string, string, string]
  | [string, string, string, string, string, string, string, string, string]
  | [string, string, string, string, string, string, string, string, string, string]
  | [string, string, string, string, string, string, string, string, string, string, string]
  | [string, string, string, string, string, string, string, string, string, string, string, string]
  | [string, string, string, string, string, string, string, string, string, string, string, string, string]
  | [string, string, string, string, string, string, string, string, string, string, string, string, string, string]
  | [
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string
    ]
  | [
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string
    ];
export type ExitCode = number | null;
export type FailureClass1 = string | null;
export type FinishedAt2 = string | null;
export type Id33 = string;
export type ImageId1 = string | null;
export type Complete = boolean;
export type Confidence = "summary" | "exit_code";
export type Errors = number | null;
export type Failed = number | null;
export type Parser1 =
  "exit_code" | "pytest" | "vitest" | "playwright" | "typescript" | "next" | "eslint" | "ruff" | "mypy";
export type Passed = number | null;
export type Skipped = number | null;
export type Summary4 = string;
export type Phase = "task" | "integration";
export type ProfileDigest1 = string | null;
export type ProfileRevisionId6 = string | null;
export type RequiredChecksDigest = string | null;
export type RunId15 = string;
export type SnapshotId1 = string;
export type SourceSha2 = string;
export type StartedAt5 = string;
export type Status15 = "started" | "passed" | "failed" | "timed_out" | "unknown";
export type StderrArtifactId = string | null;
export type StderrTruncated = boolean;
export type StdoutArtifactId = string | null;
export type StdoutTruncated = boolean;
export type TaskAttemptId7 = string;
export type TaskId7 = string;
export type AcceptanceCriteria3 = string[];
export type AssignmentStatus = string | null;
export type CreatedAt18 = string;
export type Dependencies2 = string[];
export type DirectiveVersion4 = number;
export type Id34 = string;
export type JobId3 = string | null;
export type Key9 = string;
export type Lifecycle2 = "pending" | "ready" | "started" | "accepted" | "blocked" | "cancelled";
export type MergeQueueStatus = string | null;
export type Objective8 = string;
export type Priority3 = number;
export type QueuedReason = string | null;
export type RunId16 = string | null;
export type SelectedModelProfileRevisionId = string | null;
export type SelectedWorkerRevisionId = string | null;
export type TeamVersion2 = number;
export type TeamVersionId = string;
export type Title3 = string;
export type Items17 = WorkItemView[];
export type NextAfter15 = string | null;
export type ExpectedMissionVersion = number;
export type IdempotencyKey18 = string;
export type InvocationId = string;
export type Status16 = "cancelled" | "unknown" | "already_terminal";
export type InvocationId1 = string;
export type OccurredAt2 = string;
export type SourceSequence1 = number;
export type Type2 =
  | "worker.invocation_dispatched"
  | "worker.heartbeat"
  | "worker.invocation_completed"
  | "worker.invocation_failed"
  | "worker.cancel_requested"
  | "worker.cancelled";
export type Generation2 = number;
export type InvocationId2 = string;
export type RequestDigest6 = string;
export type WorkerRevisionId = string;
export type Capabilities3 = string[];
export type Issues1 = string[];
export type NetworkChecked1 = boolean;
export type ObservedAt1 = string;
export type Status17 = "healthy" | "degraded" | "unavailable" | "misconfigured" | "unknown";
/**
 * @maxItems 64
 */
export type AllowedTools1 = string[];
export type ArchitectureArtifactId = string | null;
/**
 * @maxItems 32
 */
export type FeedbackArtifactIds = string[];
export type IdempotencyKey19 = string;
export type InvocationId3 = string;
export type ExpiresAt3 = string;
export type Generation3 = number;
export type LeaseId = string;
export type PhysicalResourceId1 = string | null;
export type RunGeneration = number;
export type Slot = number;
export type WorkerRevisionId1 = string;
export type MaxOutputBytes1 = number;
export type MaxResultBytes = number;
export type MaxRuntimeSeconds = number;
export type ModelProfileRevisionId = string;
export type Objective9 = string;
export type PermissionPolicyRevisionId1 = string | null;
export type BaseSha3 = string;
export type Branch2 = string;
export type ProjectId8 = string;
export type RepositoryId3 = string;
export type Slug2 = string;
export type WorkspaceRoot = string;
export type ProtocolVersion = "1.0";
/**
 * @maxItems 64
 */
export type RequiredCapabilities3 = string[];
export type RunId17 = string;
/**
 * @minItems 1
 * @maxItems 64
 */
export type AcceptanceCriteria4 = [string, ...string[]];
export type Description3 = string;
export type Key10 = string;
export type Title4 = string;
/**
 * @minItems 1
 * @maxItems 64
 */
export type Argv1 = [string, ...string[]];
/**
 * @minItems 1
 * @maxItems 8
 */
export type ExpectedExitCodes1 =
  | [number]
  | [number, number]
  | [number, number, number]
  | [number, number, number, number]
  | [number, number, number, number, number]
  | [number, number, number, number, number, number]
  | [number, number, number, number, number, number, number]
  | [number, number, number, number, number, number, number, number];
export type Kind16 = "argv";
export type MaxOutputBytes2 = number;
export type Parser2 =
  "exit_code" | "pytest" | "vitest" | "playwright" | "typescript" | "next" | "eslint" | "ruff" | "mypy";
export type ProfileRevisionId7 = string | null;
export type Purpose4 = "build" | "unit" | "browser" | "quality" | "integration";
export type RequireNonemptySuite1 = boolean;
export type RequiredCheckId1 = string | null;
export type TimeoutSeconds2 = number;
export type WorkingRootPolicy1 = "adapter_confirmed_root";
/**
 * @maxItems 32
 */
export type Verification2 = WorkerVerification[];
export type TaskAttemptId8 = string;
export type TaskId8 = string;
export type WorkerRevisionId2 = string;
export type RequestDigest7 = string;
export type InvocationId4 = string;
export type SafeToStart = boolean;
export type State2 = "absent" | "starting" | "running" | "succeeded" | "failed" | "cancelled" | "unknown";
/**
 * @maxItems 16
 */
export type ArtifactManifest =
  | []
  | [WorkerArtifact]
  | [WorkerArtifact, WorkerArtifact]
  | [WorkerArtifact, WorkerArtifact, WorkerArtifact]
  | [WorkerArtifact, WorkerArtifact, WorkerArtifact, WorkerArtifact]
  | [WorkerArtifact, WorkerArtifact, WorkerArtifact, WorkerArtifact, WorkerArtifact]
  | [WorkerArtifact, WorkerArtifact, WorkerArtifact, WorkerArtifact, WorkerArtifact, WorkerArtifact]
  | [WorkerArtifact, WorkerArtifact, WorkerArtifact, WorkerArtifact, WorkerArtifact, WorkerArtifact, WorkerArtifact]
  | [
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact
    ]
  | [
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact
    ]
  | [
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact
    ]
  | [
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact
    ]
  | [
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact
    ]
  | [
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact
    ]
  | [
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact
    ]
  | [
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact
    ]
  | [
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact,
      WorkerArtifact
    ];
export type Kind17 = "stdout" | "stderr" | "repository";
export type Sha2561 = string;
export type SizeBytes1 = number;
export type Branch3 = string;
export type EndHead = string;
export type Error = string | null;
export type FinishedAt3 = string;
export type Generation4 = number;
export type InvocationId5 = string;
export type ModelProfileRevisionId1 = string;
export type ProtocolVersion1 = "1.0";
export type DiffDigest = string;
export type FileCount1 = number;
export type GitStatus1 = "clean" | "dirty";
export type HeadSha2 = string;
export type ManifestDigest = string;
export type MetadataTruncated = boolean;
export type StatusDigest = string;
export type TreeDigest = string;
export type RequestDigest8 = string;
export type SourceSequence2 = number;
export type StartHead = string;
export type StartedAt6 = string;
export type Status18 = "succeeded" | "failed" | "cancelled" | "unknown";
export type Summary5 = string;
export type TaskAttemptId9 = string;
export type TaskId9 = string;
export type WorkspaceRoot1 = string;
export type InvocationId6 = string;
export type LastActivityAt = string | null;
export type PossiblyStalled1 = boolean;
export type SourceSequence3 = number;
export type State3 = "absent" | "starting" | "running" | "succeeded" | "failed" | "cancelled" | "unknown";
export type ExclusiveWorkspace1 = boolean;
export type Valid1 = boolean;
export type Archived2 = boolean;
export type ExpectedVersion6 = number;
export type IdempotencyKey20 = string;
export type ExpectedVersion7 = number;
export type IdempotencyKey21 = string;
export type Description4 = string;
export type IdempotencyKey22 = string;
export type Key11 = string;
export type Name5 = string;
export type Archived3 = boolean;
export type CreatedAt19 = string;
export type CurrentDraftVersionId = string | null;
export type CurrentPublishedVersionId = string | null;
export type Description5 = string;
export type Id35 = string;
export type Key12 = string;
export type Name6 = string;
export type UpdatedAt6 = string;
export type Version9 = number;
export type CompilerVersion = string;
export type ContentHash4 = string;
export type CreatedAt20 = string;
export type Id36 = string;
export type X = number;
export type Y = number;
export type X1 = number;
export type Y1 = number;
export type Zoom = number;
export type Published = boolean;
export type PublishedAt = string | null;
export type SnapshotHash2 = string | null;
export type AcceptsRuntimeInstructions = boolean;
export type ActionType1 = ("github.push_and_pr" | "git.integrate" | "worker.execute") | null;
export type ExpiresInSeconds = number | null;
export type RequiredGrantFrom = string | null;
export type MaxConcurrency1 = number | null;
export type ModelRouteRef = string | null;
export type PermissionPolicyRef = string | null;
export type RetryPolicyRef = string | null;
export type TimeoutSeconds3 = number | null;
/**
 * @maxItems 3
 */
export type ExecutionProfileRevisionIds3 = [] | [string] | [string, string] | [string, string, string];
export type Required = boolean;
export type CheckId = string;
export type ProfileRevisionId8 = string;
export type Purpose5 = "build" | "unit" | "browser" | "quality" | "integration";
/**
 * @maxItems 32
 */
export type RequiredAcceptanceChecks = RequiredAcceptanceCheck[];
export type Source1 = "task";
/**
 * @maxItems 64
 */
export type Requires = string[];
export type RevisionId2 = string;
export type Description6 = string;
export type Fallback = boolean;
export type From = string;
export type Id37 = string;
export type IterationKey = string | null;
export type WorkflowEdgeKind = "always" | "on_result" | "retry" | "iterate" | "on_failure";
export type MaxIterations1 = number | null;
export type Priority4 = number;
export type ProgressPath = string | null;
export type To = string;
/**
 * @maxItems 64
 */
export type Args = Predicate[];
export type PredicateOperator = "eq" | "neq" | "in" | "exists" | "lt" | "lte" | "gt" | "gte" | "and" | "or" | "not";
export type Path1 = string | null;
/**
 * @maxItems 2000
 */
export type Edges = WorkflowEdge[];
export type Entrypoint = string;
export type Key13 = string;
export type Name7 = string;
/**
 * @minItems 1
 * @maxItems 500
 */
export type Nodes1 = [WorkflowNode, ...WorkflowNode[]];
export type Id38 = string;
export type Label = string;
export type NodeVersion = "1.0";
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
export type SpecVersion = "1.0" | "1.1";
export type StateSchema = "jarvis.workflow_state.v1";
export type Version10 = number;
export type WorkflowTemplateId = string;
export type ExpectedVersion8 = number;
export type IdempotencyKey23 = string;
export type ExpectedVersion9 = number;
export type IdempotencyKey24 = string;
export type SourceVersionId = string | null;
export type WorkflowNodeConfigs =
  | OrganizerConfig
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
  | null;
export type SummaryLimit = number;
export type MaxTasks = number;
export type OutputSchema = "task_plan.v1";
export type Parallelism = 1;
export type ReadyOrder = "dependency_then_task_key";
export type TaskSource = "current_task";
export type CommandsSource = "task.verification";
export type StopOnFailure = true;
export type RequiresRepositorySnapshot = true;
export type RepositorySource = "project";
export type RunCombinedGates = true;
export type CancellationStrategy = "wait_all";
/**
 * @maxItems 64
 */
export type Children = string[];
export type JoinId = string;
export type MaxFanout = number;
export type FanoutId = string;
export type RequireAll = true;
export type ActionType2 = "github.push_and_pr" | "git.integrate" | "worker.execute";
export type ExpiresInSeconds1 = number | null;
export type RepositorySource1 = "project";
export type WaitForCi = boolean;
export type Outcome1 = "derive" | "failed" | "blocked" | "cancelled";
export type ExternalBehavior = boolean;
export type InputChannels = string[];
export type OutputChannels = string[];
export type RequiredCapabilities4 = string[];
export type Items18 = NodeTypeDefinition[];
export type CompilerVersion1 = "1.0.0";
export type Archived4 = boolean;
export type ConfigurationId1 = string;
export type ContentHash5 = string;
export type Description7 = string;
export type DisplayName2 = string;
export type Enabled3 = boolean;
export type Key14 = string;
export type Revision2 = number;
export type RevisionId3 = string;
export type Spec3 =
  | AgentRoleSpec
  | TeamTemplateSpec
  | WorkerSpec
  | ProviderSpec
  | ModelProfileSpec
  | RoutePolicySpec
  | RetryRegistrySpec
  | PermissionPolicySpec
  | ExecutionProfileSpec
  | WorkerPoolSpec;
export type Revisions = WorkflowResolvedRevision[];
export type WorkflowContentHash1 = string;
export type Items19 = WorkflowTemplateRecord[];
export type NextAfter16 = string | null;
export type ExpectedVersion10 = number;
export type IdempotencyKey25 = string;
export type ContentHash6 = string | null;
export type Code4 = string;
export type EdgeId = string | null;
export type Message5 = string;
export type NodeId3 = string | null;
export type Path2 = string | null;
export type Issues2 = WorkflowIssue[];
export type SnapshotHash3 = string | null;
export type Valid2 = boolean;
export type CompilerVersion2 = string;
export type ContentHash7 = string;
export type Id39 = string;
export type Published1 = boolean;
export type SpecVersion1 = "1.0" | "1.1";
export type Version11 = number;
export type WorkflowTemplateId1 = string;
export type Items20 = WorkflowVersionRecord[];
export type NextAfter17 = string | null;

export interface JarvisContractBundle {
  accounting_page?: AccountingPage | null;
  api_error?: ApiErrorResponse | null;
  approval_decision: ApprovalDecisionRequest;
  approvals: ApprovalPage;
  artifact?: ArtifactMetadata | null;
  configuration_revision?: ConfigurationRevision | null;
  demo_decision: DemoDecision;
  demo_decision_view: DemoDecisionView;
  dependency_preparation?: DependencyPreparationEvidence | null;
  directive_update?: DirectiveUpdate | null;
  effect?: Effect | null;
  event_page?: EventPage | null;
  event_stream_reset?: EventStreamReset | null;
  execution_profile_templates?: ExecutionProfileTemplatePage | null;
  failure_classification?: FailureClassification | null;
  failure_evidence?: FailureEvidence | null;
  failure_record?: FailureRecord | null;
  idempotency?: IdempotencyContract | null;
  integration_heads: IntegrationHeadPage;
  job?: Job | null;
  job_create?: JobCreate | null;
  job_page?: JobPage | null;
  lease?: Lease | null;
  liveness_response?: LivenessResponse | null;
  login_request?: LoginRequest | null;
  logout_response?: LogoutResponse | null;
  management_turn_page?: ManagementTurnPage | null;
  mission_autonomy_update?: MissionAutonomyUpdate | null;
  mission_control_request?: MissionControlRequest | null;
  mission_control_view?: MissionControlView | null;
  mission_create?: MissionCreate | null;
  mission_message_create?: MissionMessageCreate | null;
  mission_message_page?: MissionMessagePage | null;
  mission_page?: MissionPage | null;
  mission_team_update?: MissionTeamUpdate | null;
  mission_team_versions?: MissionTeamVersionPage | null;
  mission_wakeup_page?: MissionWakeupPage | null;
  new_event?: NewEvent | null;
  normalized_event?: NormalizedEvent | null;
  project_create?: ProjectCreate | null;
  project_page?: ProjectPage | null;
  provider_chunk?: ProviderChunk | null;
  provider_request?: ProviderRequest | null;
  provider_result?: ProviderResult | null;
  readiness_response?: ReadinessResponse | null;
  registry_page?: RegistryPage | null;
  registry_record?: RegistryRecord | null;
  registry_write?: RegistryWrite | null;
  repository_context?: RepositoryContextSnapshot | null;
  retry_policy?: RetryPolicySpec | null;
  review_decision: ReviewDecision;
  review_evidence: ReviewEvidence;
  route_preview?: RoutePreviewRequest | null;
  route_resolution?: RouteResolution | null;
  run?: Run | null;
  run_command?: RunCommand | null;
  run_command_receipt?: RunCommandReceipt | null;
  run_command_request?: RunCommandRequest | null;
  run_configuration_snapshot?: RunConfigurationSnapshot | null;
  run_control?: RunControl | null;
  run_event_snapshot?: RunEventSnapshotResponse | null;
  run_page?: RunPage | null;
  run_reconciliation_receipt?: RunReconciliationReceipt | null;
  run_reconciliation_request?: RunReconciliationRequest | null;
  run_usage: RunUsage;
  runtime_commands: CommandPage;
  runtime_nodes: NodePage;
  runtime_tasks: TaskPage;
  session_response?: SessionResponse | null;
  system_health: SystemHealth;
  task?: Task | null;
  task_attempt?: TaskAttempt | null;
  validation_report?: ValidationReport | null;
  verification_execution: VerificationExecution;
  work_item_page?: WorkItemPage | null;
  work_item_start?: WorkItemStart | null;
  worker_cancel: CancelResult;
  worker_event: WorkerEvent;
  worker_handle: WorkerInvocationHandle;
  worker_health: WorkerHealth;
  worker_invocation_request: WorkerInvocationRequest;
  worker_prepared: PreparedInvocation;
  worker_reconciliation: ReconciliationResult;
  worker_result: WorkerResult;
  worker_status: WorkerInvocationStatus;
  worker_validation: WorkerValidationReport;
  workflow_archive_request?: WorkflowArchiveRequest | null;
  workflow_command?: WorkflowCommand | null;
  workflow_create?: WorkflowCreateRequest | null;
  workflow_document?: WorkflowDocument | null;
  workflow_draft_write?: WorkflowDraftWrite | null;
  workflow_new_draft?: WorkflowNewDraft | null;
  workflow_node_configs?: WorkflowNodeConfigs;
  workflow_node_types?: NodeTypePage | null;
  workflow_snapshot?: WorkflowResolvedSnapshot | null;
  workflow_spec?: WorkflowSpec | null;
  workflow_template_page?: WorkflowTemplatePage | null;
  workflow_validate_request?: WorkflowValidateRequest | null;
  workflow_validation?: WorkflowValidationReport | null;
  workflow_version?: WorkflowVersionContract | null;
  workflow_version_page?: WorkflowVersionPage | null;
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
export interface ApprovalDecisionRequest {
  decision: Decision;
  expected_run_version: ExpectedRunVersion;
  idempotency_key: IdempotencyKey;
  request_digest: RequestDigest;
}
export interface ApprovalPage {
  items: Items1;
}
export interface ApprovalView {
  action_type: ActionType;
  actor_id?: ActorId;
  created_at: CreatedAt1;
  decided_at?: DecidedAt;
  decision?: Decision1;
  expires_at?: ExpiresAt;
  id: Id1;
  node_id: NodeId1;
  parameters: Parameters;
  request_digest: RequestDigest1;
  run_id: RunId1;
}
export interface Parameters {
  [k: string]: JsonValue;
}
export interface ArtifactMetadata {
  created_at: CreatedAt2;
  id: Id2;
  kind: Kind;
  media_type: MediaType;
  redaction_classification: RedactionClassification;
  run_id?: RunId2;
  sha256: Sha256;
  size_bytes: SizeBytes;
  storage_key: StorageKey;
  task_attempt_id?: TaskAttemptId;
}
export interface ConfigurationRevision {
  configuration_id: ConfigurationId;
  content_hash: ContentHash;
  created_at: CreatedAt3;
  id: Id3;
  key: Key;
  kind: ConfigurationKind;
  revision: Revision;
  schema_version?: SchemaVersion;
  spec: Spec;
}
export interface Spec {
  [k: string]: JsonValue;
}
export interface DemoDecision {
  decision: Decision2;
  decision_id: DecisionId;
  expected_run_version: ExpectedRunVersion1;
  idempotency_key: IdempotencyKey1;
}
export interface DemoDecisionView {
  decision: Decision3;
  id: Id4;
}
export interface DependencyPreparationEvidence {
  dependency_digest: DependencyDigest;
  finished_at?: FinishedAt;
  id: Id5;
  image_id: ImageId;
  lifecycle_scripts?: LifecycleScripts;
  lockfile_digest: LockfileDigest;
  lockfile_path: LockfilePath;
  output_artifact_id?: OutputArtifactId;
  output_truncated?: OutputTruncated;
  profile_digest: ProfileDigest;
  profile_revision_id: ProfileRevisionId1;
  registry_hosts: RegistryHosts;
  snapshot_id: SnapshotId;
  source_sha: SourceSha;
  started_at: StartedAt;
  status: Status2;
}
export interface DirectiveUpdate {
  constraints?: Constraints;
  expected_version: ExpectedVersion;
  idempotency_key: IdempotencyKey2;
  objective: Objective;
}
export interface Effect {
  created_at: CreatedAt4;
  external_id?: ExternalId;
  fence_generation: FenceGeneration;
  id: Id6;
  idempotency_key: IdempotencyKey3;
  kind: Kind1;
  request_digest: RequestDigest2;
  result?: Result;
  run_id: RunId3;
  status: EffectStatus;
  task_attempt_id?: TaskAttemptId1;
  updated_at: UpdatedAt;
}
export interface EventPage {
  after: After;
  high_watermark: HighWatermark;
  items: Items2;
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
  idempotency_key?: IdempotencyKey4;
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
  run_id?: RunId4;
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
export interface ExecutionProfileTemplatePage {
  items: Items3;
}
/**
 * Versioned public profile policy. Runtime evidence binds its resolved image ID.
 */
export interface ExecutionProfileSpec {
  dependencies?: DependencyPolicy;
  image_reference: ImageReference;
  kind?: Kind3;
  max_files?: MaxFiles;
  max_source_bytes?: MaxSourceBytes;
  network?: NetworkPolicy;
  profile_key: ProfileKey;
  profile_version?: ProfileVersion;
  project_types: ProjectTypes;
  resources?: ResourceBounds;
  source_formats: SourceFormats;
  supported_commands: SupportedCommands;
  tool_versions: ToolVersions;
}
export interface DependencyPolicy {
  cache_max_mb?: CacheMaxMb;
  lifecycle_scripts?: LifecycleScripts1;
  lockfiles?: Lockfiles;
  manager?: Manager;
  registry_allowlist?: RegistryAllowlist;
  require_integrity?: RequireIntegrity;
  require_lockfile?: RequireLockfile;
}
export interface NetworkPolicy {
  deny_host?: DenyHost;
  deny_lan?: DenyLan;
  deny_metadata?: DenyMetadata;
  deny_public_internet?: DenyPublicInternet;
  preparation?: Preparation;
  verification?: Verification;
}
export interface ResourceBounds {
  cpu_count?: CpuCount;
  memory_mb?: MemoryMb;
  output_bytes?: OutputBytes;
  pids?: Pids;
  timeout_seconds?: TimeoutSeconds;
  workspace_mb?: WorkspaceMb;
}
export interface ToolVersions {
  [k: string]: string;
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
  id: Id7;
}
export interface IdempotencyContract {
  key: Key1;
  request_digest: RequestDigest3;
  response_status?: ResponseStatus;
  scope: Scope;
  state: State;
}
export interface IntegrationHeadPage {
  items: Items4;
  next_after: NextAfter2;
}
export interface IntegrationHeadView {
  base_sha: BaseSha;
  branch: Branch;
  expires_at: ExpiresAt1;
  generation: Generation;
  head_sha: HeadSha;
  lease_owner: LeaseOwner;
  released_at: ReleasedAt;
  repository_id: RepositoryId;
  snapshot_artifact_id: SnapshotArtifactId;
}
export interface Job {
  created_at: CreatedAt5;
  id: Id8;
  objective: Objective1;
  project_id: ProjectId2;
  status: JobStatus;
  thread_id?: ThreadId1;
  updated_at: UpdatedAt1;
  version: Version;
}
export interface JobCreate {
  demo_fixture?: DemoFixture | null;
  idempotency_key: IdempotencyKey5;
  mode?: Mode;
  objective: Objective2;
  priority?: Priority;
  workflow_version_id: WorkflowVersionId;
}
export interface DemoFixture {
  ci?: Ci;
  clock?: Clock;
  delay_seconds?: DelaySeconds;
  health?: Health;
  scenario?: Scenario;
  seed?: Seed;
}
export interface JobPage {
  items: Items5;
  next_after?: NextAfter3;
}
export interface JobView {
  id: Id9;
  objective: Objective3;
  project_id: ProjectId3;
  status: Status3;
}
export interface Lease {
  acquired_at: AcquiredAt;
  expires_at: ExpiresAt2;
  generation: Generation1;
  id: Id10;
  owner_instance_id: OwnerInstanceId;
  released_at?: ReleasedAt1;
  run_id: RunId5;
}
export interface LivenessResponse {
  service?: Service;
  status?: Status4;
  version?: Version1;
}
export interface LoginRequest {
  password: Password;
  username: Username;
}
export interface LogoutResponse {
  revoked: Revoked;
}
export interface ManagementTurnPage {
  items: Items6;
  next_after?: NextAfter4;
}
export interface ManagementTurnView {
  completed_at?: CompletedAt;
  created_at: CreatedAt6;
  decision?: ManagerDecision | null;
  directive_version: DirectiveVersion;
  failure_code?: FailureCode;
  id: Id11;
  model_call_id?: ModelCallId;
  status: Status5;
  team_version: TeamVersion;
}
export interface ManagerDecision {
  action: Action;
  lifecycle?: Lifecycle;
  message: Message2;
  scheduled_wakeup_at?: ScheduledWakeupAt;
  work_items?: WorkItems;
}
export interface WorkItemProposal {
  acceptance_criteria: AcceptanceCriteria;
  dependencies?: Dependencies;
  key: Key2;
  objective: Objective4;
  priority?: Priority1;
  title: Title;
}
export interface MissionAutonomyUpdate {
  enabled: Enabled;
  expected_version: ExpectedVersion1;
  idempotency_key: IdempotencyKey6;
}
export interface MissionControlRequest {
  action: Action1;
  expected_version: ExpectedVersion2;
  idempotency_key: IdempotencyKey7;
  instruction?: Instruction;
  limits?: MissionResourceLimits | null;
  scope?: Scope1;
}
/**
 * Conservative UTC-window limits for unattended mission activity.
 */
export interface MissionResourceLimits {
  currency?: Currency2;
  max_active_jobs?: MaxActiveJobs;
  max_calls?: MaxCalls;
  max_cost?: MaxCost;
  max_input_tokens?: MaxInputTokens;
  max_iterations?: MaxIterations;
  max_new_work_items?: MaxNewWorkItems;
  max_output_tokens?: MaxOutputTokens;
  max_wall_seconds?: MaxWallSeconds;
  timezone?: Timezone;
  window_seconds?: WindowSeconds;
}
export interface MissionControlView {
  instruction?: Instruction1;
  limits: MissionResourceLimits;
  scope: Scope2;
  state: State1;
  version: Version2;
}
export interface MissionCreate {
  autonomous?: Autonomous;
  constraints?: Constraints1;
  idempotency_key: IdempotencyKey8;
  limits?: MissionResourceLimits;
  mode?: Mode1;
  objective: Objective5;
  project_id: ProjectId4;
  team_template_revision_id: TeamTemplateRevisionId;
}
export interface MissionMessageCreate {
  allow_paid_inference?: AllowPaidInference;
  body: Body;
  expected_version: ExpectedVersion3;
  idempotency_key: IdempotencyKey9;
}
export interface MissionMessagePage {
  items: Items7;
  next_after?: NextAfter5;
}
export interface MissionMessageView {
  body: Body1;
  created_at: CreatedAt7;
  directive_version: DirectiveVersion1;
  disposition?: Disposition;
  id: Id12;
  identity: Identity;
  management_turn_id?: ManagementTurnId;
  role: Role;
  sequence: Sequence;
}
export interface MissionPage {
  items: Items8;
  next_after?: NextAfter6;
}
export interface MissionView {
  active_work_directive_version?: ActiveWorkDirectiveVersion;
  autonomous?: Autonomous1;
  constraints: Constraints2;
  controls?: Controls;
  created_at: CreatedAt8;
  directive_version: DirectiveVersion2;
  id: Id13;
  lifecycle: Lifecycle1;
  mode: Mode2;
  next_action?: NextAction;
  next_action_basis?: NextActionBasis;
  objective: Objective6;
  paid_unattended_available?: PaidUnattendedAvailable;
  project_id: ProjectId5;
  team_version: TeamVersion1;
  updated_at: UpdatedAt2;
  usage?: MissionUsageView | null;
  user_action_required?: UserActionRequired;
  version: Version3;
  waiting_reason?: WaitingReason;
}
export interface Controls {
  [k: string]: string;
}
export interface MissionUsageView {
  actual: Actual;
  limits: MissionResourceLimits;
  reserved: Reserved;
  timezone?: Timezone1;
  unknown_liability?: UnknownLiability;
  window_seconds: WindowSeconds1;
  window_started_at: WindowStartedAt;
}
export interface Actual {
  [k: string]: number | string | null;
}
export interface Reserved {
  [k: string]: number | string | null;
}
export interface MissionTeamUpdate {
  expected_version: ExpectedVersion4;
  idempotency_key: IdempotencyKey10;
  team_template_revision_id: TeamTemplateRevisionId1;
}
export interface MissionTeamVersionPage {
  items: Items9;
  next_after?: NextAfter7;
}
export interface MissionTeamVersionView {
  active: Active;
  content_hash: ContentHash1;
  created_at: CreatedAt9;
  id: Id14;
  selection: FixedTeamSelection;
  version: Version4;
}
export interface FixedTeamSelection {
  budgets?: TeamBudgetPolicy;
  developer_role_revision_id: DeveloperRoleRevisionId;
  developer_worker_revision_id: DeveloperWorkerRevisionId;
  eligible_worker_revision_ids?: EligibleWorkerRevisionIds;
  escalation_policy_revision_id?: EscalationPolicyRevisionId;
  manager_profile_revision_id: ManagerProfileRevisionId;
  manager_role_revision_id: ManagerRoleRevisionId;
  members?: Members;
  reviewer_profile_revision_id: ReviewerProfileRevisionId;
  reviewer_role_revision_id: ReviewerRoleRevisionId;
  team_template_revision_id: TeamTemplateRevisionId2;
  worker_pool_snapshot_hash?: WorkerPoolSnapshotHash;
  workflow_version_id: WorkflowVersionId1;
}
export interface TeamBudgetPolicy {
  max_active_assignments?: MaxActiveAssignments;
  max_execution_seconds?: MaxExecutionSeconds;
  max_inference_calls?: MaxInferenceCalls;
  reserve_management_slots?: ReserveManagementSlots;
  reserve_review_slots?: ReserveReviewSlots;
}
/**
 * A capability request. Scheduling chooses a concrete permitted worker.
 */
export interface TeamMemberSpec {
  allowed_tools: AllowedTools;
  key: Key3;
  may_execute?: MayExecute;
  may_review?: MayReview;
  model_route_revision_id: ModelRouteRevisionId;
  permission_policy_revision_id: PermissionPolicyRevisionId;
  required_capabilities?: RequiredCapabilities;
  role_revision_id: RoleRevisionId;
  worker_pool_revision_ids?: WorkerPoolRevisionIds;
}
export interface MissionWakeupPage {
  items: Items10;
  next_after?: NextAfter8;
}
export interface MissionWakeupView {
  created_at: CreatedAt10;
  deduplication_key: DeduplicationKey;
  directive_version: DirectiveVersion3;
  id: Id15;
  kind: Kind4;
  management_turn_id?: ManagementTurnId1;
  scheduled_for: ScheduledFor;
  source_event_cursor?: SourceEventCursor;
  status: Status6;
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
  idempotency_key?: IdempotencyKey11;
  message: Message3;
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
export interface ProjectCreate {
  execution_profile_revision_ids?: ExecutionProfileRevisionIds;
  idempotency_key: IdempotencyKey12;
  name: Name1;
  project_type?: ProjectType;
  slug: Slug;
}
export interface ProjectPage {
  items: Items11;
  next_after?: NextAfter9;
}
export interface ProjectView {
  execution_profile_revision_ids?: ExecutionProfileRevisionIds1;
  id: Id16;
  name: Name2;
  project_type?: ProjectType1;
  slug: Slug1;
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
  profile_revision_id: ProfileRevisionId2;
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
  message: Message4;
  request_id?: RequestId2;
  retry_after_seconds?: RetryAfterSeconds;
  retryable: Retryable1;
}
export interface ProviderToolCall {
  arguments: Arguments;
  id: Id17;
  name: Name3;
}
export interface Arguments {
  [k: string]: JsonValue;
}
export interface ProviderRequest {
  correlation_id: CorrelationId3;
  data_classification?: DataClassification;
  node_id?: NodeId2;
  output_tokens: OutputTokens1;
  project_id?: ProjectId6;
  purpose: Purpose;
  run_id?: RunId6;
  structured_schema?: StructuredSchema;
  task_id?: TaskId2;
  text: Text2;
  tools?: Tools;
}
export interface ProviderTool {
  description?: Description;
  name: Name4;
  parameters: Parameters1;
}
export interface Parameters1 {
  [k: string]: JsonValue;
}
export interface ReadinessResponse {
  api?: Api;
  database: Database;
  execution?: Execution;
  schema_revision?: SchemaRevision;
  scope?: Scope3;
  status: Status7;
}
export interface RegistryPage {
  items: Items12;
  next_after?: NextAfter10;
}
export interface RegistryRecord {
  archived: Archived;
  circuit_state?: CircuitState;
  content_hash: ContentHash2;
  created_at: CreatedAt11;
  created_by?: CreatedBy;
  description: Description1;
  display_name: DisplayName;
  enabled: Enabled1;
  health?: Health1;
  id: Id18;
  key: Key4;
  revision: Revision1;
  revision_id: RevisionId;
  secret_label?: SecretLabel;
  secret_status?: SecretStatus;
  spec: Spec1;
  updated_at: UpdatedAt3;
  version: Version5;
  worker_runtime?: WorkerRuntimeFacts | null;
}
/**
 * Versioned responsibility; execution bindings remain separate.
 */
export interface AgentRoleSpec {
  instructions: Instructions;
  kind?: Kind5;
  purpose: Purpose1;
  responsibility: Responsibility;
}
/**
 * Fixed mission team whose referenced revisions are resolved at assignment.
 */
export interface TeamTemplateSpec {
  budgets?: TeamBudgetPolicy;
  developer_role_revision_id: DeveloperRoleRevisionId1;
  developer_worker_revision_id: DeveloperWorkerRevisionId1;
  escalation_policy_revision_id?: EscalationPolicyRevisionId1;
  kind?: Kind6;
  manager_profile_revision_id: ManagerProfileRevisionId1;
  manager_role_revision_id: ManagerRoleRevisionId1;
  members?: Members1;
  mode: Mode3;
  reviewer_profile_revision_id: ReviewerProfileRevisionId1;
  reviewer_role_revision_id: ReviewerRoleRevisionId1;
  workflow_version_id: WorkflowVersionId2;
}
export interface WorkerSpec {
  adapter_kind?: AdapterKind;
  capabilities?: Capabilities;
  deployment_configured?: DeploymentConfigured;
  execution_host_label?: ExecutionHostLabel;
  execution_profile_revision_ids?: ExecutionProfileRevisionIds2;
  kind?: Kind7;
  labels?: Labels;
  max_concurrency?: MaxConcurrency;
  model_binding?: ModelBinding;
  observed_build_digest?: ObservedBuildDigest;
  observed_wrapper_version?: ObservedWrapperVersion;
  permitted_project_ids?: PermittedProjectIds;
  physical_resource_id?: PhysicalResourceId;
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
  mode?: Mode4;
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
  kind?: Kind8;
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
  kind?: Kind9;
  locality?: Locality1;
  model_identifier: ModelIdentifier1;
  output_limit: OutputLimit;
  parameters?: Parameters2;
  pricing?: Pricing;
  provider_revision_id: ProviderRevisionId2;
  purposes: Purposes;
  streaming?: Streaming;
  structured_json?: StructuredJson;
  tool_calls?: ToolCalls1;
  usage_reporting?: UsageReporting;
}
export interface Parameters2 {
  [k: string]: JsonValue;
}
export interface RoutePolicySpec {
  allow_remote?: AllowRemote;
  allow_unknown_health?: AllowUnknownHealth;
  allowed_data?: AllowedData1;
  candidates: Candidates;
  failover_classes?: FailoverClasses;
  kind?: Kind10;
  purposes: Purposes1;
  required_capabilities?: RequiredCapabilities1;
  spend?: SpendPolicy;
}
export interface RouteCandidate {
  priority?: Priority2;
  profile_revision_id: ProfileRevisionId3;
}
export interface SpendPolicy {
  allow_paid?: AllowPaid;
  max_call_cost?: MaxCallCost;
  max_input_tokens?: MaxInputTokens1;
  max_output_tokens?: MaxOutputTokens1;
  max_run_cost?: MaxRunCost;
  on_exceeded?: OnExceeded;
}
export interface RetryRegistrySpec {
  kind?: Kind11;
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
  kind?: Kind12;
  network?: Network;
  remote_provider?: RemoteProvider;
  sensitive_action?: SensitiveAction;
  shell?: Shell;
  unknown_action?: UnknownAction;
}
/**
 * Versioned allowlist of explicitly registered worker revisions.
 */
export interface WorkerPoolSpec {
  health_freshness_seconds?: HealthFreshnessSeconds;
  kind?: Kind13;
  permitted_project_ids?: PermittedProjectIds1;
  required_capabilities?: RequiredCapabilities2;
  worker_revision_ids: WorkerRevisionIds;
}
export interface WorkerRuntimeFacts {
  exclusive_workspace?: ExclusiveWorkspace;
  last_heartbeat_at?: LastHeartbeatAt;
  possibly_stalled?: PossiblyStalled;
  slots_in_use?: SlotsInUse;
  validated_at?: ValidatedAt;
  validation_issues?: ValidationIssues;
}
export interface RegistryWrite {
  archived?: Archived1;
  clear_secret?: ClearSecret;
  deployment_ref?: DeploymentRef;
  description?: Description2;
  display_name: DisplayName1;
  enabled?: Enabled2;
  expected_version?: ExpectedVersion5;
  idempotency_key: IdempotencyKey13;
  key: Key5;
  secret_ref?: SecretRef;
  spec: Spec2;
}
export interface RepositoryContextSnapshot {
  context_digest: ContextDigest;
  coverage: Coverage;
  created_at: CreatedAt12;
  entries: Entries;
  id: Id19;
  omitted_paths: OmittedPaths;
  repository_id: RepositoryId1;
  run_id: RunId7;
  selection: Selection;
  selection_policy: SelectionPolicy;
  source_sha: SourceSha1;
  tree_sha: TreeSha;
}
export interface RepositoryContextEntry {
  content_digest: ContentDigest;
  end_line: EndLine;
  path: Path;
  provenance: Provenance1;
  start_line: StartLine;
}
export interface RetryPolicySpec {
  rules: Rules1;
  schema_version?: SchemaVersion4;
}
export interface ReviewDecision {
  findings?: Findings;
  finished_at: FinishedAt1;
  id: Id20;
  reviewed_head_sha: ReviewedHeadSha;
  reviewed_snapshot_id: ReviewedSnapshotId;
  reviewer_revision: ReviewerRevision;
  snapshot_digest: SnapshotDigest;
  started_at: StartedAt1;
  summary: Summary3;
  task_attempt_id: TaskAttemptId3;
  task_id: TaskId3;
  verdict: Verdict;
}
export interface ReviewFinding {
  criterion_index: CriterionIndex;
  source_path: SourcePath;
  summary: Summary2;
}
export interface ReviewEvidence {
  acceptance_criteria: AcceptanceCriteria1;
  architecture_artifact_ids?: ArchitectureArtifactIds;
  config_snapshot_id: ConfigSnapshotId;
  failure_history_artifact_id: FailureHistoryArtifactId;
  objective: Objective7;
  prior_feedback_artifact_ids: PriorFeedbackArtifactIds;
  snapshot: SealedRepositorySnapshot;
  task_attempt_id: TaskAttemptId5;
  task_id: TaskId4;
  task_title: TaskTitle;
  verification_artifact_ids: VerificationArtifactIds;
  workflow_version_id: WorkflowVersionId3;
}
export interface SealedRepositorySnapshot {
  base_sha: BaseSha1;
  branch: Branch1;
  content_digest: ContentDigest1;
  created_at: CreatedAt13;
  cumulative_diff_artifact_id: CumulativeDiffArtifactId;
  file_count: FileCount;
  git_status?: GitStatus;
  head_sha: HeadSha1;
  id: Id21;
  latest_base_sha: LatestBaseSha;
  latest_diff_artifact_id: LatestDiffArtifactId;
  lfs?: Lfs;
  manifest_artifact_id: ManifestArtifactId;
  repository_id: RepositoryId2;
  run_id: RunId8;
  source_artifact_id: SourceArtifactId;
  submodules?: Submodules;
  task_attempt_id: TaskAttemptId4;
  tree_sha: TreeSha1;
  worker_result_id: WorkerResultId;
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
  purpose: Purpose2;
  run_spend?: RunSpend;
}
export interface RouteResolution {
  candidates?: Candidates1;
  decision?: Decision4;
  demo?: Demo3;
  reasons?: Reasons1;
  route_revision_id: RouteRevisionId2;
  selected_profile_revision_id?: SelectedProfileRevisionId;
  selected_provider_revision_id?: SelectedProviderRevisionId;
  snapshot_hash: SnapshotHash;
}
export interface CandidateDecision {
  eligible: Eligible;
  profile_revision_id: ProfileRevisionId4;
  reasons?: Reasons;
}
export interface Run {
  claimable_at: ClaimableAt;
  config_snapshot_id: ConfigSnapshotId1;
  created_at: CreatedAt14;
  desired_state: DesiredRunState;
  id: Id22;
  job_id: JobId1;
  langgraph_thread_id: LanggraphThreadId;
  run_number: RunNumber;
  status: RunStatus;
  updated_at: UpdatedAt4;
  version: Version6;
  workflow_version_id: WorkflowVersionId4;
}
export interface RunCommand {
  created_at: CreatedAt15;
  id: Id23;
  idempotency_key: IdempotencyKey14;
  kind: RunCommandKind;
  payload: Payload;
  request_digest: RequestDigest4;
  run_id: RunId9;
  sequence: Sequence1;
  status: CommandStatus;
}
export interface Payload {
  [k: string]: JsonValue;
}
export interface RunCommandReceipt {
  command_id: CommandId;
  duplicate?: Duplicate;
  request_digest: RequestDigest5;
  run_id: RunId10;
  schema_version?: SchemaVersion5;
  sequence: Sequence2;
  status: CommandStatus;
}
export interface RunCommandRequest {
  expected_run_version?: ExpectedRunVersion2;
  idempotency_key: IdempotencyKey15;
  kind: RunCommandKind;
  payload?: Payload1;
  run_id: RunId11;
  schema_version?: SchemaVersion6;
}
export interface Payload1 {
  [k: string]: JsonValue;
}
export interface RunConfigurationSnapshot {
  created_at: CreatedAt16;
  effective_spec: EffectiveSpec;
  id: Id24;
  resolved_revisions: ResolvedRevisions;
  schema_version?: SchemaVersion7;
  snapshot_hash: SnapshotHash1;
  workflow_content_hash: WorkflowContentHash;
  workflow_version_id: WorkflowVersionId5;
}
export interface EffectiveSpec {
  [k: string]: JsonValue;
}
export interface ResolvedRevision {
  content_hash: ContentHash3;
  key: Key6;
  kind: ConfigurationKind;
  revision_id: RevisionId1;
}
export interface RunControl {
  expected_run_version: ExpectedRunVersion3;
  idempotency_key: IdempotencyKey16;
  instruction?: Instruction2;
  kind: RunCommandKind;
}
export interface RunEventSnapshotResponse {
  last_event_at: LastEventAt;
  last_event_position: LastEventPosition;
  last_run_sequence: LastRunSequence;
  read_cursor: ReadCursor;
  run_id: RunId12;
  status: Status8;
}
export interface RunPage {
  items: Items13;
  next_after?: NextAfter11;
}
export interface RunView {
  claimable_at: ClaimableAt1;
  completed_at: CompletedAt1;
  current_node: CurrentNode;
  desired_state: DesiredState;
  id: Id25;
  job_id: JobId2;
  last_event_at: LastEventAt1;
  last_event_position: LastEventPosition1;
  last_run_sequence: LastRunSequence1;
  mode: Mode5;
  project_id: ProjectId7;
  recovering: Recovering;
  result_summary: ResultSummary;
  retry_of_run_id: RetryOfRunId;
  run_number: RunNumber1;
  started_at: StartedAt2;
  status: Status9;
  thread_id: ThreadId2;
  version: Version7;
  workflow_version_id: WorkflowVersionId6;
}
export interface RunReconciliationReceipt {
  duplicate?: Duplicate1;
  effect_id: EffectId;
  effect_status: EffectStatus1;
  queued_for_inspection: QueuedForInspection;
  run_id: RunId13;
}
/**
 * Request evidence collection for an existing ambiguous external identity.
 */
export interface RunReconciliationRequest {
  effect_id: EffectId1;
  expected_run_version: ExpectedRunVersion4;
  idempotency_key: IdempotencyKey17;
}
export interface RunUsage {
  calls: Calls;
  currencies: Currencies;
  known_tokens: KnownTokens;
  provenance: Provenance2;
  total_tokens: TotalTokens1;
  unknown_usage_calls: UnknownUsageCalls;
  worker_usage?: WorkerUsage;
}
export interface CurrencyUsage {
  currency: Currency3;
  known_subtotal: KnownSubtotal;
  status: Status10;
  total: Total;
  unknown_calls: UnknownCalls;
}
export interface CommandPage {
  items: Items14;
  next_after?: NextAfter12;
}
export interface CommandView {
  applied_at: AppliedAt;
  id: Id26;
  kind: Kind14;
  sequence: Sequence3;
  status: Status11;
}
export interface NodePage {
  items: Items15;
  next_after?: NextAfter13;
}
export interface NodeView {
  completed_at: CompletedAt2;
  execution_number: ExecutionNumber;
  id: Id27;
  started_at: StartedAt3;
  status: Status12;
  task_attempt_id: TaskAttemptId6;
  task_id: TaskId5;
  workflow_node_id: WorkflowNodeId1;
}
export interface TaskPage {
  items: Items16;
  next_after?: NextAfter14;
}
export interface TaskView {
  attempts: Attempts;
  dependencies: Dependencies1;
  id: Id29;
  key: Key7;
  status: Status14;
  title: Title1;
  weight: Weight;
}
export interface AttemptView {
  id: Id28;
  number: Number;
  snapshot_digest: SnapshotDigest1;
  status: Status13;
}
export interface SessionResponse {
  absolute_expires_at: AbsoluteExpiresAt;
  csrf_token: CsrfToken;
  idle_expires_at: IdleExpiresAt;
  user: SessionUser;
}
export interface SessionUser {
  id: Id30;
  role?: Role1;
  username: Username1;
}
export interface SystemHealth {
  accepting_instances: AcceptingInstances;
  control_plane?: ControlPlane;
  database?: Database1;
  execution: Execution1;
  execution_reasons: ExecutionReasons;
  expired_active_leases: ExpiredActiveLeases;
  heartbeat_stale_after_seconds: HeartbeatStaleAfterSeconds;
  last_heartbeat_at: LastHeartbeatAt1;
  observed_at: ObservedAt;
  orchestrator: Orchestrator;
  provider: Provider;
  repository_binding: RepositoryBinding;
  run_counts: RunCounts;
  runtime_manifest: RuntimeManifest;
  runtime_manifest_sha256?: RuntimeManifestSha256;
  runtime_mode: RuntimeMode;
  verification_broker: VerificationBroker;
  worker: Worker;
}
export interface RunCounts {
  [k: string]: number;
}
export interface Task {
  acceptance_criteria: AcceptanceCriteria2;
  created_at: CreatedAt17;
  id: Id31;
  key: Key8;
  run_id: RunId14;
  status: TaskStatus;
  title: Title2;
  updated_at: UpdatedAt5;
  verification: Verification1;
  version: Version8;
  weight?: Weight1;
}
export interface Verification1 {
  [k: string]: JsonValue;
}
export interface TaskAttempt {
  attempt_number: AttemptNumber;
  base_sha?: BaseSha2;
  completed_at?: CompletedAt3;
  id: Id32;
  result_sha?: ResultSha;
  started_at?: StartedAt4;
  status: AttemptStatus;
  task_id: TaskId6;
}
export interface ValidationReport {
  demo?: Demo4;
  health?: Health2;
  issues?: Issues;
  network_checked?: NetworkChecked;
  valid: Valid;
}
export interface VerificationExecution {
  command: VerificationCommand;
  command_digest?: CommandDigest;
  cwd: Cwd;
  dependency_digest?: DependencyDigest1;
  environment_keys: EnvironmentKeys;
  exit_code?: ExitCode;
  failure_class?: FailureClass1;
  finished_at?: FinishedAt2;
  id: Id33;
  image_id?: ImageId1;
  parsed?: ParsedVerification | null;
  phase?: Phase;
  profile_digest?: ProfileDigest1;
  profile_revision_id?: ProfileRevisionId6;
  required_checks_digest?: RequiredChecksDigest;
  run_id: RunId15;
  snapshot_id: SnapshotId1;
  source_sha: SourceSha2;
  started_at: StartedAt5;
  status: Status15;
  stderr_artifact_id?: StderrArtifactId;
  stderr_truncated?: StderrTruncated;
  stdout_artifact_id?: StdoutArtifactId;
  stdout_truncated?: StdoutTruncated;
  task_attempt_id: TaskAttemptId7;
  task_id: TaskId7;
}
export interface VerificationCommand {
  argv: Argv;
  environment?: Environment;
  expected_exit_codes?: ExpectedExitCodes;
  kind?: Kind15;
  max_output_bytes?: MaxOutputBytes;
  parser?: Parser;
  profile_revision_id?: ProfileRevisionId5;
  purpose?: Purpose3;
  require_nonempty_suite?: RequireNonemptySuite;
  required_check_id?: RequiredCheckId;
  timeout_seconds?: TimeoutSeconds1;
  working_root_policy?: WorkingRootPolicy;
}
export interface Environment {
  [k: string]: string;
}
export interface ParsedVerification {
  complete?: Complete;
  confidence: Confidence;
  errors?: Errors;
  failed?: Failed;
  parser: Parser1;
  passed?: Passed;
  skipped?: Skipped;
  summary: Summary4;
}
export interface WorkItemPage {
  items: Items17;
  next_after?: NextAfter15;
}
export interface WorkItemView {
  acceptance_criteria: AcceptanceCriteria3;
  assignment_status?: AssignmentStatus;
  created_at: CreatedAt18;
  dependencies: Dependencies2;
  directive_version: DirectiveVersion4;
  id: Id34;
  job_id?: JobId3;
  key: Key9;
  lifecycle: Lifecycle2;
  merge_queue_status?: MergeQueueStatus;
  objective: Objective8;
  priority: Priority3;
  queued_reason?: QueuedReason;
  run_id?: RunId16;
  selected_model_profile_revision_id?: SelectedModelProfileRevisionId;
  selected_worker_revision_id?: SelectedWorkerRevisionId;
  team_version: TeamVersion2;
  team_version_id: TeamVersionId;
  title: Title3;
}
export interface WorkItemStart {
  expected_mission_version: ExpectedMissionVersion;
  idempotency_key: IdempotencyKey18;
}
export interface CancelResult {
  invocation_id: InvocationId;
  status: Status16;
}
export interface WorkerEvent {
  invocation_id: InvocationId1;
  occurred_at: OccurredAt2;
  source_sequence: SourceSequence1;
  type: Type2;
}
export interface WorkerInvocationHandle {
  generation: Generation2;
  invocation_id: InvocationId2;
  request_digest: RequestDigest6;
  worker_revision_id: WorkerRevisionId;
}
export interface WorkerHealth {
  capabilities?: Capabilities3;
  issues?: Issues1;
  network_checked?: NetworkChecked1;
  observed_at: ObservedAt1;
  status: Status17;
}
export interface WorkerInvocationRequest {
  allowed_tools?: AllowedTools1;
  architecture_artifact_id?: ArchitectureArtifactId;
  feedback_artifact_ids?: FeedbackArtifactIds;
  idempotency_key: IdempotencyKey19;
  invocation_id: InvocationId3;
  lease: WorkerSlotFence;
  limits?: WorkerLimits;
  model_profile_revision_id: ModelProfileRevisionId;
  objective: Objective9;
  permission_policy_revision_id?: PermissionPolicyRevisionId1;
  project: WorkerProject;
  protocol_version?: ProtocolVersion;
  required_capabilities?: RequiredCapabilities3;
  run_id: RunId17;
  task: WorkerTask;
  task_attempt_id: TaskAttemptId8;
  task_id: TaskId8;
  worker_revision_id: WorkerRevisionId2;
}
export interface WorkerSlotFence {
  expires_at: ExpiresAt3;
  generation: Generation3;
  lease_id: LeaseId;
  physical_resource_id?: PhysicalResourceId1;
  run_generation: RunGeneration;
  slot: Slot;
  worker_revision_id: WorkerRevisionId1;
}
export interface WorkerLimits {
  max_output_bytes?: MaxOutputBytes1;
  max_result_bytes?: MaxResultBytes;
  max_runtime_seconds?: MaxRuntimeSeconds;
}
export interface WorkerProject {
  base_sha: BaseSha3;
  branch: Branch2;
  project_id: ProjectId8;
  repository_id: RepositoryId3;
  slug: Slug2;
  workspace_root: WorkspaceRoot;
}
export interface WorkerTask {
  acceptance_criteria: AcceptanceCriteria4;
  description: Description3;
  key: Key10;
  title: Title4;
  verification?: Verification2;
}
/**
 * M7-compatible name for the authoritative verification command contract.
 */
export interface WorkerVerification {
  argv: Argv1;
  environment?: Environment1;
  expected_exit_codes?: ExpectedExitCodes1;
  kind?: Kind16;
  max_output_bytes?: MaxOutputBytes2;
  parser?: Parser2;
  profile_revision_id?: ProfileRevisionId7;
  purpose?: Purpose4;
  require_nonempty_suite?: RequireNonemptySuite1;
  required_check_id?: RequiredCheckId1;
  timeout_seconds?: TimeoutSeconds2;
  working_root_policy?: WorkingRootPolicy1;
}
export interface Environment1 {
  [k: string]: string;
}
export interface PreparedInvocation {
  request: WorkerInvocationRequest;
  request_digest: RequestDigest7;
}
export interface ReconciliationResult {
  invocation_id: InvocationId4;
  safe_to_start?: SafeToStart;
  state: State2;
}
export interface WorkerResult {
  artifact_manifest: ArtifactManifest;
  branch: Branch3;
  end_head: EndHead;
  error?: Error;
  finished_at: FinishedAt3;
  generation: Generation4;
  invocation_id: InvocationId5;
  model_profile_revision_id: ModelProfileRevisionId1;
  protocol_version?: ProtocolVersion1;
  repository_snapshot: WorkerRepositorySnapshot;
  request_digest: RequestDigest8;
  source_sequence: SourceSequence2;
  start_head: StartHead;
  started_at: StartedAt6;
  status: Status18;
  summary: Summary5;
  task_attempt_id: TaskAttemptId9;
  task_id: TaskId9;
  workspace_root: WorkspaceRoot1;
}
export interface WorkerArtifact {
  kind: Kind17;
  sha256: Sha2561;
  size_bytes: SizeBytes1;
}
export interface WorkerRepositorySnapshot {
  diff_digest: DiffDigest;
  file_count: FileCount1;
  git_status: GitStatus1;
  head_sha: HeadSha2;
  manifest_digest: ManifestDigest;
  metadata_truncated?: MetadataTruncated;
  status_digest: StatusDigest;
  tree_digest: TreeDigest;
}
export interface WorkerInvocationStatus {
  invocation_id: InvocationId6;
  last_activity_at?: LastActivityAt;
  possibly_stalled?: PossiblyStalled1;
  source_sequence?: SourceSequence3;
  state: State3;
}
export interface WorkerValidationReport {
  exclusive_workspace?: ExclusiveWorkspace1;
  health: WorkerHealth;
  valid: Valid1;
}
export interface WorkflowArchiveRequest {
  archived: Archived2;
  expected_version: ExpectedVersion6;
  idempotency_key: IdempotencyKey20;
}
export interface WorkflowCommand {
  expected_version: ExpectedVersion7;
  idempotency_key: IdempotencyKey21;
}
export interface WorkflowCreateRequest {
  description?: Description4;
  idempotency_key: IdempotencyKey22;
  key: Key11;
  name: Name5;
}
export interface WorkflowDocument {
  template: WorkflowTemplateRecord;
  version: WorkflowVersionRecord;
}
export interface WorkflowTemplateRecord {
  archived: Archived3;
  created_at: CreatedAt19;
  current_draft_version_id?: CurrentDraftVersionId;
  current_published_version_id?: CurrentPublishedVersionId;
  description: Description5;
  id: Id35;
  key: Key12;
  name: Name6;
  updated_at: UpdatedAt6;
  version: Version9;
}
export interface WorkflowVersionRecord {
  compiler_version: CompilerVersion;
  content_hash: ContentHash4;
  created_at: CreatedAt20;
  id: Id36;
  layout: WorkflowLayout;
  published: Published;
  published_at?: PublishedAt;
  snapshot_hash?: SnapshotHash2;
  spec: WorkflowSpec;
  version: Version10;
  workflow_template_id: WorkflowTemplateId;
}
export interface WorkflowLayout {
  nodes?: Nodes;
  viewport?: WorkflowViewport | null;
}
export interface Nodes {
  [k: string]: WorkflowPosition;
}
export interface WorkflowPosition {
  x: X;
  y: Y;
}
export interface WorkflowViewport {
  x: X1;
  y: Y1;
  zoom?: Zoom;
}
export interface WorkflowSpec {
  defaults?: NodePolicy;
  description?: Description6;
  edges: Edges;
  entrypoint: Entrypoint;
  key: Key13;
  name: Name7;
  nodes: Nodes1;
  outputs: WorkflowOutputs;
  reducers?: Reducers;
  spec_version?: SpecVersion;
  state_schema?: StateSchema;
}
export interface NodePolicy {
  accepts_runtime_instructions?: AcceptsRuntimeInstructions;
  approval?: ApprovalPolicy | null;
  max_concurrency?: MaxConcurrency1;
  model_route_ref?: ModelRouteRef;
  permission_policy_ref?: PermissionPolicyRef;
  retry_policy_ref?: RetryPolicyRef;
  timeout_seconds?: TimeoutSeconds3;
  verification?: VerificationPolicy | null;
  worker_selector?: WorkerSelector | null;
}
export interface ApprovalPolicy {
  action_type?: ActionType1;
  expires_in_seconds?: ExpiresInSeconds;
  required_grant_from?: RequiredGrantFrom;
}
export interface VerificationPolicy {
  execution_profile_revision_ids?: ExecutionProfileRevisionIds3;
  required?: Required;
  required_acceptance_checks?: RequiredAcceptanceChecks;
  source?: Source1;
}
export interface RequiredAcceptanceCheck {
  check_id: CheckId;
  command: VerificationCommand;
  profile_revision_id: ProfileRevisionId8;
  purpose: Purpose5;
}
export interface WorkerSelector {
  requires?: Requires;
  revision_id: RevisionId2;
}
export interface WorkflowEdge {
  fallback?: Fallback;
  from: From;
  id: Id37;
  iteration_key?: IterationKey;
  kind: WorkflowEdgeKind;
  max_iterations?: MaxIterations1;
  priority?: Priority4;
  progress_path?: ProgressPath;
  retry_class?: FailureClass | null;
  to: To;
  when?: Predicate | null;
}
export interface Predicate {
  args?: Args;
  op: PredicateOperator;
  path?: Path1;
  value?: unknown;
}
export interface WorkflowNode {
  config: Config;
  id: Id38;
  label: Label;
  node_version?: NodeVersion;
  policy?: NodePolicy;
  type: WorkflowNodeType;
}
export interface Config {
  [k: string]: JsonValue;
}
export interface WorkflowOutputs {
  result_path: ResultPath;
}
export interface Reducers {
  [k: string]: "merge_by_id" | "set_union" | "max_map";
}
export interface WorkflowDraftWrite {
  expected_version: ExpectedVersion8;
  idempotency_key: IdempotencyKey23;
  layout?: WorkflowLayout;
  spec: WorkflowSpec;
}
export interface WorkflowNewDraft {
  expected_version: ExpectedVersion9;
  idempotency_key: IdempotencyKey24;
  source_version_id?: SourceVersionId;
}
export interface OrganizerConfig {
  summary_limit?: SummaryLimit;
}
export interface ArchitectConfig {
  max_tasks?: MaxTasks;
  output_schema?: OutputSchema;
}
export interface DispatchConfig {
  parallelism?: Parallelism;
  ready_order?: ReadyOrder;
}
export interface WorkerConfig {
  task_source?: TaskSource;
}
export interface VerifyConfig {
  commands_source?: CommandsSource;
  stop_on_failure?: StopOnFailure;
}
export interface ReviewerConfig {
  requires_repository_snapshot?: RequiresRepositorySnapshot;
}
export interface IntegrateConfig {
  repository_source?: RepositorySource;
  run_combined_gates?: RunCombinedGates;
}
export interface RouterConfig {}
export interface FanoutConfig {
  cancellation_strategy?: CancellationStrategy;
  children?: Children;
  join_id?: JoinId;
  max_fanout?: MaxFanout;
}
export interface JoinConfig {
  fanout_id?: FanoutId;
  require_all?: RequireAll;
}
export interface ApprovalConfig {
  action_type?: ActionType2;
  expires_in_seconds?: ExpiresInSeconds1;
}
export interface PublishConfig {
  repository_source?: RepositorySource1;
  wait_for_ci?: WaitForCi;
}
export interface FinalizeConfig {
  outcome?: Outcome1;
}
export interface NodeTypePage {
  items: Items18;
}
export interface NodeTypeDefinition {
  config_schema: ConfigSchema;
  default_config: DefaultConfig;
  external_behavior: ExternalBehavior;
  input_channels: InputChannels;
  output_channels: OutputChannels;
  policy_schema: PolicySchema;
  required_capabilities: RequiredCapabilities4;
  type: WorkflowNodeType;
}
export interface ConfigSchema {
  [k: string]: JsonValue;
}
export interface DefaultConfig {
  [k: string]: JsonValue;
}
export interface PolicySchema {
  [k: string]: JsonValue;
}
export interface WorkflowResolvedSnapshot {
  compiler_version?: CompilerVersion1;
  revisions?: Revisions;
  workflow_content_hash: WorkflowContentHash1;
}
export interface WorkflowResolvedRevision {
  archived?: Archived4;
  configuration_id: ConfigurationId1;
  content_hash: ContentHash5;
  description?: Description7;
  display_name: DisplayName2;
  enabled?: Enabled3;
  key: Key14;
  revision: Revision2;
  revision_id: RevisionId3;
  spec: Spec3;
}
export interface WorkflowTemplatePage {
  items: Items19;
  next_after?: NextAfter16;
}
export interface WorkflowValidateRequest {
  expected_version: ExpectedVersion10;
  idempotency_key: IdempotencyKey25;
  layout?: Layout;
  spec: Spec4;
}
export interface Layout {
  [k: string]: JsonValue;
}
export interface Spec4 {
  [k: string]: JsonValue;
}
export interface WorkflowValidationReport {
  content_hash?: ContentHash6;
  issues?: Issues2;
  snapshot_hash?: SnapshotHash3;
  valid: Valid2;
}
export interface WorkflowIssue {
  code: Code4;
  edge_id?: EdgeId;
  message: Message5;
  node_id?: NodeId3;
  path?: Path2;
}
export interface WorkflowVersionContract {
  compiler_version: CompilerVersion2;
  content_hash: ContentHash7;
  id: Id39;
  layout: Layout1;
  published: Published1;
  spec: WorkflowSpec;
  spec_version?: SpecVersion1;
  version: Version11;
  workflow_template_id: WorkflowTemplateId1;
}
export interface Layout1 {
  [k: string]: JsonValue;
}
export interface WorkflowVersionPage {
  items: Items20;
  next_after?: NextAfter17;
}
