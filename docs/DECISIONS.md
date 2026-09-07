# Jarvis V1 Architecture Decisions

Status: accepted baseline for implementation. Changes require an appended decision entry, migration/compatibility analysis, and updates to affected specifications.

## Source observations

The bootstrap repository contains no V1 application code. The preserved prototype consists of:

- a synchronous CLI LangGraph with `architect -> select_task -> developer -> verify -> reviewer -> advance`, PostgresSaver, one thread ID, a fixed seven-attempt review loop, and final terminal output;
- an SSH call from Core to the existing OpenHands runner on Worker-01 using a base64 JSON argument and `JARVIS_RESULT_JSON=` sentinel;
- verification at the real remote workspace root, normalization of common model-invented absolute `cd` prefixes, deterministic command evidence, and Reviewer context containing a current repository/source snapshot plus the latest diff;
- one shared project workspace per slug and automatic commits, with no normalized live events, API/UI, queue/lease, durable effect identity, true approvals, configuration registry, or parallel-work isolation;
- PostgreSQL 16 bound to loopback at legacy `/opt/jarvis`, which remains recovery material.

These behaviors are evidence and compatibility constraints, not code to transplant blindly.

## Decision index

| ID | Decision |
|---|---|
| ADR-001 | Split browser/web, control API, orchestrator, and database processes |
| ADR-002 | Use PostgreSQL for queue/leases; do not add Redis in V1 |
| ADR-003 | Use SSE for browser events and HTTP for commands |
| ADR-004 | Persist normalized events first; LISTEN/NOTIFY is wakeup only |
| ADR-005 | Keep LangGraph checkpoints authoritative for execution |
| ADR-006 | Compile immutable workflow data through a static node registry |
| ADR-007 | Snapshot exact configuration per run |
| ADR-008 | Classify failures and budget retries by class |
| ADR-009 | Use expiring leases and fencing for runs/workers/integration |
| ADR-010 | Use an effect ledger; promise at-least-once delivery, not universal exactly-once |
| ADR-011 | Support legacy OpenHands over SSH behind a generic worker protocol |
| ADR-012 | Isolate task writes and serialize integration |
| ADR-013 | Implement approvals with LangGraph interrupt/resume |
| ADR-014 | Make OpenAI and Ollama separate first-class adapters under one interface |
| ADR-015 | Store large content as immutable artifacts |
| ADR-016 | Use server-side opaque sessions for the private single-owner V1 |
| ADR-017 | Deploy with a dedicated V1 database/services under `/opt/jarvis-v1` |
| ADR-018 | Prove the stack with deterministic, network-denied demo adapters |
| ADR-019 | Support event playback now; defer historical checkpoint re-execution |
| ADR-020 | Prefer a GitHub App; allow a scoped existing-machine-account staging adapter |
| ADR-021 | Collect health without mounting the Docker socket |
| ADR-022 | Pin and compatibility-test runtime dependencies during M0/M1 |

## Accepted decisions

### ADR-001 — Process split

**Decision:** Next.js serves the UI, FastAPI serves authentication/control/query/SSE, a dedicated Python orchestrator owns long-running LangGraph execution/adapters, and PostgreSQL holds durable state.

**Why:** API restarts and request timeouts cannot own hours-long work. Different secret and network privileges are enforceable. The web remains untrusted and secret-free.

**Consequences:** More services and health checks; command and event contracts are mandatory. A monolithic FastAPI `graph.invoke()` request was rejected.

### ADR-002 — PostgreSQL queue and leases

**Decision:** Claim queued runs with ordered `SELECT ... FOR UPDATE SKIP LOCKED`, durable backoff timestamps, and lease rows. Do not add Redis initially.

