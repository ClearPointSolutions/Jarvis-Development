# Jarvis Mission Control V1 Architecture

Status: approved implementation baseline
Scope: V1 control plane, runtime, integrations, and operator UI

Technology baseline: Next.js, React, TypeScript, Tailwind CSS, shadcn/ui or an accessibility-equivalent component system, React Flow, TanStack Query, selective Zustand, and xterm.js on the frontend; Python 3.12+, FastAPI, Pydantic, SQLAlchemy 2.x, Alembic, asyncio, LangGraph, and `langgraph-checkpoint-postgres` on the backend; PostgreSQL, pytest, frontend component tests, Playwright, type checks, and linting across the system. Exact compatible versions are pinned and proven in M0/M1 rather than assumed from the legacy inventory.

## 1. Architectural invariants

1. LangGraph is the orchestration source of truth. React Flow is an editor/visualization, not a scheduler.
2. PostgreSQL is the durable system of record for configuration, commands, normalized events, query projections, leases, effect records, and LangGraph checkpoints.
3. The API validates and records commands; a dedicated orchestrator claims and executes runs outside request handlers.
4. Meaningful observable actions become redacted, append-only events before reaching the browser.
5. Runtime configuration is versioned data. A run is bound to an immutable resolved snapshot.
6. External effects are at-least-once at the transport boundary and idempotent/fenced at the application boundary. The system does not claim universal exactly-once execution.
7. Large logs and payloads are immutable artifacts referenced from state/events.
8. No browser path can submit arbitrary shell commands or receive a secret.

## 2. Runtime topology

```text
Authenticated browser
  | HTTPS; same-origin UI, JSON commands, SSE
  v
Reverse proxy / private LAN or VPN ingress
  |--------------------------|
  v                          v
Next.js web              FastAPI control API
  (no secrets)             | auth, CRUD, commands, queries, SSE
                            |
                            v
                     PostgreSQL 16+
                     - control/domain schemas
                     - append-only events + projections
                     - queue, commands, leases, effect ledger
                     - LangGraph checkpoint schema
                            ^
                            |
                    dedicated orchestrator
                    - run claimer and recovery
                    - workflow compiler + LangGraph
                    - event/outbox writer
                    - provider, worker, GitHub adapters
                    - health collection
                      |        |             |
                      v        v             v
                Worker-01   OpenAI/Ollama   GitHub
                 via SSH     via HTTPS/LAN   via API/gh adapter
```

Docker Compose runs `jarvis-v1-web`, `jarvis-v1-api`, `jarvis-v1-orchestrator`, and `jarvis-v1-postgres` side by side on Jarvis-Core. The browser can reach only the reverse-proxied web/API surface. PostgreSQL is private to the V1 network or bound to loopback for administration.

## 3. Component responsibilities

### 3.1 Next.js web

- Renders login, dashboard, Organizer chat, projects/jobs/runs, workflow studio, registries, approvals, artifacts, health, and debug views.
- Uses TanStack Query for request/response server state and a small Zustand store only for ephemeral UI state such as filters, selected node, and panel layout.
- Opens a same-origin `EventSource` stream and applies events to a cache only after deduplicating by `event_id`/cursor.
- Treats server snapshots as authoritative after reconnect or detected gaps.
- Uses React Flow for draft editing and runtime projection. Runtime node state comes from events/projections; dragging a runtime node changes layout only.
- Uses xterm.js solely to render escaped, read-only command output.

The web container has no database, SSH, provider, GitHub, or secret access.

### 3.2 FastAPI control API

- Authenticates sessions and authorizes every object/action.
- Exposes versioned REST resources for threads, projects, repositories, jobs, runs, tasks, workflow drafts/versions, workers/revisions, providers, model profiles, policies, approvals, artifacts, health, and audit queries.
- Validates workflow specs and publishes immutable versions.
- Converts state-changing requests into idempotent durable records and commands in short transactions.
- Serves initial read models and authorized artifact content.
- Streams committed events using database replay plus PostgreSQL notification wakeups.
- Never calls `graph.invoke()` for long work and never executes a caller-supplied command.

### 3.3 PostgreSQL

Logical schemas:

