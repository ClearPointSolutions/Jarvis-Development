# Jarvis V1 Data Model

Status: normative logical model; physical details may be refined by migrations without changing the invariants below.

M4 physical refinement (migration `0005`): workflow templates add owner identity
and a current draft pointer. Workflow versions add an immutable resolved public
registry snapshot and snapshot hash. `control.workflow_revision_references`
retains foreign keys to every resolved M3 revision. Database triggers reject
cross-template/lifecycle pointer injection, identity changes, and published
spec/layout/snapshot/binding mutation. Pre-M4 ownerless rows remain historical
and are not exposed as new executable Studio templates. Migrations `0001`–`0004`
are unchanged. See [`M4_CONTRACT.md`](M4_CONTRACT.md).

## 1. Conventions

- PostgreSQL 16+ is the canonical durable store.
- Application identifiers are UUIDv7 generated server-side. Human-readable keys such as `DEV-001` are scoped labels, never primary keys.
- All timestamps are `timestamptz` in UTC. Mutable rows have `created_at`, `updated_at`, and integer `version` for optimistic concurrency.
- Enumerations are database check constraints or lookup tables where values are expected to evolve. API enums remain versioned.
- JSONB is used for validated versioned specifications/snapshots and provider-specific metadata, not as a substitute for core relationships.
- Secret values never appear in these tables. A `secret_ref` is an opaque server-side locator such as `file:github.env#TOKEN`; API responses return only a masked label and configured/unconfigured state.
- Content bodies larger than the configured event/state limit are stored through the artifact store; records contain URI/key, digest, size, media type, and redaction classification.
- Foreign keys use `RESTRICT` for historical/configuration references and soft retirement (`archived_at`/`enabled=false`). Execution/audit history is not cascade-deleted.

## 2. Status vocabularies

### 2.1 Job and run

- Job: `draft`, `queued`, `active`, `waiting`, `completed`, `failed`, `blocked`, `cancelled`.
- Run: `queued`, `claiming`, `running`, `pause_requested`, `paused`, `approval_required`, `cancel_requested`, `completed`, `failed`, `blocked`, `cancelled`.
- `desired_state`: `running`, `paused`, or `cancelled`. It expresses durable intent; `status` expresses acknowledged observation.

Terminal run states are `completed`, `failed`, `blocked`, and `cancelled`. They cannot transition back. Whole-run retry creates another run.

### 2.2 Tasks, attempts, and nodes

- Task: `pending`, `ready`, `running`, `waiting`, `approval_required`, `succeeded`, `failed`, `blocked`, `cancelled`, `skipped`.
- Attempt: `queued`, `running`, `verifying`, `reviewing`, `succeeded`, `failed`, `cancelled`, `unknown`.
- Node execution: `queued`, `running`, `waiting`, `interrupted`, `succeeded`, `failed`, `cancelled`, `skipped`.

### 2.3 Commands, approvals, effects, and leases

- Command: `pending`, `applying`, `applied`, `rejected`, `superseded`.
- Approval: `pending`, `decided`, `expired`, `cancelled`; decisions are `approved`, `rejected`.
- Effect/invocation: `prepared`, `dispatched`, `running`, `succeeded`, `failed`, `cancel_requested`, `cancelled`, `unknown`.
- Lease: active if `released_at IS NULL AND expires_at > now()`; expiry is not success/failure by itself.

## 3. Identity and conversation

### `users`

`id`, unique normalized `username`, `password_hash`, `role`, `enabled`, `last_login_at`, timestamps.

V1 accepts role `owner`; schema can later add viewers/operators without weakening object authorization.

### `sessions`

`id`, `user_id`, unique `token_hash`, `csrf_secret_hash`, `created_at`, `last_seen_at`, `expires_at`, `revoked_at`, `ip_prefix`, `user_agent_hash`.

Only a hash of the opaque session token is stored. Session lookup and revocation are server-side.

### `conversation_threads`

