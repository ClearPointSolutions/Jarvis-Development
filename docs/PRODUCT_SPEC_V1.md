# Jarvis Mission Control V1 Product Specification

Status: architecture baseline
Audience: product owner, implementers, reviewers, operators
Normative language: **MUST**, **SHOULD**, and **MAY** indicate requirement strength.

## 1. Product statement

Jarvis Mission Control is the authenticated browser interface and durable control plane for the Jarvis LangGraph system. It lets the human supervisor converse with the Organizer, define projects and executable workflows, start and control jobs, observe real agent and tool activity, decide approvals, inspect results, and review historical execution without exposing hidden model reasoning or infrastructure credentials.

The primary chain of authority is:

`Human supervisor -> Mission Control -> LangGraph supervisor -> workers/adapters -> tools, GitHub, and infrastructure`

LangGraph is the execution authority. Mission Control presents and commands it; the UI never advances a workflow locally.

## 2. V1 users and trust assumptions

V1 is a single-owner administrative system. It has an authenticated `owner` account and a role-ready authorization model, but team tenancy, public signup, and delegated organization administration are out of scope. The owner is trusted to approve privileged actions; browsers, submitted text, model output, worker output, repositories, and external services are not trusted.

Primary user: the human supervisor who creates objectives, configures execution, observes progress, and makes risk decisions.

Secondary operator mode: a read-only wall/display view. It receives only authenticated, redacted data and exposes no controls.

## 3. Goals

V1 MUST provide:

1. Secure login and session management.
2. Organizer conversation threads that can create objectives and accept follow-up instructions.
3. Projects, repositories, jobs, runs, tasks, attempts, history, and artifacts.
4. A real-time graph and activity feed driven only by normalized persisted runtime events.
5. A worker registry and GUI editor backed by versioned worker configuration.
6. Provider connections and model profiles with first-class OpenAI and Ollama routing.
7. A React Flow workflow-template editor whose published versions compile into executable LangGraph graphs.
8. Per-node worker, model, retry, verification, timeout, and approval policy.
9. Durable queueing, checkpointing, pause/resume/cancel commands, failure-specific retries, and process recovery.
10. Real LangGraph interrupt/resume approvals.
11. Visibility into files, diffs, commands, tests, model usage, Git operations, PR/CI state, and infrastructure health.
12. A read-only terminal/log experience; no browser-accessible arbitrary shell.
13. Token, latency, and cost-accounting infrastructure, including explicit unknown values.
14. Deterministic demo mode and a real Jarvis-Worker-01 staging path.
15. Side-by-side deployment at `/opt/jarvis-v1`, leaving `/opt/jarvis` untouched.

## 4. Non-goals

V1 does not include public internet exposure, public signup, a general interactive terminal, arbitrary user-authored code inside workflow routing expressions, a mobile app, voice/home automation, replacement of Open WebUI, replacement of LangSmith Studio, or promotion over the legacy `/opt/jarvis` installation.

Historical playback of persisted events is in scope. Re-executing from an old checkpoint or forking a historical run is deferred until its side-effect safety model is explicitly approved; a replay button MUST NOT silently repeat external effects.

## 5. Core concepts

- **Conversation thread:** Organizer messages and user instructions. It can contain multiple jobs.
- **Project:** Durable objective context plus one or more repository bindings and policies.
- **Job:** A requested objective and its lifecycle. A job can have more than one run after an explicit whole-run retry.
- **Run:** One LangGraph execution against one immutable workflow/configuration snapshot.
- **Task:** A dependency-aware unit produced by the Architect/Organizer or supplied to the workflow.
- **Attempt:** One semantic try to complete a task. Transport/provider sub-retries are recorded separately and do not automatically consume the task's code-failure budget.
- **Workflow template/version:** Editable identity plus an immutable published executable specification.
- **Worker:** A configured execution capability, such as the OpenHands SSH adapter for Jarvis-Worker-01.
- **Provider/model profile:** A secret-free provider reference and model behavior/capability configuration.
- **Event:** An immutable normalized fact about an observable action or transition.
- **Approval:** A durable request and append-only human decision linked to a LangGraph interrupt.
- **Artifact:** Immutable metadata and content reference for files, logs, reports, diffs, or outputs.

## 6. Information architecture

### 6.1 Mission dashboard

The main authenticated route shows Organizer chat, the selected run's live execution graph, task-based progress, recent activity, pending approvals, and compact system/worker/provider health. The user can change the selected run without changing execution.

### 6.2 Projects and jobs

Project views show repository bindings, objectives, policies, active jobs, branches/PRs, and history. Job/run views show the workflow snapshot, task tree, attempts, events, artifacts, commands, tests, failures, approvals, usage, and final result.

### 6.3 Workflow studio

The workflow editor creates drafts, validates them server-side, and publishes immutable versions. Nodes and edges are executable data. Invalid, dangling, unsafe, or unbounded graphs cannot be published or run. Visual layout is saved but does not influence execution semantics.

### 6.4 Configuration

Worker, provider, model-profile, retry-policy, and project editors expose non-secret settings, validation state, version history, and health. Secret fields accept only a server-side secret reference or a write-only secret operation; stored secret values are never returned.

### 6.5 Operations and history

Operations views expose health, lease state, queue depth, failures, and redacted diagnostics. History is reconstructed from stored projections and append-only events. The default view is human-readable; owner debug mode can reveal redacted raw event/state metadata, never hidden chain-of-thought.

## 7. Required user journeys

### 7.1 Configure and run real work