- `control`: users, sessions, configuration, workflow versions, jobs/runs, commands, leases, effects, integrations, and projections.
- `event_store`: immutable normalized events, per-run sequence counters, and audit events.
- `langgraph`: tables managed through the compatible Postgres checkpointer/migrations.

All three may share the dedicated V1 database while retaining separate roles and schema grants. Domain state changes and their normalized event/outbox insertion occur in one transaction where the application owns both. `LISTEN/NOTIFY` is a wake-up optimization only; reconnect/replay always queries the event table.

### 3.4 Orchestrator service

- Claims runnable rows with ordered `FOR UPDATE SKIP LOCKED`, assigns a renewable lease/fencing generation, and runs only within configured concurrency.
- Loads the immutable workflow version and resolved configuration snapshot, compiles it through the approved node registry, and invokes/streams LangGraph using the run's stable `langgraph_thread_id` and PostgresSaver.
- Observes graph/node/tool/model/adapter output, normalizes it, persists it, and updates query projections.
- Reconciles durable run commands and approval decisions at safe boundaries.
- Owns worker/provider/GitHub adapters, retry classification, health probes, usage accounting, and recovery.
- Refuses to commit results from an expired lease or stale fencing generation.

### 3.5 Adapters

Adapters expose typed capability interfaces and never leak provider-native payloads directly to the UI.

- `WorkerAdapter`: validate, start, inspect, cancel, collect result, and health.
- `ModelProviderAdapter`: validate profile, health, invoke/stream, normalize usage/errors.
- `SourceControlAdapter`: inspect repository, create branch/worktree, snapshot, integrate, push, create/update PR, inspect CI.
- `ArtifactStore`: put/get immutable content by digest and metadata.
- `HealthProbe`: sampled host/service/provider status.

OpenHands over SSH is the first worker implementation. Codex or another worker adds an adapter plus declared capabilities, not workflow branches.

## 4. Source-of-truth boundaries

| Concern | Authority | Notes |
|---|---|---|
| Workflow execution position/state | LangGraph checkpoint for the run | Same `langgraph_thread_id` on resume; never inferred from UI |
| Workflow/config definition | Published immutable version + run snapshot | Drafts cannot execute |
| Intent/control | Durable `run_commands` and approval decisions | API records; orchestrator applies |
| Historical facts | Append-only event store | Events never updated/deleted through application APIs |
| Current lists/status UI | Relational projections | Rebuildable/auditable from events plus checkpoint reconciliation |
| External effect status | Effect/invocation ledger + adapter reconciliation | Fenced; unknown outcomes are explicit |
| Large content | Artifact store + immutable metadata | Digest checked; event/state stores references |
| Secrets | Server-side secret store/file/environment | Database/browser store references and status only |

A projection discrepancy never causes the UI to advance the workflow. Reconciliation reads the checkpoint/effect ledger, emits a correction event, and repairs the projection.

## 5. Principal flows

### 5.1 Start a run

1. Browser sends an idempotent `POST /api/v1/projects/{project_id}/jobs` with objective and a published workflow version.
2. API authorizes the project, resolves referenced active configuration revisions, validates capabilities/policies, and writes the job, queued run, redacted resolved snapshot, and `job.created`/`run.queued` events atomically.
3. API returns `202 Accepted` with IDs and event cursor.
4. Orchestrator claims the run, creates/renews its lease, compiles the exact snapshot, and invokes LangGraph with the stable thread ID.
5. Runtime state/events become query projections; SSE subscribers wake and fetch committed rows.

### 5.2 Read snapshot then stream

1. Browser requests the run view. API returns a projection plus `read_cursor`, all from a repeatable read boundary.
2. Browser opens `/api/v1/runs/{run_id}/events/stream?after={read_cursor}`.
3. API replays authorized matching events after the cursor, then listens for wakeups and queries again.
4. SSE `id` is the event's global durable position. `Last-Event-ID` takes precedence on reconnect.
5. A cursor outside retention or a detected run-sequence gap produces a `stream.reset` control message; the browser reloads the snapshot.

### 5.3 Control a run