`id`, `owner_user_id`, `title`, `status`, `next_message_sequence`, timestamps, `archived_at`.

### `messages`

`id`, `thread_id`, unique (`thread_id`, `sequence`), `role` (`user`, `organizer`, `system`, `tool`), `content_text`, optional `artifact_id`, optional `run_id`, `visibility`, `created_at`.

No hidden reasoning field exists. A user message that becomes a runtime instruction also links to a `run_command`.

## 4. Projects and repositories

### `projects`

`id`, `owner_user_id`, unique `slug`, `name`, `description`, `default_workflow_version_id`, `default_branch_policy_id`, `status`, timestamps, `archived_at`.

### `project_repositories`

`id`, `project_id`, `provider_kind`, `remote_owner`, `remote_name`, `remote_url`, `default_branch`, `integration_branch`, `workspace_key`, `github_connection_id`, timestamps.

Constraint: repository URL and workspace key pass adapter validation; no credential may be embedded in a URL.

### `repository_snapshots`

`id`, `project_repository_id`, `run_id`, optional `task_attempt_id`, `head_sha`, `base_sha`, `tree_digest`, `status_digest`, `source_artifact_id`, `diff_artifact_id`, `created_at`.

Reviewer and integration records reference a snapshot. A snapshot is immutable; if HEAD changes, a new snapshot is required.

### `branch_policies`

`id`, `name`, `revision`, `spec_version`, `spec_json`, `enabled`, `created_at` with unique (`id`, `revision`) represented physically by an identity plus revision table if preferred.

Policy covers branch naming, integration strategy, required commands/tests/CI, protected operations, and allowed remotes.

## 5. Versioned configuration

Configuration identities have a mutable display row and immutable revision rows. Editing creates a revision; runs resolve exact revisions into a snapshot.

### `workers`

`id`, unique `key`, `display_name`, `description`, `enabled`, `current_revision_id`, timestamps, `archived_at`.

### `worker_revisions`

`id`, `worker_id`, `revision`, `adapter_kind`, `config_schema_version`, `config_json`, `capabilities_json`, `max_concurrency`, `created_by`, `created_at`, unique (`worker_id`, `revision`).

For Worker-01, `config_json` includes configured host alias/address, SSH user, key `secret_ref`, workspace/runner/invocation roots, timeouts, and host-key policy. Responses redact the secret reference details as configured.

### `provider_connections`

`id`, unique `key`, `kind` (`openai`, `ollama`), `display_name`, `base_url`, `secret_ref`, `enabled`, `egress_policy_id`, health state/timestamps, mutable `version`.

Connection changes do not rewrite historical snapshots. Secrets are dereferenced only in the orchestrator.

### `model_profiles`

`id`, unique `key`, `provider_connection_id`, `revision`, `model_name`, `capabilities_json`, `parameters_json`, context/output limits, `pricing_json`, `enabled`, timestamps, unique (`key`, `revision`). Pricing records currency, units, source/effective date, or `unknown`.

### `route_policies`

`id`, unique `key`, `revision`, `required_capabilities_json`, ordered `candidate_profile_ids`, health/circuit/failover rules, residency/remote-use constraint, `enabled`, timestamps.

### `retry_policies`

`id`, unique `key`, `revision`, `scope`, `rules_json`, `enabled`, timestamps. Each rule maps failure class to `max_retries`, backoff, jitter, optional alternate route/worker, and exhausted action (`fail`, `block`, `approval`).

### `permission_policies`

`id`, unique `key`, `revision`, `rules_json`, `enabled`, timestamps. Rules map typed actions and context to `allow`, `deny`, or `require_approval`; default is deny for unknown/destructive actions.

### `workflow_templates`

`id`, unique `key`, `name`, `description`, `current_draft_version_id`, `latest_published_version_id`, timestamps, `archived_at`.

### `workflow_versions`

