# Jarvis V1 Normalized Event Schema

Status: normative V1 contract
Transport: persisted PostgreSQL rows, JSON API, and SSE

## 1. Contract goals

The event contract decouples LangGraph, adapters, and infrastructure from the UI. It is append-only, replayable, ordered, versioned, human-readable, machine-filterable, distributed-source aware, and redacted before persistence. Events describe observable facts and declared summaries; they never contain hidden chain-of-thought.

Delivery is at least once. Consumers MUST deduplicate. `LISTEN/NOTIFY` may wake stream servers but is never a delivery guarantee.

## 2. Canonical envelope

```json
{
  "schema_version": "1.0",
  "event_id": "01992f3e-7e4d-7e8a-a32d-4f82a1e1cb29",
  "global_position": 1842,
  "run_sequence": 37,
  "occurred_at": "2026-09-07T14:34:10.123Z",
  "recorded_at": "2026-09-07T14:34:10.141Z",
  "category": "command",
  "type": "command.started",
  "severity": "info",
  "message": "Developer started the task verification suite",
  "mode": "real",
  "visibility": "owner",
  "scope": {
    "project_id": "01992f3d-...",
    "thread_id": "01992f3d-...",
    "job_id": "01992f3d-...",
    "run_id": "01992f3d-...",
    "task_id": "01992f3e-...",
    "task_attempt_id": "01992f3e-...",
    "workflow_node_id": "verify",
    "node_execution_id": "01992f3e-..."
  },
  "source": {
    "kind": "worker_adapter",
    "name": "openhands_ssh",
    "instance_id": "orch-01",
    "host_id": "jarvis-worker-01",
    "source_sequence": 901
  },
  "correlation_id": "01992f3d-...",
  "causation_event_id": "01992f3e-...",
  "idempotency_key": "run/node/effect/verify-1",
  "trace": {
    "trace_id": "4f8c...",
    "span_id": "59a1..."
  },
  "data": {
    "command_execution_id": "01992f3e-...",
    "command_kind": "verification",
    "cwd": ".",
    "display_command": "python -m pytest",
    "timeout_seconds": 1200
  },
  "artifact_refs": []
}
```

### 2.1 Required fields

`schema_version`, `event_id`, `global_position`, `occurred_at`, `recorded_at`, `category`, `type`, `severity`, `message`, `mode`, `visibility`, `source`, `correlation_id`, `data`, and `artifact_refs` are required. `scope.run_id` and `run_sequence` are required for run events; system/auth/config events may omit them.

### 2.2 Field semantics

- `event_id`: immutable UUIDv7 identity used for deduplication.
- `global_position`: database-assigned commit-safe replay cursor. Event transactions serialize allocation through a locked singleton counter (and may allocate a contiguous batch), preventing a lower cursor from committing after a higher one. Authorization filters can still make client-visible gaps.
- `run_sequence`: gap-free committed sequence within a run, allocated under row lock. It defines run timeline order.
- `occurred_at`: best producer observation time; may arrive out of order.
- `recorded_at`: database commit-time value and canonical display fallback.
- `category`: stable broad filter.
- `type`: stable lower-case dotted name. Past meanings never change.
- `severity`: `debug`, `info`, `success`, `warning`, `error`, `critical`.
- `message`: concise server-generated summary derived from typed redacted fields. It is not trusted HTML.
- `mode`: `real` or `demo`.
- `visibility`: `owner`, `operator`, or `internal`; V1 returns owner-visible records only to the owner and never streams internal-only payloads.
- `scope`: nullable resource IDs. IDs must refer to the same run/job/project hierarchy.
- `source`: producer kind/name plus configured host and stable producer sequence where available.
- `correlation_id`: operation/root request or run correlation.
- `causation_event_id`: immediate prior fact that caused this fact, when known.
- `idempotency_key`: stable identity for repeatable effects/commands, when applicable.
- `trace`: operational trace correlation, not reasoning.
- `data`: event-type-specific object validated against the schema version.
- `artifact_refs`: typed IDs for large/full content omitted from `data`.

Unknown envelope fields are rejected for major version 1. Event-type `data` schemas may add optional fields in a minor version; required/removal/semantic changes require a new major version and an upcaster for readers.

## 3. Categories and required V1 event types

