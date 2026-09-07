# Jarvis V1 Workflow Runtime

Status: normative compilation and execution design

## 1. Purpose

Workflow templates are validated executable data compiled into LangGraph. React Flow edits the data and layout; it does not execute edges, calculate retries, or hold authoritative state. Each run binds one immutable published workflow version and one resolved configuration snapshot.

## 2. Workflow specification V1

The canonical stored representation is JSON validated against a version-controlled JSON Schema. YAML may be accepted as an import format but is normalized to canonical JSON before hashing.

```json
{
  "spec_version": "1.0",
  "key": "software-change",
  "name": "Software change with review",
  "entrypoint": "organizer",
  "state_schema": "jarvis.workflow_state.v1",
  "defaults": {
    "retry_policy_ref": "standard@3",
    "permission_policy_ref": "owner-safe@2",
    "timeout_seconds": 1800
  },
  "nodes": [
    {
      "id": "organizer",
      "type": "organizer",
      "label": "Organizer",
      "config": {},
      "policy": {"model_route_ref": "organizer@4"}
    },
    {
      "id": "architect",
      "type": "architect",
      "label": "Architect",
      "config": {"output_schema": "task_plan.v1", "max_tasks": 100},
      "policy": {"model_route_ref": "architect@2", "retry_policy_ref": "structured-model@1"}
    },
    {
      "id": "dispatch",
      "type": "task_dispatch",
      "label": "Select ready task",
      "config": {"parallelism": 1, "ready_order": "dependency_then_task_key"},
      "policy": {}
    },
    {
      "id": "develop",
      "type": "worker",
      "label": "Developer",
      "config": {},
      "policy": {
        "worker_selector": {"requires": ["code", "shell", "git"]},
        "model_route_ref": "developer@5",
        "retry_policy_ref": "development@3",
        "verification": {"source": "task", "required": true},
        "approval": {"before": []},
        "timeout_seconds": 7200
      }
    },
    {
      "id": "verify",
      "type": "verify",
      "label": "Deterministic verification",
      "config": {"commands_source": "task.verification", "stop_on_failure": true},
      "policy": {"retry_policy_ref": "verification@1", "timeout_seconds": 1200}
    },
    {
      "id": "review",
      "type": "reviewer",
      "label": "Independent review",
      "config": {"requires_repository_snapshot": true},
      "policy": {"model_route_ref": "reviewer@4", "retry_policy_ref": "review@2"}
    },
    {
      "id": "integrate",
      "type": "integrate",
      "label": "Integrate accepted task",
      "config": {"repository_source": "project", "run_combined_gates": true},
      "policy": {"retry_policy_ref": "integration@1"}
    },
    {
      "id": "publish_approval",
      "type": "approval",
      "label": "Approve publication",
      "config": {"action_type": "github.push_and_pr", "expires_in_seconds": null},
      "policy": {}
    },
    {
      "id": "publish",
      "type": "github_publish",
      "label": "Publish pull request",
      "config": {"repository_source": "project", "wait_for_ci": true},
      "policy": {"approval": {"required_grant_from": "publish_approval"}}
    },
    {"id": "finish", "type": "finalize", "label": "Finish", "config": {}, "policy": {}}
  ],
  "edges": [
    {"id": "e1", "from": "organizer", "to": "architect", "kind": "always"},
    {"id": "e2", "from": "architect", "to": "dispatch", "kind": "always"},
    {"id": "e3", "from": "dispatch", "to": "develop", "kind": "on_result", "when": {"path": "$.tasks.dispatch_status", "op": "eq", "value": "selected"}},
    {"id": "e4", "from": "dispatch", "to": "publish_approval", "kind": "on_result", "when": {"path": "$.tasks.dispatch_status", "op": "eq", "value": "all_succeeded"}},
    {"id": "e4f", "from": "dispatch", "to": "finish", "kind": "on_result", "when": {"path": "$.tasks.dispatch_status", "op": "eq", "value": "terminal_failure"}},
    {"id": "e5", "from": "develop", "to": "verify", "kind": "on_result", "when": {"path": "$.node.result", "op": "eq", "value": "succeeded"}},
    {"id": "e6", "from": "verify", "to": "review", "kind": "on_result", "when": {"path": "$.verification.verdict", "op": "eq", "value": "pass"}},
    {"id": "e7", "from": "verify", "to": "develop", "kind": "retry", "when": {"path": "$.verification.verdict", "op": "eq", "value": "fail"}, "retry_class": "code.test_failure"},
    {"id": "e8", "from": "review", "to": "integrate", "kind": "on_result", "when": {"path": "$.review.verdict", "op": "eq", "value": "pass"}},
    {"id": "e9", "from": "review", "to": "develop", "kind": "retry", "when": {"path": "$.review.verdict", "op": "eq", "value": "fail"}, "retry_class": "code.review_failure"},
    {"id": "e10", "from": "integrate", "to": "dispatch", "kind": "iterate", "iteration_key": "planned_tasks", "progress_path": "$.tasks.terminal_count", "max_iterations": 100},
    {"id": "e11", "from": "publish_approval", "to": "publish", "kind": "on_result", "when": {"path": "$.approval.decision", "op": "eq", "value": "approved"}},
    {"id": "e12", "from": "publish_approval", "to": "finish", "kind": "on_result", "when": {"path": "$.approval.decision", "op": "eq", "value": "rejected"}},
    {"id": "e13", "from": "publish", "to": "finish", "kind": "always"}
  ],
  "outputs": {"result_path": "$.final"}
}
```