**Why:** PostgreSQL is already required for state/events/checkpoints; one transactional system reduces operational and consistency burden. PostgreSQL documents `SKIP LOCKED` as appropriate for avoiding contention among consumers of queue-like tables: [PostgreSQL SELECT locking clause](https://www.postgresql.org/docs/current/sql-select.html#SQL-FOR-UPDATE-SHARE).

**Consequences:** Queue scale is bounded by database design, which is acceptable for V1. Claims, indexes, and sweeper behavior need concurrency tests. Add a broker only after measured need.

### ADR-003 — SSE plus HTTP commands

**Decision:** Same-origin SSE streams committed server-to-browser events; normal idempotent HTTP endpoints record commands.

**Why:** Runtime traffic is predominantly one-way, browser reconnection/cursors are natural, and operational complexity is lower than WebSockets.

**Consequences:** Commands are separate requests; proxy buffering/timeouts need configuration. WebSockets remain a future option if proven bidirectional/scale needs arise.

### ADR-004 — Durable event delivery

**Decision:** Store the normalized event and projection update transactionally, then send a small PostgreSQL notification as a wakeup. SSE always queries by durable cursor.

**Why:** PostgreSQL notifications are not a durable queue. Database replay handles disconnects, API restarts, and missed wakeups.

**Consequences:** Event volume/index/retention require care. A direct in-memory event bus as the source of truth was rejected.

### ADR-005 — LangGraph execution authority

**Decision:** Compile every run into LangGraph with PostgresSaver and a stable per-run thread ID. Relational statuses are query/control projections, not an alternative workflow engine.

**Why:** It preserves durable graph semantics, fault recovery, and human interrupts while giving Mission Control queryable state. Current LangGraph documentation describes checkpointed threads, recovery, and resume behavior: [persistence](https://docs.langchain.com/oss/python/langgraph/persistence).

**Consequences:** Projection reconciliation and checkpoint compatibility tests are required. The UI cannot optimistically advance a node.

### ADR-006 — Executable workflow spec

**Decision:** Published canonical JSON plus a static code-reviewed node factory registry compiles into LangGraph. Safe declarative predicates route edges; only bounded retry cycles and bounded monotonic iterator cycles are permitted.

**Why:** Visual workflows must execute without becoming arbitrary-code injection or a second scheduler.

**Consequences:** New node types require code/schema/security/tests. Arbitrary Python/JavaScript nodes and decorative runtime nodes were rejected.

### ADR-007 — Immutable run snapshots

**Decision:** A run resolves exact workflow, worker, model, retry, permission, repository, and compiler revisions into a content-hashed, secret-free snapshot.

**Why:** Restart and audit must not depend on settings edited later.

**Consequences:** Configuration revisioning and migration/upcasting are required; active runs do not automatically receive configuration fixes.

### ADR-008 — Failure classes and independent budgets

**Decision:** One normalized classifier selects exactly one failure class/counter. Infrastructure/provider failures do not spend developer code/test/review budgets. `max_retries` means tries after the initial operation.

**Why:** The prototype proved that transport/tooling failures otherwise exhaust the wrong retry loop.

**Consequences:** Adapters need typed errors and ambiguous-outcome reconciliation. Unknown failures block/escalate rather than defaulting to developer fault.

### ADR-009 — Leases with fencing

**Decision:** Run claims, worker slots, and repository integration locks use expiry, heartbeat, monotonically increasing generation, and stale-result rejection.

**Why:** Expiry alone can allow two owners during pauses/network partitions. Fencing prevents an old owner from committing.

**Consequences:** Every authoritative result/effect commit carries generation. Clock/expiry and recovery need deterministic tests.

### ADR-010 — Effect ledger and delivery semantics

**Decision:** Persist effect intent/idempotency key before dispatch, attach external ID, reconcile on re-entry, and fence commit. State/event delivery is at least once; supported effects become effectively once at committed outcome.

**Why:** A crash can occur after an external side effect but before a LangGraph checkpoint. Universal exactly-once claims would be false.

**Consequences:** Adapter-specific reconcile behavior is mandatory. Unknown non-idempotent outcomes block rather than repeat.

### ADR-011 — Generic worker adapter, legacy first

**Decision:** Implement `OpenHandsSshWorkerAdapter` for the observed base64/sentinel runner and add a V1 invocation wrapper for durable idempotency without replacing the runner. Future Codex workers implement the same protocol.

**Why:** It satisfies real Worker-01 compatibility while avoiding OpenHands assumptions in workflow state/UI.

**Consequences:** Until wrapper/isolation passes staging, concurrency remains one and lost synchronous SSH can become an explicit unknown outcome.

### ADR-012 — Branch/worktree isolation and serialized integration

**Decision:** Each write task/attempt uses an isolated branch/worktree. Passing work merges under an integration lease with base-SHA check and combined gates.

**Why:** Parallel agents cannot safely mutate one directory/ref; reviewers need authoritative stable state.

**Consequences:** Additional Git lifecycle/cleanup and conflict feedback. Blind concurrent merge or last-writer-wins was rejected.

### ADR-013 — Real approvals

**Decision:** Approval nodes call LangGraph `interrupt()`; decisions are durable and resume the same thread using `Command(resume=...)`. Protected effects validate a digest-bound grant immediately before execution.

**Why:** A database flag/UI modal alone cannot durably suspend the workflow. LangGraph documents indefinite checkpointed interrupts and same-thread resume, including node restart behavior: [interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts).

**Consequences:** Pre-interrupt work must be idempotent/read-only; duplicate/stale decisions reject. Pause remains a separate cooperative control.

### ADR-014 — Provider abstraction

**Decision:** OpenAI and Ollama have distinct adapters behind a normalized provider interface. Ordered versioned route policy selects candidates by capabilities, data policy, health, and circuit state.

**Why:** A nominally OpenAI-compatible endpoint does not make health, usage, options, and error semantics identical. Both providers remain first class.

**Consequences:** More contract tests; token/cost may be unknown/estimated. Model names and URLs are never hard-coded.

### ADR-015 — Artifact references

**Decision:** Bounded summaries/references go into events/checkpoints; large stdout, stderr, source snapshots, patches, reports, and binary content go into a digest-addressed artifact backend.

**Why:** The prototype and source notes show huge logs make graph state unreliable and expensive.

**Consequences:** Artifact authorization, retention, digest verification, backup, and missing-content handling are release requirements. Local filesystem is initial backend behind an interface.

### ADR-016 — Server-side sessions

**Decision:** Use Argon2id password authentication and random opaque server-side sessions in Secure HttpOnly SameSite cookies for single-owner V1.

**Why:** This minimizes browser token exposure and supports revocation without adding an external identity dependency.

**Consequences:** CSRF/origin protection and session database availability are required. Multi-user/public/SSO requires a future review.

### ADR-017 — Dedicated side-by-side V1 deployment

**Decision:** Independent V1 service names, database, volumes, secrets, ports, and root beneath `/opt/jarvis-v1`; never reuse/migrate/stop `/opt/jarvis` in staging.

**Why:** The prototype is the recovery path until explicit promotion.

**Consequences:** Temporary duplicate resource use and separate backup/operations. No in-place upgrade from legacy.

### ADR-018 — Deterministic demo mode

**Decision:** Demo uses real API/orchestrator/LangGraph/event/UI paths with deterministic fake external adapters and denied outbound network.

**Why:** It proves control-plane behavior reproducibly without fabricating production activity or requiring homelab access.

**Consequences:** Fixtures must stay behaviorally compatible and clearly labeled. A frontend-only animation demo was rejected.

### ADR-019 — Playback versus re-execution

**Decision:** V1 replays stored events for history. Historical checkpoint re-execution/fork is deferred.

**Why:** Re-invoking downstream nodes can repeat LLM/API/interrupt/external effects; V1 first needs explicit isolated semantics.

**Consequences:** Users can inspect full history but cannot click a past point to rerun it. Resume and linked retries remain supported.

### ADR-020 — GitHub authentication

**Decision:** Prefer a least-privilege GitHub App for durable V1. Permit a server-only scoped adapter using the existing supervisor machine account/CLI for staging if that is the available credential path.

**Why:** GitHub Apps provide explicit minimal permissions and rich check integration; current infrastructure already has a machine account.

**Consequences:** Exact staging auth is resolved from non-secret facts in Prompt 03. Publication remains approval-bound and repository-allowlisted.

### ADR-021 — No Docker socket

**Decision:** Do not mount Docker socket. Collect needed health through process/service probes or a narrow exporter.

**Why:** Docker socket is effectively host-root control and exceeds a read-only health requirement.

**Consequences:** Some container metrics/status may require a small hardened collector or remain unavailable initially.

### ADR-022 — Dependency compatibility gate

**Decision:** M0/M1 choose and pin current compatible Python/Node/LangGraph/checkpointer/OpenAI/React Flow packages and test migrations, compilation, interrupts, streaming, and builds before feature expansion.

**Why:** The observed prototype versions are inventory, not guaranteed V1 constraints; these libraries evolve.

**Consequences:** Architecture specifies behavior rather than stale exact versions. Any necessary API adaptation stays inside adapters/compiler.

### ADR-023 — LangGraph owns checkpoint namespaces

**Decision:** A top-level run uses one globally unique, stable `configurable.thread_id` for checkpoint recovery. Jarvis binds that thread to an immutable run configuration snapshot and workflow version in its relational model and may include those IDs as additional configurable metadata. Jarvis does not place an application-defined partition key in `checkpoint_ns`; LangGraph owns that value for compiled subgraph addressing.

**Why:** The ADR-022 spike against LangGraph 1.2.11 showed that state inspection interprets a non-empty `checkpoint_ns` as a compiled subgraph path. An arbitrary Jarvis namespace therefore makes `aget_state` fail with a missing-subgraph error even though the checkpoint was durably written.

**Consequences:** Restart recovery and version binding remain stable without colliding with LangGraph's subgraph protocol. The workflow compiler must preserve LangGraph-generated namespaces and correlate checkpoints through `runs.langgraph_thread_id` plus immutable snapshot metadata.

### ADR-024 — M2 browser transport and artifact authorization

**Decision:** The Next server forwards the original browser authority and the narrow
authentication/CSRF/SSE headers to FastAPI through a streaming same-origin transport.
FastAPI remains the authorization authority. Incoming forwarding headers are not
trusted. The API sees the Next process as the network source, so network login
limiting is conservative across all browsers; account limits remain independent.

**Why:** Browser cookies must remain same-origin and HttpOnly, and SSE must retain
its durable reconnect cursor across the actual web/API boundary. Generic proxy
defaults can replace Host with the internal upstream authority and break the
normative exact-origin check.

**Consequences:** The integrated Chromium/PostgreSQL gate verifies the real transport.
The API and web both bound mutation bodies. CSP uses per-request script nonces;
inline styles remain allowed for React Flow/xterm presentation, while scripts do
not permit unsafe-inline or unsafe-eval. Session polling is authenticated request
activity; SSE authentication/revalidation is read-only, including denials.

Event artifact metadata is immutable from migration 0003. Content namespaces include
run/job/project scope, and downloads require an authorized visible originating
event plus size/digest verification. Global-counter locking precedes run, command,
and artifact mutations. LISTEN/NOTIFY is only a latency optimization; polling and
replay are authoritative. Unsupported schema majors, expired/future cursors and
sequence gaps yield explicit reset semantics. No retention worker or runtime job
loop is introduced in M2.

## Unresolved rework risks and required spikes

These do not block architecture, but they are explicit gates:

1. **Legacy runner idempotency/streaming:** determine whether the V1 wrapper can reliably detach, persist PID/result, stream useful facts, and cancel a process group under Worker-01 permissions. Otherwise retain concurrency one and unknown-outcome blocking.
2. **Worker worktrees:** prove OpenHands `Conversation(workspace=...)` and persistence paths behave correctly per isolated worktree. If not, use per-task cloned workspace or serialized project execution behind the same adapter.
3. **LangGraph/checkpointer API/schema:** resolved for M1 by the pinned compatibility suite. Async saver setup is idempotent, interrupt/resume survives reconnect by stable thread ID, streaming shapes are covered, LangGraph owns subgraph namespaces per ADR-023, and PostgreSQL 16 persistence is verified. Pending-write crash injection remains part of M5 runtime-node testing.
4. **Atomic domain/checkpoint boundary:** effect ledger handles cross-boundary crashes, but failure injection must verify every node's prepare/commit ordering.
5. **SSE through chosen Next.js/proxy topology:** verify no buffering, cookie/origin behavior, connection limits, and graceful deployment reconnect.
6. **Ollama capabilities/usage:** probe the deployed version/models rather than assuming structured output, tool calling, tokenizer counts, or concurrent capacity.
7. **GitHub credential form:** inspect only non-secret auth facts in staging; choose App or scoped machine-account adapter and required permissions before real tests.
8. **Reviewer context scale:** source snapshots need deterministic selection/size policy for larger repositories without losing authoritative evidence.
9. **Artifact retention/backup capacity:** set concrete quotas/retention after measuring demo and real runs; event/audit references must show expired content explicitly.
10. **Parallel integration policy:** begin with conservative concurrency and merge strategy; expand only after race/conflict tests on representative repositories.
11. **Health collection:** define the narrowest host/GPU/container telemetry mechanism available without Docker socket or privileged agent.
12. **Single-owner limitation:** any public ingress, multiple users, or delegated roles requires a new auth/tenant/threat-model decision.

## Superseding a decision

Append a new ADR with `supersedes: ADR-xxx`, record evidence, compatibility/migration/security/rollback impact, update normative docs/tests, and merge it before implementation that relies on the change. Historical entries remain intact.