The owner logs in, creates or edits a Worker-01 definition, validates its connectivity, configures a provider/model profile, publishes an executable workflow, creates a project/objective, and starts a run. The API returns after enqueueing. The orchestrator claims the run, compiles the published version, and streams persisted events. Architect tasks appear; Developer work executes at the real repository root on Worker-01; deterministic verification and independent review follow. Failures route according to class-specific policy. Any protected publish action interrupts for approval. Completion and artifacts remain after service restarts.

### 7.2 Intervene safely

The owner requests pause, resume, cancel, retry, or supplies an Organizer instruction. The browser posts an idempotent command. The UI shows `*_requested` until the orchestrator acknowledges it at a safe boundary. Cancel attempts to stop an active adapter invocation and records whether termination was confirmed. Approval decisions resume the exact interrupted LangGraph thread; duplicate or stale decisions are rejected.

### 7.3 Diagnose a run

The owner opens a failed run, sees the failure class, retry counter for that class, affected task/attempt/node, command/test summaries, immutable log artifacts, repository snapshot used by the reviewer, and infrastructure health at the time. Large output is referenced rather than embedded in graph state or routine events.

### 7.4 Deterministic demonstration

Demo mode uses deterministic in-process provider, worker, GitHub, and health adapters. It exercises task creation, parallel-capable scheduling, a planned test failure and retry, approval interrupt/resume, log/file/test events, and durable history. Demo events are clearly labeled `mode=demo` and never mixed with real results.

## 8. Functional requirements

### 8.1 Authentication and authorization

- Every non-health UI/API route MUST require authentication.
- State-changing requests MUST enforce authorization, origin checks, CSRF protection, and idempotency keys.
- Login, logout, approval, configuration changes, control commands, and secret-reference changes MUST be audited.
- The API MUST never return secret values.

### 8.2 Conversation and objectives

- Messages MUST be durable and ordered within a thread.
- An objective start is an explicit command, not an accidental side effect of rendering or reconnecting chat.
- Follow-up instructions to an active run MUST be durable commands and enter LangGraph only at declared safe input points.
- Model messages store/display final content, tool requests/results, and concise status summaries; hidden reasoning is excluded.

### 8.3 Runtime control

- Starting a run MUST persist the job, run, workflow/config snapshot, enqueue state, and creation events atomically.
- API request handlers MUST NOT own long-lived execution.
- Pause is cooperative and reports `pause_requested` until checkpointed. Resume applies only to a paused run. Cancel is terminal for that run. Whole-run retry creates a new run linked to its predecessor.
- Concurrent/duplicate commands MUST resolve deterministically and remain auditable.

### 8.4 Observation

- Every meaningful observable action MUST emit a normalized event before it can be represented as live activity.
- Events MUST be append-only, persisted before delivery, ordered by durable cursor, replayable, and redacted before persistence.
- The browser MUST recover missed events after disconnect using its last durable cursor.
- Progress MUST be computed from task weights/statuses or shown as indeterminate; it MUST NOT be invented from elapsed time.

### 8.5 Workflow configuration

- Draft editing and publication MUST be separate.
- Published workflow versions and per-run resolved configuration snapshots MUST be immutable.
- All node and edge behavior MUST pass schema, graph, capability, reference, and policy validation.
- Existing runs MUST be unaffected by later configuration edits.

### 8.6 Worker execution and source control

- The initial production adapter MUST invoke the existing OpenHands runner on Jarvis-Worker-01 over SSH.
- Verification MUST run from the authoritative repository/worktree root supplied by the adapter.
- Reviewer input MUST include an immutable snapshot of current branch HEAD, tree/status, relevant source, test evidence, and task acceptance criteria; the latest diff is supplemental.
- Parallel write tasks MUST use isolated branches/worktrees. Integration/merge MUST be serialized and revalidated against the current integration head.
- Remote push, PR creation, merge, deploy, deletion, privileged commands, and policy-selected actions MUST require the configured approval.

### 8.7 Provider routing and accounting

- OpenAI and Ollama MUST share a provider interface while retaining provider-specific health, capability, and usage handling.
- Route selection MUST be deterministic from versioned policy, health, required capabilities, and availability.
- Usage records MUST preserve reported tokens, estimates and their provenance, latency, retry/failover, and a price snapshot or `unknown` cost.
- Optional provider absence MUST degrade clearly without breaking unrelated routes.

## 9. Quality attributes and service targets

- **Durability:** committed jobs, commands, events, approvals, artifacts metadata, and checkpoints survive API/orchestrator restart.
- **Delivery:** event delivery is at least once; consumers deduplicate by event ID/cursor. External effects use idempotency and fencing to achieve effectively-once committed outcomes where supported.
- **Responsiveness:** enqueue/control API p95 under 500 ms on the LAN excluding login hashing; a committed event should normally be visible in a connected browser within 2 seconds.
- **Recovery:** an expired run lease is reclaimable automatically. Recovery must not consume a code/test/review retry budget merely because a process died.
- **Scale target:** at least 20 simultaneous browser streams, 100 queued runs, and configured parallel execution up to available worker/provider capacity. V1 is not a high-volume multi-tenant service.
- **Retention:** events and audit records are retained by default; large logs/health samples may use documented retention policies, never silent deletion.
- **Accessibility:** keyboard-accessible controls, text status in addition to color/animation, focus management for approvals, and WCAG 2.1 AA contrast are required.
- **Compatibility:** desktop-first current evergreen browsers; mobile supports chat, status, feed, approvals, pause, and cancel with a simplified graph.

## 10. Completion definition

V1 is complete only when the tests in `docs/ACCEPTANCE_TESTS.md` pass, including deterministic demo mode and the specified real Worker-01/GitHub staging scenario; `scripts/verify.sh`, backend/frontend tests, type/lint checks, Playwright, and production builds pass; staging survives process restart; no secret is committed or exposed; deployment is reproducible; and `/opt/jarvis` remains intact.