Visual positions, viewport, grouping, and colors are stored in `layout_json` keyed by node/edge ID. Layout is excluded from the executable content hash.

Every node accepts the same typed `policy` envelope: optional `worker_selector`, `model_route_ref`, `retry_policy_ref`, `permission_policy_ref`, `verification`, `approval`, `timeout_seconds`, and resource/concurrency limits. Defaults resolve first and a node may tighten/override only allowed fields. Publication validates applicability: for example, a worker selector on a pure router is invalid, while a worker node must resolve a worker and an actual model binding. `config` contains node-type semantics; execution policy is not hidden inside it.

Worker model binding is capability based. A worker revision declares either `control_plane` binding (the adapter can apply an allowed selected profile without receiving a raw credential) or `worker_managed` binding (the worker has a fixed, declared profile). The existing OpenHands runner is initially `worker_managed` because it reads model configuration from Worker-01's local environment. Selecting a different developer model is rejected unless a worker revision/wrapper genuinely supports that binding; the GUI cannot pretend a model change took effect.

The task dispatcher returns `selected`, `all_succeeded`, or `terminal_failure`; it never equates “all terminal” with success. `finalize` derives `failed`, `blocked`, or `cancelled` from the terminal task/failure/control records. A publication edge is reachable only from `all_succeeded`.

## 3. Node registry

The runtime has a code-reviewed registry of supported node types. Configuration selects types and behavior; it cannot name/import arbitrary Python.

| Type | Runtime behavior |
|---|---|
| `organizer` | Produces/consumes user-facing messages and dispatch summaries; may accept durable instructions at safe points |
| `architect` | Produces a schema-valid dependency-ordered task plan |
| `task_dispatch` | Selects ready task IDs and optionally issues bounded parallel LangGraph sends |
| `worker` | Leases a matching worker and drives a typed worker invocation |
| `verify` | Executes configured/task verification commands at the authoritative repository root |
| `reviewer` | Reviews acceptance criteria against a sealed current repository snapshot and verification evidence |
| `integrate` | Serializes accepted branch integration, validates current base/HEAD, and runs combined gates |
| `router` | Evaluates a safe declarative predicate and selects one edge |
| `fanout` | Emits bounded child work for a declared list/path |
| `join` | Waits for the declared child execution set and reduces results deterministically |
| `approval` | Creates/reuses an approval and invokes LangGraph interrupt |
| `github_publish` | Performs an approved, idempotent GitHub publication effect |
| `finalize` | Computes final status/result from task and policy state |

Tool activity such as Shell or Filesystem is normally a child execution/event of a worker node, not a decorative workflow node. A later tool node type requires a typed adapter and permission schema before it can be published.

## 4. State contract

`jarvis.workflow_state.v1` contains small, JSON-serializable orchestration facts only:

- IDs: project/job/run, workflow/config snapshot, current task/attempt/node, correlation.
- objective and bounded human/agent summaries.
- task IDs and dependency/status summaries, not full source or logs.
- node result envelopes and typed route outcome.
- per-failure-class retry counters and exhausted decisions.
- pending approval ID/interrupt key and last durable command sequence.
- selected worker/model revision IDs and effect/invocation IDs.
- artifact/snapshot references.
- desired/observed run state and final result summary.