`id`, `workflow_template_id`, monotonically increasing `version`, `lifecycle` (`draft`, `published`, `retired`), `spec_version`, validated `spec_json`, separate `layout_json`, `content_hash`, `created_by`, `created_at`, `published_at`, unique (`workflow_template_id`, `version`).

Published rows are immutable. Only a published version may start a real run.

## 6. Jobs, runs, and resolved configuration

### `jobs`

`id`, `project_id`, optional `conversation_thread_id`, `objective`, `title`, `priority`, `status`, optional `parent_job_id`, `created_by`, timestamps, `completed_at`, `result_summary`, `row_version`.

### `runs`

`id`, `job_id`, `run_number`, optional `retry_of_run_id`, `workflow_version_id`, `config_snapshot_id`, unique `langgraph_thread_id`, `mode` (`real`, `demo`), `status`, `desired_state`, `priority`, `claimable_at`, `next_command_sequence`, `lease_generation`, `last_checkpoint_id`, `last_event_at`, `started_at`, `finished_at`, `result_summary`, `row_version`, unique (`job_id`, `run_number`).

### `run_config_snapshots`

`id`, unique `content_hash`, `schema_version`, `workflow_version_id`, `resolved_json`, `created_at`.

The snapshot contains exact worker/model/policy revision IDs, non-secret effective settings, secret reference identifiers (never values), repository binding/base SHA policy, compiler version, and feature flags. It is immutable and sufficient to recompile the same execution semantics.

### `run_leases`

`run_id` primary key, `owner_instance_id`, `generation`, `acquired_at`, `heartbeat_at`, `expires_at`, `released_at`, `release_reason`.

Only the current generation may append authoritative execution transitions or commit effects for the run.

### `orchestrator_instances`

`id`, `started_at`, `last_heartbeat_at`, `version`, `hostname`, `status`, `draining_at`.

## 7. Tasks and runtime executions

### `tasks`

`id`, `run_id`, optional `parent_task_id`, unique (`run_id`, `task_key`), `task_key`, `title`, `description`, `acceptance_criteria_json`, `verification_spec_json`, `weight`, `status`, `assigned_worker_id`, `current_attempt_number`, `created_by_node_id`, timestamps, `row_version`.

### `task_dependencies`

`task_id`, `depends_on_task_id`, `kind` (`success`, `completion`), primary key (`task_id`, `depends_on_task_id`), check tasks differ and share a run. Cycle validation occurs before insertion/dispatch.

### `task_attempts`

`id`, `task_id`, `attempt_number`, `run_id`, `node_execution_id`, `worker_revision_id`, `worker_invocation_id`, `base_snapshot_id`, `result_snapshot_id`, `status`, `failure_id`, `started_at`, `finished_at`, unique (`task_id`, `attempt_number`).

### `node_executions`

`id`, `run_id`, `workflow_node_id`, `execution_number`, optional `task_id`, optional `task_attempt_id`, optional `parent_node_execution_id`, `status`, `input_summary`, `output_summary`, `checkpoint_before`, `checkpoint_after`, `started_at`, `finished_at`, unique (`run_id`, `workflow_node_id`, `execution_number`).

### `retry_counters`

`id`, `run_id`, optional `task_id`, `node_execution_id`, `failure_class`, `used_retries`, `max_retries_snapshot`, `updated_at`, unique (`run_id`, `task_id`, `node_execution_id`, `failure_class`) with normalized null handling through explicit scope columns/indexes.

Only the classified failure's counter increments. The originating event records before/after values and policy revision.

### `failures`

`id`, `run_id`, optional task/attempt/node/effect/provider references, `failure_class`, `failure_code`, `retryable`, `summary`, `detail_artifact_id`, `origin`, `occurred_at`, `resolved_at`.

Failure details are redacted. Classification is immutable; reclassification creates an audit/correction record rather than rewriting historical events.

## 8. Commands and approvals

### `run_commands`

