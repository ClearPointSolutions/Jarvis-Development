"""Stable status and classification vocabularies."""

from enum import StrEnum


class JobStatus(StrEnum):
    DRAFT = "draft"
    QUEUED = "queued"
    ACTIVE = "active"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class RunStatus(StrEnum):
    QUEUED = "queued"
    CLAIMING = "claiming"
    RUNNING = "running"
    PAUSE_REQUESTED = "pause_requested"
    PAUSED = "paused"
    APPROVAL_REQUIRED = "approval_required"
    CANCEL_REQUESTED = "cancel_requested"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class DesiredRunState(StrEnum):
    RUNNING = "running"
    PAUSED = "paused"
    CANCELLED = "cancelled"


class TaskStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    WAITING = "waiting"
    APPROVAL_REQUIRED = "approval_required"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


class AttemptStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    VERIFYING = "verifying"
    REVIEWING = "reviewing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class NodeExecutionStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING = "waiting"
    INTERRUPTED = "interrupted"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


class CommandStatus(StrEnum):
    PENDING = "pending"
    APPLYING = "applying"
    APPLIED = "applied"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class RunCommandKind(StrEnum):
    PAUSE = "pause"
    RESUME = "resume"
    CANCEL = "cancel"
    INSTRUCTION = "instruction"
    RETRY = "retry"


class EffectStatus(StrEnum):
    PREPARED = "prepared"
    DISPATCHED = "dispatched"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class EventMode(StrEnum):
    REAL = "real"
    DEMO = "demo"


class EventVisibility(StrEnum):
    OWNER = "owner"
    OPERATOR = "operator"
    INTERNAL = "internal"


class EventSeverity(StrEnum):
    DEBUG = "debug"
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class EventCategory(StrEnum):
    AUTH = "auth"
    CONFIG = "config"
    THREAD = "thread"
    JOB = "job"
    RUN = "run"
    GRAPH = "graph"
    NODE = "node"
    TASK = "task"
    WORKER = "worker"
    MODEL = "model"
    TOOL = "tool"
    FILE = "file"
    COMMAND = "command"
    TEST = "test"
    REVIEW = "review"
    GIT = "git"
    APPROVAL = "approval"
    ARTIFACT = "artifact"
    FAILURE = "failure"
    SYSTEM = "system"


class FailureClass(StrEnum):
    CODE_IMPLEMENTATION_FAILURE = "code.implementation_failure"
    CODE_TEST_FAILURE = "code.test_failure"
    CODE_REVIEW_FAILURE = "code.review_failure"
    CODE_GIT_CONFLICT = "code.git_conflict"
    INFRASTRUCTURE_WORKER_UNAVAILABLE = "infrastructure.worker_unavailable"
    INFRASTRUCTURE_WORKER_TRANSPORT = "infrastructure.worker_transport"
    INFRASTRUCTURE_SERVICE_UNAVAILABLE = "infrastructure.service_unavailable"
    PROVIDER_RATE_LIMITED = "provider.rate_limited"
    PROVIDER_TRANSIENT = "provider.transient"
    PROVIDER_CONTRACT_FAILURE = "provider.contract_failure"
    CONFIGURATION_INVALID = "configuration.invalid"
    SECURITY_POLICY_DENIED = "security.policy_denied"
    APPROVAL_REJECTED = "approval.rejected"
    ORCHESTRATION_RUNTIME_ERROR = "orchestration.runtime_error"
    USER_CANCELLED = "user.cancelled"


class ConfigurationKind(StrEnum):
    WORKER = "worker"
    PROVIDER_CONNECTION = "provider_connection"
    MODEL_PROFILE = "model_profile"
    ROUTE_POLICY = "route_policy"
    RETRY_POLICY = "retry_policy"
    PERMISSION_POLICY = "permission_policy"
    BRANCH_POLICY = "branch_policy"
    PROJECT_SETTINGS = "project_settings"


TERMINAL_RUN_STATUSES = frozenset(
    {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.BLOCKED, RunStatus.CANCELLED}
)