Reducers are explicit. Maps merge by stable ID with version comparison; event/artifact reference lists deduplicate by ID; parallel child results merge by child execution ID; scalars that could be concurrently written are forbidden. Large messages, source trees, patches, stdout/stderr, and model payloads remain artifacts.

## 5. Publication validation

Publishing is one server transaction after all checks pass:

1. JSON Schema and size/count limits.
2. Unique stable node/edge IDs and exactly one entrypoint.
3. All edges reference existing nodes; every nonterminal node has a reachable exit; at least one terminal path exists; unreachable nodes are rejected.
4. Generic cycles are rejected. A cycle is permitted only through (a) an edge of kind `retry` with a named failure class and finite effective retry budget, or (b) an edge of kind `iterate` emitted by an approved iterator node with a declared monotonic progress path and hard `max_iterations`. Task iteration additionally requires the Architect's `max_tasks` not exceed that bound.
5. Conditional outgoing edges are deterministic: explicit priority, mutually exclusive predicates where provable, and exactly one declared fallback when cases may be incomplete.
6. Predicates use the allowlisted AST: `eq`, `neq`, `in`, `exists`, `lt/lte/gt/gte`, `and`, `or`, `not` over allowlisted state paths and JSON literals. No code, regex with unsafe complexity, templates, network, or environment access.
7. Fan-out has a configured maximum and a matching join/cancellation strategy. Reducers exist for every parallel write.
8. Referenced worker/provider/model/retry/permission revisions exist, are enabled/publishable, and provide required capabilities.
9. Each external effect has timeout, retry, permission, idempotency, and failure route semantics.
10. Approval nodes identify a typed action and all protected effect nodes require a valid grant; no path bypasses the grant.
11. Verification-required worker paths reach a verify node before reviewer/publish/final success.
12. The compiler supports `spec_version`; the canonical executable JSON hash matches the stored hash.

Draft validation returns node/edge-addressed errors suitable for the GUI. The server repeats validation at publication and again when resolving a run.

## 6. Exact compilation to LangGraph

1. Load the published `workflow_version` and run configuration snapshot in one repeatable-read transaction.
2. Verify hashes, compiler compatibility, referenced revisions, and repository binding. Never substitute a current revision for a missing snapshotted revision.
3. Canonicalize nodes by ID and edges by `(from, priority, id)`.
4. Instantiate a `StateGraph(WorkflowStateV1)`.
5. For each node, look up its type in the static `NodeFactoryRegistry`. The factory closes over the immutable node configuration, effective policies, workflow node ID, and services. It returns an async callable wrapped by standard lifecycle, command-boundary, lease-fence, error-classification, and event instrumentation middleware.
6. Add `START -> entrypoint`.
7. An `always` edge compiles with `add_edge`. A conditional group compiles with `add_conditional_edges`; its router evaluates only the safe predicate AST and returns a destination key from the precomputed table.
8. A `retry` edge compiles as a conditional route guarded by the failure classifier and the snapshotted retry counter. Exhaustion routes to the node/policy's explicit terminal `fail`, `block`, or approval destination, never back into the cycle.
9. An `iterate` edge compiles with a guard that verifies the configured progress value strictly increased since the prior traversal and remains within `max_iterations`. Lack of progress or bound exhaustion is an orchestration failure, not another traversal.
10. A `fanout` factory returns LangGraph `Send` instructions bounded by configured and runtime capacity. The matching join uses a reducer keyed by child execution ID; completion requires the snapshotted expected set.
11. Terminal success/failure/cancel outcomes route to `END` only after `finalize` persists the corresponding events/projections.
12. Compile with the production Postgres checkpointer. Invocation always includes the globally unique stable `configurable.thread_id = runs.langgraph_thread_id`; immutable run and workflow-version identity is carried by the run snapshot and Jarvis configuration metadata. `checkpoint_ns` is reserved for LangGraph's compiled subgraph namespace and is never repurposed as an application partition key.
13. Cache compiled graph structure by `(workflow_content_hash, config_snapshot_hash, compiler_version)` inside an orchestrator process. A cache miss after restart recompiles deterministically.
14. Emit `graph.compiled` with hashes, compiler version, node/edge counts, and no secrets. A compile error blocks the run without starting effects.