`id`, `run_id`, unique (`run_id`, `sequence`), `command_type` (`pause`, `resume`, `cancel`, `instruction`, `retry`), `payload_json`, `requested_by`, `idempotency_key`, `expected_run_version`, `status`, `reason`, timestamps, unique (`requested_by`, `idempotency_key`).

`retry` against a terminal run results in a new linked run; it never resumes the terminal row.

### `approvals`

`id`, `run_id`, `node_execution_id`, `interrupt_key`, `action_type`, `action_summary`, `reason`, `risk`, redacted `parameters_json`, `policy_snapshot_json`, `status`, `expires_at`, timestamps, unique (`run_id`, `interrupt_key`).

### `approval_decisions`

`id`, `approval_id`, `decision`, `comment`, `decided_by`, `session_id`, `idempotency_key`, `created_at`, unique (`approval_id`) and unique (`decided_by`, `idempotency_key`).

Decisions are append-only. The approval status is a projection updated transactionally with the first accepted decision.

## 9. Effects, workers, commands, tests, and Git

### `effects`

`id`, `run_id`, `node_execution_id`, `effect_kind`, `idempotency_key`, `request_digest`, redacted `request_json`, `status`, `fencing_generation`, `external_id`, `result_digest`, `result_artifact_id`, `started_at`, `finished_at`, `last_reconciled_at`, unique (`adapter_scope`, `idempotency_key`).

### `worker_slots`

`id`, `worker_id`, `slot_number`, unique (`worker_id`, `slot_number`). Changing capacity creates/retires slots only when unleased.

### `worker_leases`

`id`, `worker_slot_id`, `run_id`, `task_attempt_id`, `worker_invocation_id`, `token_hash`, `generation`, `acquired_at`, `heartbeat_at`, `expires_at`, `released_at`. A partial unique index permits only one unreleased lease per slot.

### `worker_invocations`

`id`, `effect_id`, `worker_revision_id`, `remote_invocation_id`, `workspace_root`, `branch_name`, `base_sha`, `status`, `remote_process_ref`, `started_at`, `last_heartbeat_at`, `finished_at`, `exit_code`, `result_artifact_id`, `fencing_generation`, unique (`worker_revision_id`, `remote_invocation_id`).

### `command_executions`

`id`, `run_id`, `task_attempt_id`, `worker_invocation_id`, `command_kind`, redacted `display_command`, `argv_digest`, `cwd`, `status`, `started_at`, `finished_at`, `exit_code`, stdout/stderr artifact IDs, `summary`.

The original unredacted environment is never stored. Commands originate from validated workflow/task specs or adapter internals, not browser input.

### `test_executions`

`id`, `command_execution_id`, `framework`, `status`, counts (`total`, `passed`, `failed`, `skipped`, `errored`), `duration_ms`, `report_artifact_id`, `summary`.

### `file_changes`

`id`, `repository_snapshot_id`, `path`, `change_type`, additions/deletions, before/after blob digest, optional patch artifact, `task_attempt_id`.

Paths are normalized, relative to the repository root, and cannot escape it.

### `git_operations`

`id`, `run_id`, `task_attempt_id`, `repository_id`, `operation`, `base_sha`, `head_sha`, `branch`, `status`, `failure_id`, `started_at`, `finished_at`, `metadata_json`.

### `github_publications`

`id`, `run_id`, `repository_id`, `effect_id`, `commit_sha`, `branch`, optional PR number/URL, `status`, CI state/conclusion, last sync time, redacted metadata. Push/PR/merge operations link to the approval that authorized them when policy requires it.

## 10. Provider calls and health

### `model_calls`

`id`, `run_id`, `node_execution_id`, optional `task_attempt_id`, `profile_id`, `provider_connection_id`, `route_policy_id`, `attempt_number`, `request_digest`, `status`, provider request ID, latency fields, prompt/completion/total token values, `usage_source` (`provider`, `tokenizer_estimate`, `unknown`), `cost_amount`, `cost_currency`, `pricing_snapshot_json`, `failure_id`, timestamps.