| Category | Event types |
|---|---|
| `auth` | `auth.login_succeeded`, `auth.login_failed`, `auth.logout`, `auth.session_revoked` |
| `config` | `config.created`, `config.revised`, `config.validated`, `workflow.published` |
| `thread` | `thread.created`, `message.created`, `instruction.queued`, `instruction.applied` |
| `job` | `job.created`, `job.status_changed`, `job.completed`, `job.failed`, `job.blocked`, `job.cancelled` |
| `run` | `run.queued`, `run.claimed`, `run.started`, `run.command_requested`, `run.command_applied`, `run.command_rejected`, `run.pause_requested`, `run.paused`, `run.resumed`, `run.cancel_requested`, `run.cancelled`, `run.recovering`, `run.recovered`, `run.completed`, `run.failed`, `run.blocked` |
| `graph` | `graph.compiled`, `graph.compile_failed`, `graph.checkpointed`, `graph.route_selected`, `graph.fanout_started`, `graph.join_completed` |
| `node` | `node.queued`, `node.started`, `node.waiting`, `node.interrupted`, `node.succeeded`, `node.failed`, `node.skipped`, `node.cancelled` |
| `task` | `task.created`, `task.dependencies_set`, `task.ready`, `task.delegated`, `task.attempt_started`, `task.verifying`, `task.reviewing`, `task.retry_scheduled`, `task.succeeded`, `task.failed`, `task.blocked`, `task.cancelled` |
| `worker` | `worker.lease_acquired`, `worker.invocation_dispatched`, `worker.heartbeat`, `worker.invocation_completed`, `worker.invocation_failed`, `worker.cancel_requested`, `worker.cancelled`, `worker.lease_lost`, `worker.health_changed` |
| `model` | `model.route_selected`, `model.call_started`, `model.stream_progress`, `model.call_completed`, `model.call_failed`, `model.failover`, `model.usage_recorded`, `model.health_changed` |
| `tool` | `tool.started`, `tool.completed`, `tool.failed` |
| `file` | `file.read`, `file.write_started`, `file.write_completed`, `file.created`, `file.deleted`, `file.snapshot_created` |
| `command` | `command.started`, `command.output_summary`, `command.completed`, `command.failed`, `command.timed_out` |
| `test` | `test.started`, `test.completed`, `test.failed` |
| `review` | `review.started`, `review.completed`, `review.failed`, `review.snapshot_invalidated` |
| `git` | `git.branch_created`, `git.commit_created`, `git.integration_started`, `git.integration_conflict`, `git.integration_completed`, `git.push_started`, `git.push_completed`, `git.pr_created`, `git.ci_updated` |
| `approval` | `approval.requested`, `approval.decided`, `approval.expired`, `approval.cancelled`, `approval.resume_queued`, `approval.resumed` |
| `artifact` | `artifact.created`, `artifact.verified`, `artifact.unavailable` |
| `failure` | `failure.classified`, `retry.budget_consumed`, `retry.budget_exhausted` |
| `system` | `system.health_changed`, `service.health_changed`, `orchestrator.heartbeat`, `lease.expired`, `security.redaction_applied` |

New types require a schema, fixture, redaction test, human summary formatter, and UI unknown-type fallback before use.

## 4. Important payload schemas

The examples below show required core fields; every payload may also include documented optional measurements.

### `node.started`

```json
{
  "node_execution_id": "uuid",
  "workflow_node_id": "developer",
  "node_type": "worker",
  "execution_number": 2,
  "input_summary": "Implement DEV-002",
  "effective_policy_refs": ["retry:development@3", "permission:default@2"]
}
```

### `task.retry_scheduled`

```json
{
  "task_id": "uuid",
  "failed_attempt_id": "uuid",
  "failure_class": "code.test_failure",
  "retry_number": 1,
  "max_retries": 3,
  "delay_ms": 1000,
  "next_node_id": "developer",
  "feedback_artifact_id": "uuid"
}
```

### `failure.classified`

```json
{
  "failure_id": "uuid",
  "class": "infrastructure.worker_transport",
  "code": "ssh_connection_lost",
  "retryable": true,
  "budget_scope": "infrastructure.worker_transport",
  "consumes_semantic_attempt": false,
  "summary": "Worker connection was lost before a result was confirmed",
  "detail_artifact_id": "uuid"
}
```

### `approval.requested`

```json
{
  "approval_id": "uuid",
  "interrupt_key": "publish-pr:DEV-004",
  "action_type": "github.push_and_pr",
  "action_summary": "Push branch and open a pull request",
  "reason": "Publish the verified project result",
  "risk": "Creates externally visible repository state",
  "parameters": {"repository": "ClearPointSolutions/example", "branch": "jarvis/run-123"},
  "expires_at": null
}
```