Node factories are the only place that translates declarative config into executable behavior. Adding a node type requires implementation, threat review, schema, compiler tests, event fixtures, and acceptance tests.

## 7. Runtime scheduling and command boundaries

The orchestrator queue chooses runs; LangGraph chooses nodes within a claimed run. Each wrapped node follows:

1. Verify run lease generation and desired state.
2. Apply pending ordered commands that are legal at this boundary.
3. Create/reuse a node execution identity and emit start/resume.
4. Resolve/reuse prepared effect IDs.
5. Execute or poll typed adapters.
6. Persist result/failure references and events.
7. Return a small state update; PostgresSaver checkpoints it.

`pause` is cooperative. At the next node boundary, the wrapper creates/reuses a durable control-wait keyed to the pause command and calls its stable LangGraph `interrupt()` position. The run becomes checkpointed `paused`. A resume command causes the orchestrator to invoke the same thread with `Command(resume={control_wait_id, command_id})`; on node re-entry the wrapper calls the same interrupt, consumes/validates the resume value, records both commands, clears the wait, and continues the logical node. If an external effect is active, the adapter continues or receives cancellation according to policy and the UI remains `pause_requested`. A hard stop is modeled as cancel, not pause.

`cancel` sets terminal intent. The adapter receives one idempotent cancel request. Confirmed cancellation routes to cancelled. An ambiguous external outcome is recorded and reconciled; the stale result cannot commit because of fencing.

If cancel arrives while the graph is paused at a control or approval interrupt, the orchestrator resumes that same interrupt with a typed cancel payload. The gate/approval node validates it, performs no protected effect, writes cancellation state, and routes through `finalize` to `END`. Thus the domain run and checkpoint agree on cancellation; the control plane does not merely abandon an indefinitely resumable checkpoint.

`instruction` is appended to the thread and only injected through nodes declaring `accepts_runtime_instructions=true`. It does not mutate arbitrary checkpoint fields.

## 8. Failure classification and retry semantics

Canonical top-level classes:

| Class | Examples | Default budget impact |
|---|---|---|
| `code.implementation_failure` | worker reports incomplete/broken implementation | development code counter |
| `code.test_failure` | deterministic test/build/lint failure caused by repository | test/code counter |
| `code.review_failure` | reviewer finds a concrete acceptance/quality defect | review counter |
| `code.git_conflict` | task branch cannot integrate with current head | integration/code counter |
| `infrastructure.worker_unavailable` | host down, no capacity | worker-infrastructure counter only |
| `infrastructure.worker_transport` | SSH loss/timeout before confirmed result | transport counter only; reconcile first |
| `infrastructure.service_unavailable` | database/GitHub/Ollama network outage | service-infrastructure counter only |
| `provider.rate_limited` | remote rate limit | provider counter, honor retry-after |
| `provider.transient` | timeout/5xx | provider counter |
| `provider.contract_failure` | invalid structured output after validation repair | model-contract counter; may route profile |
| `configuration.invalid` | missing/disabled revision or incompatible capability | non-retryable blocked |
| `security.policy_denied` | disallowed action | non-retryable blocked/failed |
| `approval.rejected` | owner rejects protected action | declared reject branch, not a failure retry |
| `orchestration.runtime_error` | compiler/node invariant defect | orchestration counter then blocked |
| `user.cancelled` | explicit cancel | terminal; no retry counter |

Classification precedence is policy-denied/cancelled, explicit adapter code, deterministic verifier evidence, provider/transport evidence, then `orchestration.runtime_error`. Unknown is never silently called a code failure.

`max_retries` means additional tries after the initial operation. Each failure increments exactly one counter at its defined run/task/node scope. The event includes the counter and policy revision. Infrastructure and provider sub-retries do not increment semantic task attempt numbers unless the worker actually began a new semantic coding attempt. Backoff is persisted as `claimable_at`, so restarts do not reset it. Exhaustion follows the explicit policy action.

Reviewer failure feedback is an artifact linked to the next attempt. Deterministic verification failure normally bypasses an LLM review and routes directly according to `code.test_failure`. Every retry is visible.

## 9. Task planning, parallelism, and repository authority

Architect output is schema validated before task insertion. Tasks use stable keys, acceptance criteria, deterministic verification specs, weights, and an acyclic dependency graph. The dispatcher marks tasks ready transactionally when their dependency condition is satisfied.