Prompts/responses are not stored here. Approved redacted content belongs in message/artifact records.

### `health_samples`

`id`, `source_kind`, `source_id`, `host_id`, `observed_at`, `status`, `metrics_json`, `failure_code`. Partition by time when volume warrants it and apply documented retention. Health events reference aggregates rather than emitting every raw metric sample.

### `circuit_states`

`provider_connection_id` or worker scope, `state` (`closed`, `open`, `half_open`), failure count/window, `opened_at`, `next_probe_at`, `version`.

## 11. Artifacts and events

### `artifacts`

`id`, `run_id`, optional task/attempt/node references, `kind`, `name`, `media_type`, `storage_backend`, `storage_key`, `sha256`, `size_bytes`, `classification`, `redaction_status`, `created_at`, unique (`storage_backend`, `storage_key`), and an optional dedupe index on digest within a security scope.

Local V1 storage uses a directory beneath `/opt/jarvis-v1/data/artifacts` mounted only into API/orchestrator as required. Downloads use authorization and safe content disposition.

### `run_event_counters`

`run_id` primary key, `next_sequence`. Allocation is locked in the event transaction.

### `event_global_counter`

Singleton row with `next_position`. Every event-writing transaction locks this row and allocates one position or a contiguous range before insert. The lock is held through commit, so another transaction cannot commit a higher cursor before the lower range is committed. This deliberate global serialization makes an SSE high-water cursor safe; V1 event volume is low enough for the tradeoff, and batching amortizes the lock.

All event-producing mutation paths use one lock order: global event counter first, then per-run counters in sorted run-ID order, then aggregate/projection rows in stable table/key order. Code that already holds an aggregate lock cannot call the event writer. This avoids a global-counter/run-row deadlock while preserving atomic state-plus-event commits.

### `events`

`global_position bigint`, unique `event_id`, `schema_version`, optional `run_id`, `run_sequence`, job/project/thread/task/attempt/node references, `occurred_at`, `recorded_at`, `category`, `type`, `severity`, source/correlation/causation/idempotency fields, human `message`, validated redacted `data_json`, optional `artifact_id`, `visibility`, `mode`, `integrity_hash`.

Constraints:

- primary key (`global_position`), allocated by the locked global counter rather than a PostgreSQL sequence; unique (`run_id`, `run_sequence`) when run-scoped;
- unique producer identity (`source_instance_id`, `source_sequence`) when supplied;
- `recorded_at` uses database wall-clock time after cursor allocation; ordering relies on position, not clocks;
- database grants and a protective trigger prohibit application `UPDATE`/`DELETE`;
- inserts require the event-writer function/role so redaction/schema checks cannot be bypassed.

See `EVENT_SCHEMA.md` for the envelope and ordering contract.

## 12. Projection and integrity indexes

Minimum indexes include:

- runnable runs on (`status`, `claimable_at`, `priority DESC`, `created_at`);
- pending commands on (`run_id`, `status`, `sequence`);
- event replay on (`run_id`, `run_sequence`) and (`global_position`), plus category/type and time indexes for filters;
- tasks on (`run_id`, `status`) and dependencies by both task columns;
- active lease expiry indexes;
- approvals on (`status`, `created_at`);
- artifacts/model calls/failures by run and task;
- GIN indexes only on demonstrated JSONB query paths.

Projection updates carry `last_event_position`. A repair job can compare it with the event/checkpoint watermark and rebuild affected read models without changing historical events.

## 13. LangGraph checkpoint ownership

Checkpoint tables are created/migrated only through the selected compatible `langgraph-checkpoint-postgres` version. Application migrations do not reinterpret or duplicate checkpoint payloads. `runs.langgraph_thread_id` links domain execution to the checkpoint namespace; `last_checkpoint_id` is a convenience pointer, not an independent workflow state.

Database restore must restore control, event, and checkpoint schemas to one consistent point. Artifact manifests are included in backup verification.
