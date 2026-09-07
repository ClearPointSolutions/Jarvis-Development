# Jarvis V1 Worker Protocol

Status: normative adapter contract and initial OpenHands SSH mapping

## 1. Goals

The protocol isolates LangGraph from a worker implementation. It supports capability selection, bounded concurrency, durable invocation identity, lifecycle events, cancellation, heartbeats, authoritative repository roots, redacted artifacts, and recovery. OpenHands on Jarvis-Worker-01 is the first adapter; future Codex workers implement the same contract.

The protocol is a Python service interface in V1, with an SSH transport implementation. It is not a publicly exposed worker HTTP API.

## 2. Worker definition

A versioned worker revision declares:

```json
{
  "adapter_kind": "openhands_ssh_v1",
  "display_name": "Jarvis-Worker-01",
  "capabilities": ["code", "filesystem", "shell", "git", "tests"],
  "max_concurrency": 1,
  "labels": {"os": "linux", "python": "3.12", "node": "20"},
  "model_binding": {"mode": "worker_managed", "allowed_profile_refs": ["worker01-default@1"]},
  "connection": {
    "host": "configured-host-or-address",
    "port": 22,
    "user": "jarvis",
    "ssh_key_ref": "secret:worker01-key",
    "host_key_ref": "secret:worker01-known-host",
    "workspace_root": "/opt/jarvis-worker/workspaces",
    "runner_path": "/opt/jarvis-worker/developer_task.py",
    "venv_activate": "/opt/jarvis-worker/venv/bin/activate",
    "invocation_root": "/opt/jarvis-worker/persistence/v1-invocations"
  },
  "timeouts": {"connect_seconds": 10, "run_seconds": 7200, "heartbeat_seconds": 10}
}
```

These example paths reflect the observed prototype but all are configuration. The browser sees labels/capabilities/health and masked configuration; it never receives host credentials or raw secret references.

## 3. Adapter interface

```text
validate(worker_revision) -> ValidationReport
health(worker_revision) -> WorkerHealth
prepare(request, lease) -> PreparedInvocation
start(prepared) -> InvocationHandle
inspect(handle) -> InvocationStatus
events(handle, after_source_sequence) -> async stream WorkerEvent
cancel(handle, reason) -> CancelResult
collect(handle) -> WorkerResult
reconcile(handle) -> ReconciliationResult
```

All calls accept a deadline and correlation context. `prepare`/`start` are idempotent by `invocation_id`. `collect` never infers success from SSH exit alone; it validates a signed/digested structured result associated with the invocation.

## 4. Invocation request

```json
{
  "protocol_version": "1.0",
  "invocation_id": "uuid",
  "idempotency_key": "run/task/attempt/worker",
  "run_id": "uuid",
  "task_id": "uuid",
  "task_attempt_id": "uuid",
  "lease": {"slot": 0, "generation": 8, "token": "write-only-random-token", "expires_at": "..."},
  "project": {
    "slug": "safe-slug",
    "repository_id": "uuid",
    "workspace_root": "/opt/jarvis-worker/workspaces/safe-slug",
    "branch": "jarvis/run-short/DEV-001-a1",
    "base_sha": "40-hex-sha"
  },
  "objective": "bounded objective",
  "architecture_artifact_id": "uuid",
  "task": {
    "key": "DEV-001",
    "title": "...",
    "description": "...",
    "acceptance_criteria": ["..."],
    "verification": [{"kind": "argv", "argv": ["python", "-m", "pytest"], "timeout_seconds": 1200}]
  },
  "feedback_artifact_ids": [],
  "model_binding": {"mode": "worker_managed", "profile_ref": "worker01-default@1"},
  "limits": {"max_runtime_seconds": 7200, "max_output_bytes": 104857600},
  "event_callback": null
}
```

The token is transmitted only to the trusted remote wrapper and stored hashed where possible. Model credentials used by the legacy runner remain local to Worker-01; they are not placed in the request or returned.