### `command.completed`

```json
{
  "command_execution_id": "uuid",
  "command_kind": "verification",
  "cwd": ".",
  "display_command": "python -m pytest",
  "exit_code": 0,
  "duration_ms": 4210,
  "stdout_artifact_id": "uuid",
  "stderr_artifact_id": null,
  "output_summary": "19 tests passed"
}
```

### `model.call_completed`

```json
{
  "model_call_id": "uuid",
  "provider_kind": "openai",
  "profile_key": "reviewer-primary",
  "model": "configured-model-name",
  "latency_ms": 2100,
  "usage": {"prompt_tokens": 1200, "completion_tokens": 180, "source": "provider"},
  "cost": {"amount": "0.000000", "currency": "USD", "status": "known"},
  "finish_reason": "stop"
}
```

Model prompt/response text is intentionally absent. Approved final message content uses `message.created`; diagnostic bodies use redacted artifacts.

## 5. Lifecycle pairing and state transitions

Operations lasting more than one transaction emit `*.started` followed by exactly one terminal `*.completed`, `*.failed`, `*.cancelled`, or `*.timed_out` event for the same execution ID. Reconciliation may synthesize a terminal event only after confirming durable effect state, and marks `data.reconciled=true`.

Projection state machines reject illegal transitions. A duplicate producer notification with the same source identity or idempotency key returns the original event and does not allocate another run sequence. Corrections append `*.corrected` only for approved event types and reference the incorrect event; historical rows remain unchanged.

## 6. Ordering, clocks, and replay

- `run_sequence` is the authoritative total order for one run.
- `global_position` is the authoritative database/SSE cursor across authorized events. It is not a PostgreSQL identity/sequence, because sequence values alone do not impose concurrent transaction commit order.
- `occurred_at` represents observation and may precede an already-recorded event; UI timelines order by run sequence and display occurred time as metadata.
- Parallel child events are serialized at persistence. Causation and node execution IDs preserve the concurrency relationship.
- Source-local sequence detects missing/duplicate adapter emissions but does not override database ordering.

SSE frame:

```text
id: 1842
event: jarvis.event
data: {canonical single-line JSON envelope}

```

The endpoint honors `Last-Event-ID` or an initial `after` cursor, emits keepalive comments, and queries rows after every wakeup. Browser `EventSource` is designed to reconnect and carries a last-event identifier in the standard event stream model: [HTML Standard, server-sent events](https://html.spec.whatwg.org/multipage/server-sent-events.html).

## 7. Redaction and size rules

Redaction occurs before database insertion, message formatting, tracing, and `NOTIFY`. It covers known secret values loaded in memory, authorization/cookie headers, credentialed URLs, private-key blocks, common key/token/password fields, `.env` assignments, connection strings, and configurable patterns. Values become typed placeholders such as `[REDACTED:token]`; events may include only count/rule IDs, never the removed value or a reversible hash.

Producer payload limits are enforced before persistence:

- envelope plus `data`: target maximum 64 KiB;
- human `message`: target maximum 1 KiB;
- command/output snippets: bounded and redacted;
- larger stdout, stderr, patches, source snapshots, exception traces, and reports: artifact references.

Binary data never appears inline. Paths are normalized and classified; server-local secret paths are reduced to approved labels.

## 8. Event production transaction

1. Validate the producer and event-type schema.
2. Resolve scope and authorization metadata.
3. Apply recursive redaction and content-size extraction.
4. Lock the singleton global event counter first, then per-run counters in sorted run-ID order, then aggregate/projection rows in stable order; allocate positions/range while holding the locks through commit. Calling the writer after taking aggregate locks is forbidden.
5. Set database wall-clock `recorded_at`, insert the event batch, and apply any application-owned projection transition in the same transaction.
6. On commit, publish `NOTIFY` with the highest new global position.
7. Stream servers query by cursor; they do not trust notification payload content.

Adapter output that arrives after its lease/fence expires is stored as a non-authoritative diagnostic event or artifact and cannot advance runtime state.

## 9. Schema governance and testing

- JSON Schema files are version-controlled during implementation and generate/validate Pydantic and TypeScript types.
- Golden fixtures cover every event type, legacy normalization, redaction, maximum size, unknown fields, and forward-compatible optional fields.
- Contract tests prove append-only database privileges/triggers and deterministic formatting.
- UI tests prove unknown event types render a safe generic row and do not crash the stream.
- An upcaster reads older supported major versions into the current in-memory view; stored events are never rewritten during upgrades.