Parallel task execution is allowed only when:

- the workflow uses a fan-out/dispatcher that permits it;
- worker capacity is available;
- dependency edges permit it;
- write tasks receive distinct worktrees/branches;
- task-declared exclusive resources do not conflict.

The repository integration head is authoritative. Each attempt records base SHA and result SHA. Independent review uses the result snapshot for that branch. Passing branches enter a serialized integration queue. Before merge, the integrator compares the current integration head, resolves according to policy, reruns combined gates, seals a new snapshot, and only then advances. A previously passing review cannot authorize a different SHA.

## 10. Process recovery and side-effect safety

LangGraph durable execution checkpoints node boundaries, but a crash can occur between an external effect and a checkpoint. Therefore every effect uses a durable ledger:

- `prepare`: transactionally create effect with request digest/idempotency key.
- `dispatch`: adapter starts/reuses the external operation and records its external ID.
- `await`: poll/stream by external ID; heartbeats are diagnostic.
- `commit`: accept result only under the current run/worker fencing generation, store artifacts, emit terminal event, then return state update.

On node re-entry, the wrapper consults this ledger. A successful effect is reused; a running effect is reattached; a known failed idempotent effect follows policy; an unknown non-idempotent effect blocks for reconciliation. No recovery path blindly repeats push, merge, deploy, deletion, or communication.

## 11. Three complete workflow traces

### Trace A: software change, test retry, approval, and restart

1. Owner starts a job from Organizer chat. API persists run snapshot and queue events.
2. Organizer and Architect run; Architect creates `DEV-001..003` with dependencies and verification.
3. Dispatcher selects `DEV-001`; Developer leases Worker-01 and creates a task worktree.
4. Worker edits/commits. Verify runs at the returned root and fails a test.
5. Failure is `code.test_failure`; only that budget increments. Developer retry receives test evidence and authoritative current repo state.
6. Tests pass; a sealed snapshot goes to Reviewer. Reviewer passes the current task.
7. Tasks advance and integrate serially. After the last review, publication reaches an approval node and interrupts.
8. Orchestrator is restarted while waiting. The checkpoint and pending approval remain. A new instance reclaims the run without repeating work.
9. Owner approves. Same LangGraph thread resumes; the idempotent GitHub effect pushes and opens a PR, CI status is observed, and finalize completes.
10. Event/history/artifacts are replayable after all services restart.

### Trace B: infrastructure loss without consuming code budget

1. Architect creates a task and Developer selects Worker-01.
2. SSH connection fails before remote invocation creation is confirmed.
3. Adapter reconciliation checks the remote invocation ID. If absent, it records `infrastructure.worker_transport`, increments only that counter, backs off, and retains task attempt semantics.
4. If the invocation is live, the orchestrator reattaches. If its outcome is unknown and could have changed the repository, the attempt becomes `unknown` and the workspace is quarantined; no second worker starts the same task.
5. Worker returns healthy, the infrastructure retry proceeds, and the task completes as its original/appropriately reconciled semantic attempt.
6. The UI displays outage, retry number, and recovery; developer code budget is unchanged.

### Trace C: parallel branches and integration race

1. Architect creates independent backend and frontend tasks plus a dependent integration task.
2. Dispatcher fans out two child executions. Separate worker slots/worktrees use the same recorded base SHA.
3. Both pass branch-local tests and independent review; their results enter integration order.
4. Backend obtains the repository integration lease, merges, runs combined gates, and advances integration HEAD.
5. Frontend then obtains the lease and detects its base is stale. It rebases/merges under policy. A conflict becomes `code.git_conflict` with feedback; it does not consume worker-transport budget or overwrite the backend result.
6. After conflict retry, combined gates pass. Join deduplicates child completions and releases the dependent integration task once.
7. A concurrent cancel command arriving before final publication is processed by sequence; cancel dominates a later pending resume and prevents push.

## 12. Historical replay terminology

- **Playback:** render persisted events and graph projections without executing anything. Required in V1.
- **Resume:** continue the same interrupted/nonterminal run from its current checkpoint. Required.
- **Retry:** create a new task attempt or linked run according to policy. Required.
- **Re-execute/fork:** invoke from a historical checkpoint and repeat downstream nodes. Deferred because external effects may repeat; it requires a new run ID, isolated workspace, and explicit effect policy when introduced.