`model_binding.mode=worker_managed` records and validates the actual fixed model profile provided by the worker's local configuration. `control_plane` may be used by a future/revised adapter only when it can apply the selected profile through a typed secure mechanism; raw provider keys are never placed in this request. A selected per-node model that the worker cannot honor fails publication/start validation rather than becoming a cosmetic UI setting.

## 5. Worker result

```json
{
  "protocol_version": "1.0",
  "invocation_id": "uuid",
  "status": "succeeded",
  "workspace_root": "/opt/jarvis-worker/workspaces/safe-slug/worktrees/...",
  "branch": "jarvis/run-short/DEV-001-a1",
  "start_head": "sha",
  "end_head": "sha",
  "repository_snapshot": {
    "head_sha": "sha",
    "tree_digest": "sha256",
    "git_status": "clean",
    "snapshot_artifact_id": "uuid"
  },
  "summary": "Implemented and locally checked the task",
  "artifact_manifest_id": "uuid",
  "error": null,
  "started_at": "...",
  "finished_at": "...",
  "source_sequence": 82
}
```

Allowed terminal statuses are `succeeded`, `failed`, `cancelled`, and `unknown`. Result validation checks invocation ID, workspace containment, lease/fence, SHA formats, artifact digests, output limits, and status consistency.

## 6. Events and output

Worker-native events are mapped into the normalized event schema. Minimum observable events are invocation start/finish, heartbeat, file changes, command start/finish, test start/finish, commit/snapshot, cancellation, and failure. If the current legacy runner cannot stream a fine-grained event, the adapter emits only facts it can observe; it does not fake agent/tool activity.

Stdout/stderr are treated as untrusted data. The adapter:

1. captures bounded raw bytes to a server-side staging file;
2. redacts before artifact publication or snippets;
3. emits rate-limited summaries, not one event per line;
4. preserves the full redacted log as an artifact with digest;
5. parses a final structured sentinel only after limiting line size and matching the expected invocation.

## 7. Initial OpenHands SSH compatibility mapping

The observed legacy runner accepts one base64-encoded JSON argument with `project_slug`, `objective`, `architecture`, `task`, and `feedback`; it prints `JARVIS_RESULT_JSON=...`, creates/reuses `/opt/jarvis-worker/workspaces/{slug}`, invokes OpenHands, commits any changes, and returns start/end HEAD and error state.

The V1 adapter maps to it as follows:

- resolve/sanitize the project slug and verify the final remote path remains under configured workspace root;
- create an isolated task worktree/branch before invocation where compatibility permits; otherwise set worker concurrency to one and regard the legacy per-project workspace as an exclusive resource;
- build the legacy payload from immutable request/artifact content with strict size limits;
- shell-quote the base64 value as one argument and invoke the configured venv/runner over SSH;
- parse the last bounded matching sentinel; nonzero SSH exit, missing sentinel, invalid JSON, or mismatched task becomes a typed failure, never implicit success;
- independently inspect repository root, HEAD, status, diff, and artifacts after the runner returns; do not trust model text as verification;
- run deterministic verification separately through the adapter at that exact root;
- seal the repository snapshot used by Reviewer.

### 7.1 Durable compatibility wrapper

To survive orchestrator/SSH loss without starting duplicate OpenHands work, V1 SHOULD install a small, versioned, non-secret wrapper alongside—but not over—the existing worker files, under a configured V1 worker path. The wrapper atomically creates an invocation directory by ID, stores a redacted request digest/status/PID/result, launches the unchanged legacy runner once, and lets the adapter poll by invocation ID. `start` returns an existing handle if the directory already exists with the same digest and rejects a digest mismatch.

If staging is restricted to the existing synchronous command before that wrapper is installed, a lost SSH session has an ambiguous outcome. The adapter MUST reconcile remote process/workspace/result state, quarantine uncertain workspace changes, and block rather than automatically launching a duplicate. This limitation is an explicit staging gate, not a reason to misclassify the failure.