1. Browser posts pause/resume/cancel/instruction/retry with an idempotency key and expected run version.
2. API inserts one ordered command and emits `run.command_requested`; duplicate keys return the original response.
3. Orchestrator locks pending commands in sequence. Cancel dominates later pause/resume; stale/invalid commands are rejected with a reason event.
4. At a node boundary, a pause request creates/reuses a durable control-wait record and the standard node wrapper calls a stable LangGraph control `interrupt()`. On resume, that same interrupt consumes the `Command(resume=...)` value and clears the wait. While an external effect is active the UI says `pause_requested`, not `paused`.

### 5.4 Approval

1. A policy-aware graph node creates or reuses an approval request and calls LangGraph `interrupt()` with a small JSON-safe reference.
2. Checkpoint and events show `approval_required`; the run lease can be released while waiting.
3. Owner posts a decision once. API stores an append-only decision with actor/session context and queues a resume command.
4. Orchestrator claims the run and invokes the same graph/thread with `Command(resume=decision)`.
5. Because an interrupting node restarts from its beginning, all work before `interrupt()` is read-only or protected by the effect ledger. The protected effect occurs after the approved decision in an idempotent effect step.

### 5.5 Worker execution

1. Runtime creates a task attempt, resolves a compatible worker revision, and leases a worker slot.
2. Adapter creates an invocation/effect record with a unique idempotency key and fencing token.
3. OpenHands SSH adapter creates/uses an isolated task branch/worktree and invokes the legacy runner through the compatibility wrapper described in `WORKER_PROTOCOL.md`.
4. Output is redacted and summarized into events; full output becomes a digest-addressed artifact.
5. Deterministic verification runs at the adapter-reported repository root. A repository snapshot is sealed for review.
6. Result commit is accepted only while run and worker leases are current. Reviewer receives the sealed current state, not merely the last diff.

## 6. API resource outline

All endpoints are under `/api/v1`; request/response schemas are generated from Pydantic and consumed by the frontend client.

- `POST /auth/login`, `POST /auth/logout`, `GET /session`
- `GET|POST /threads`, `GET /threads/{id}`, `POST /threads/{id}/messages`
- `GET|POST /projects`, `GET|PATCH /projects/{id}`, repository-binding subresources
- `GET|POST /jobs`, `GET /jobs/{id}`, `GET /jobs/{id}/runs`
- `POST /projects/{id}/jobs`, `GET /runs/{id}`, `POST /runs/{id}/commands`
- `GET /runs/{id}/events`, `GET /runs/{id}/events/stream`
- `GET|POST|PATCH /workflow-templates`, draft validate/publish/version endpoints
- `GET|POST|PATCH /workers`, revision/validate/health endpoints
- `GET|POST|PATCH /providers`, model-profile and route-policy endpoints
- `GET /approvals`, `POST /approvals/{id}/decisions`
- `GET /artifacts/{id}`, `GET /health`, `GET /system/health`

Every list is paginated with stable ordering. Mutable resources use optimistic `version`/ETag checks. Commands and creates use idempotency keys. SSE is GET-only and cookie-authenticated on the same origin.

## 7. Concurrency and race handling

### 7.1 Run queue

Claims are ordered by priority, `claimable_at`, and creation time. A single atomic transaction locks a candidate with `SKIP LOCKED`, increments `lease_generation`, and assigns owner/expiry. Multiple orchestrators may run without double-committing a result. A sweeper makes expired non-terminal leases claimable after reconciliation.

### 7.2 Commands

Each run has a monotonically increasing command sequence and projection version. API transactions lock the run command counter. Orchestrator applies commands in sequence and records `applied`, `rejected`, or `superseded`. Terminal cancel supersedes pending pause/resume; an approval decision cannot revive a cancelled run.

### 7.3 Worker capacity

Workers expose `max_concurrency`; concrete slot rows are individually leased. Heartbeats extend leases. A stale holder cannot publish results after its fencing token changes. A worker with ambiguous remote execution is quarantined/reconciled before the same work is dispatched elsewhere.

### 7.4 Repository writes

Each write attempt owns one worktree and task branch. Parallel branches may execute and review independently. A per-project/repository integration lease serializes merges. Merge checks expected base SHA, rebases/merges according to project policy, reruns required gates on the combined head, then advances the integration ref atomically. Conflicts are `code.git_conflict`, never an infrastructure retry. Review evidence is invalidated if HEAD changes.

### 7.5 Parallel graph work