## 8. Verification protocol

Preferred commands are structured argv arrays plus timeout, expected exit codes, and an allowlisted environment overlay. Legacy architect command strings may be supported only through a controlled `bash -lc` adapter mode, with length limits, redaction, permission policy, and no browser-supplied string.

Every verification command runs with:

- `cwd` equal to the adapter-confirmed repository/worktree root;
- the configured worker virtual environment first on `PATH` where required;
- a minimal environment without orchestration/provider/GitHub secrets unless a specific test policy grants a reference;
- bounded runtime/output/process group;
- command, cwd, duration, exit code, summary, and output artifacts emitted.

Model-invented leading `cd /app`, `/workspace`, `/project`, `/repo`, or another non-root path is invalid. Normalization may remove only an explicitly recognized bad leading `cd` for legacy compatibility and MUST emit a correction event. New workflow specs should reject it at validation time.

## 9. Reviewer evidence contract

Reviewer input is created after deterministic verification and includes:

- original objective and immutable workflow/config references;
- current task and only its acceptance criteria;
- base/result commit SHAs;
- complete bounded repository file manifest and relevant current source snapshot artifact;
- clean/dirty status and submodule/LFS status where applicable;
- verification command/result/report artifacts;
- full cumulative branch diff and latest-attempt diff, clearly distinguished;
- prior feedback and failure history.

The result snapshot HEAD is checked again when review completes. A mismatch invalidates the review. Passing deterministic checks are strong evidence, but the reviewer may fail a concrete uncovered issue and must cite it. Later-task features are not current-task criteria.

## 10. Lease, heartbeat, and fencing

- The scheduler leases a numbered worker slot, not merely the worker identity.
- The lease has a random token and monotonically increasing generation. Database stores token hash.
- The orchestrator heartbeat renews both run and worker leases; remote activity heartbeat is separately observed.
- Missing activity marks `possibly_stalled`; it does not immediately prove failure.
- On expiry, reconciliation determines whether the remote operation is live, terminal, absent, or unknown before redispatch.
- Every result carries invocation ID/generation. A stale generation may be archived for diagnostics but cannot advance a task or integration ref.
- Worker capacity and timeouts are configuration, with `max_concurrency=1` for the legacy shared workspace until isolation is demonstrated.

## 11. Cancellation

Cancel is idempotent. The adapter records intent before sending a remote signal. A V1 wrapper terminates the invocation process group with a grace period and then reports confirmed or unknown termination. It must not kill unrelated worker processes. Existing commits/files are preserved for audit/quarantine; cleanup is a separate typed, policy-controlled operation.

An SSH disconnect is not proof of cancellation. A late result after cancel is retained as diagnostic evidence and rejected by the fence.

## 12. Security requirements

- Use a pinned known-hosts entry; `StrictHostKeyChecking=accept-new` is not acceptable for steady-state production.
- SSH private key is a read-only server-side secret mount accessible only to the orchestrator account.
- Remote command construction uses fixed program paths and strict quoting; configuration paths are validated absolute paths.
- Slugs, branch names, and IDs use allowlisted character sets and containment checks.
- Worker output is untrusted and redacted before persistence/logging.
- The worker receives only task-scoped data and credentials. It never receives the Mission Control database URL/session secret.
- Passwordless sudo on Worker-01 is a high-risk capability: privileged commands are denied unless a typed policy and durable approval explicitly authorize them.

## 13. Health and capability validation

Validation checks DNS/address reachability, pinned host key, authentication, runner/venv existence, writable configured roots, Git version/identity, available tools, and a harmless protocol probe. It returns facts without secrets. Health distinguishes `healthy`, `degraded`, `unavailable`, `misconfigured`, and `unknown`; absence of optional capabilities affects scheduling rather than hard-coded workflow branches.