Only explicit fan-out nodes create parallel task dispatch. State reducers are defined for every concurrently written channel. Join nodes use expected child execution IDs and ignore duplicate completions. A task dependency unique constraint and row locks prevent two dispatchers from claiming the same task attempt.

## 8. Durability and restart recovery

The API is stateless apart from signed/encrypted session context and database connections. Its restart only interrupts SSE; browsers reconnect by cursor.

The orchestrator persists intent before every effect and relies on checkpoints at graph boundaries. On restart:

1. Expired run leases are identified.
2. In-flight effects/invocations are inspected using their durable IDs.
3. Completed effects are reused; live effects are reattached/polled; confirmed absent safe effects may be retried; unknown non-idempotent outcomes become blocked for reconciliation.
4. The exact workflow/config snapshot is recompiled.
5. LangGraph resumes with the same thread ID from its checkpoint.
6. A recovery event records previous/new lease generation and decisions. Recovery alone consumes no semantic failure budget.

Node code must follow prepare/dispatch/await/commit phases. Re-entry checks the effect ledger before dispatch. Side effects before a LangGraph interrupt must be idempotent because the interrupted node restarts on resume. These rules align with current LangGraph persistence and interrupt behavior: [persistence](https://docs.langchain.com/oss/python/langgraph/persistence) and [interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts).

## 9. Event and projection architecture

Producers submit typed event intents to one normalizer. The normalizer validates schema/version, assigns correlation/causation, redacts recursively, stores oversized fields as artifacts, allocates commit-safe durable ordering under the global event-counter lock, inserts the immutable event, and updates owned projections in the same transaction. All such mutations acquire the global counter before sorted run counters and aggregate rows to avoid deadlocks. A trigger or constrained database role rejects update/delete on event rows.

PostgreSQL `NOTIFY` carries only a small cursor/wakeup after commit. It is not a message broker and its payload is not treated as durable delivery. Queue consumers use `SKIP LOCKED`, which PostgreSQL explicitly documents as suitable for queue-like access, with deterministic ordering in the query: [PostgreSQL `SELECT`](https://www.postgresql.org/docs/current/sql-select.html).

## 10. Observability without reasoning disclosure

The system records agent/node lifecycle, declared input/output summaries, tool calls, file paths/diffs, commands, test outcomes, model/provider metadata, usage, decisions, failures, health, and timing. It excludes scratchpads, hidden reasoning, provider-internal reasoning fields, raw secrets, unrestricted environment dumps, and unbounded source/log bodies. Debug mode grants more redacted structured data, not chain-of-thought.

Every service emits structured operational logs with event/run/correlation IDs. Health endpoints distinguish liveness (process event loop), readiness (required dependencies/migrations), and dependency health. The event store is the operator audit trail; service logs are diagnostic and may be rotated.

## 11. Proposed repository layout for implementation

```text
api/
  app/api/              # FastAPI routes and auth dependencies
  app/domain/           # domain models and policies
  app/db/               # SQLAlchemy repositories and projections
  app/events/           # schemas, redaction, append/replay
  app/workflows/        # spec validation and compiler shared package
  migrations/           # Alembic
orchestrator/
  app/runtime/          # claims, commands, recovery, LangGraph runner
  app/nodes/            # approved node factories
  app/adapters/         # worker/provider/GitHub/artifact adapters
web/
  app/                  # Next.js routes
  components/           # dashboard, workflow, feed, inspectors
  lib/                  # generated API types, SSE/cache handling
packages/contracts/     # generated JSON Schema/OpenAPI fixtures if useful
deploy/                 # side-by-side Compose and service configuration
scripts/                # dev, demo, verify, deploy
tests/                  # cross-service contract and E2E fixtures
docs/
```

The API and orchestrator may share a Python package for schemas/domain logic, but they remain separate processes and deployable services.

## 12. Architectural fitness rules

CI MUST fail when:

- an event payload violates its versioned schema or redaction tests;
- a workflow fixture cannot compile deterministically;
- a browser bundle imports server-only configuration/secret modules;
- an application role can update/delete event rows;
- an API route invokes a worker/shell or a long LangGraph run;
- adapter contract/idempotency/fencing tests fail;
- migrations cannot upgrade from a fresh database and the supported prior release;
- demo mode emits unmarked real-looking events or reaches real network adapters.
