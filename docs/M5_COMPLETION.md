# M5 — Durable orchestrator, controls and recovery

Status: **LOCAL GATES COMPLETE / NOT READY FOR M6**. Exact-commit GitHub CI
is the remaining completion gate.

Base: `4367599eeed256d345296dff8f85c52cdc87d38a` (verified origin/main).
M4 verify: [34171942359](https://github.com/ClearPointSolutions/Jarvis-Development/actions/runs/34171942359).
Branch: `codex/m5-durable-orchestrator`. Final SHA and CI evidence are pending.
Prerequisite/status commit: `e6ab1d7`.

## Runtime and database

Migration **0006** adds queue priority, event mode, bounded runtime control
metadata, current node/result summary, lease heartbeat and the claim index. It
grants the API INSERT on immutable run snapshots. Migrations 0001–0005 and all
legacy reference files remain unchanged.

Run `python -m jarvis_orchestrator.main` separately from the API, using the
orchestrator database role. Migrations/bootstrap run with the migration role;
the service does not perform schema management. Bootstrap native saver tables with
`python -m jarvis_persistence.checkpoints`; this grants table DML to the dedicated
orchestrator role. The API retains no checkpoint-table access. Shared connection
URL conversion preserves PostgreSQL role options and credential encoding. There is no public orchestrator
listener, shell endpoint, Redis, worker connection or provider call. The browser
runner starts the actual service against a disposable loopback database.

Configuration (environment prefix `JARVIS_ORCHESTRATOR_`):

| Setting | Default | Meaning |
| --- | --- | --- |
| `MAX_CONCURRENCY` | 2 | Maximum active run tasks per service instance, bounded 1–64 |
| `GLOBAL_CONCURRENCY` | 2 | Cluster-wide active lease cap, bounded 1–256; configure identically on all instances |
| `LEASE_SECONDS` | 30 | Lease duration, bounded 5–600 seconds |
| `POLL_SECONDS` | 0.2 | Command/queue/renewal polling, bounded 0.01–1 second |
| `GRACE_SECONDS` | 10 | Drain deadline, bounded 0–300 seconds |

Each process start gets a fresh instance identity. Claims use PostgreSQL
`FOR UPDATE SKIP LOCKED`: descending priority, then ascending `claimable_at`,
creation timestamp and UUID. Live leases exclude runs. Expired ownership gets
a strictly greater generation; lease history is retained. Commands are processed
even when execution capacity is saturated. Database polling failures retry
without charging any run retry budget.

M2's global-event-counter-before-run lock ordering is preserved. Executor
transactions lock and validate the run/current lease and recheck expiry before
commit. Native PostgresSaver checkpoint, blob and pending-write operations take
the same run lock and verify owner/generation/expiry inside their own transaction.
The pinned saver `_cursor` override is covered by a compatibility test and must
be reviewed when upgrading LangGraph/checkpoint-postgres. Stale executor results
are discarded and logged with run/generation only; they cannot update projections
or checkpoints. No arbitrary exception text is exported.

## Execution, effects and recovery

The API validates owner/project, published workflow and current immutable
configuration references, persists job/run/snapshot/stable thread and events,
then returns 202. Execution recompiles exactly that workflow and verifies snapshot
hashes. LangGraph controls routing and checkpoints; SQL projections are query
surfaces, not a second workflow engine.

Node middleware persists execution identities, queued/start/end state, times,
safe bounded results, classified failures and correlated events. Parallel branch
identities are included in the replay key; execution numbers increase per workflow
node. Existing task/attempt identities are attached where present; task planning
is not introduced in M5. Node and command projections are owner-authorized and paginated.

External nodes use one injected `EffectAdapter` interface: inspect, dispatch and
idempotent cancellation. Effect preparation records intent and a stable identity
before dispatch. On restart the ledger reuses completed redacted results, inspects
live identities, or dispatches confirmed-absent idempotent work. Unknown outcomes
of non-idempotent operations explicitly block. A dispatch-intent crash is treated
conservatively if absence cannot prove safety. This is **not universal exactly-once
execution**: duplicate transport attempts require adapter idempotency/reconciliation.

Recovery registers a new instance, claims expired nonterminal work with a new
generation, emits recovering events, recompiles the exact snapshot, inspects the
ledger and resumes the original PostgresSaver thread. Result-before-checkpoint and
checkpoint-before-projection gaps are replayed safely. Recovery does not charge
semantic retry counters.

SIGINT/SIGTERM marks the instance draining and stops claims. In-flight tasks retain
renewed leases during the grace period. Tasks exceeding the deadline are cancelled
locally; their durable leases expire and normal recovery handles external outcomes.
No uncontrolled OS worker processes are killed.

## Commands and failure policy

Commands are durable, idempotent and optimistically versioned. The orchestrator
applies them in sequence and records applied/rejected/superseded dispositions.
Cancel dominates pending pause/resume, and terminal runs cannot resume. Retry of
a failed/blocked run creates a linked run with a new thread and the same immutable
configuration, preserving the original history.

Pause records intent immediately; active effects continue until a safe boundary.
LangGraph `interrupt` persists suspension, the run becomes paused and capacity is
released. Resume uses the same thread with a matching durable interrupt identity.
Pausing an already suspended retry keeps that checkpoint paused without executing
another node; resume retains the original retry deadline. The retry regression
asserts the unchanged thread/deadline and no additional effect dispatch while paused.
Cancel asks controlled adapters to cancel and discards racing results. Recovery
reconciles pending cancellations before declaring the run cancelled.

Instructions are bounded and delivered as data only to nodes whose published
`accepts_runtime_instructions` policy opts in. The effect intent freezes the
instruction set so restart does not change an already prepared invocation.
The objective is supplied as runtime input, never executable workflow metadata.

M1/M3 failure classes determine exactly one budget. Unknown, configuration and
security failures block without spending developer retries. Retry counts mean
retries after the initial attempt. M3 backoff/jitter determines a persisted
`claimable_at`/retry deadline; LangGraph suspends during the wait. Pause/resume
preserves that deadline. Exhaustion emits an event and follows the validated M4
failure/block route. Model retries can fail over only to immutable declared
candidates when both retry and route policy permit the failure class. No live
model/provider call occurs in M5; deterministic adapters receive selected identities.

## API and UI

All mutations require authentication, owner authorization, CSRF/origin checks and
idempotency. Commands additionally require the expected run version. Unowned UUIDs
return 404. Published versions are required; API handlers never invoke a graph.

| Route | Behavior |
| --- | --- |
| `GET/POST /api/v1/projects` | Owner project list/create |
| `POST /api/v1/projects/{id}/jobs` | Durable job/run enqueue, 202 |
| `GET /api/v1/jobs`, `/jobs/{id}` | Job projections |
| `GET /api/v1/runs`, `/runs/{id}` | Actual/desired state, recovery, activity and event watermarks |
| `GET /api/v1/runs/{id}/nodes` | Node projection history |
| `GET/POST /api/v1/runs/{id}/commands` | Command history/enqueue |
| Existing run events/snapshot/stream routes | Durable replay and authenticated SSE |

Runs UI creates projects, starts published workflows, shows history and exposes
real pause/resume/cancel/retry/instruction commands. Controls display actual and
desired state separately, recovery, block summaries and command acknowledgement.
The existing event feed continues to replay durable events.

## Acceptance evidence

- RUN-001/002: concurrent claims, deterministic priority, locked-row skip, renewal,
  expiry/reassignment, stale node/projection and native checkpoint writes.
- RUN-003: authenticated durable 202 enqueue, idempotency and optimistic commands.
- RUN-004/005: persisted pause, restart/resume same thread, cancel command dominance,
  live adapter cancellation and no terminal resurrection.
- RUN-006/007: effect crash windows and unknown non-idempotent outcomes.
- RUN-008: active adapter continues through API recreation; event replay is gap-free.
- RUN-009: linked whole-run retry preserves the original thread/history.
- FAIL-001–007: isolated code/infrastructure/provider/review/git-conflict budgets,
  exhaustion, failover and non-transient/unknown blocking.
- Fault hooks: before prepare; after prepare; after dispatch; after result; after
  checkpoint; during pause; during cancellation; during retry scheduling.
- 100-run ordered-claim test; bounded two-instance execution; survivor recovery;
  graceful drain; instruction opt-in and objective delivery.

**570 Python tests pass**, including migration roundtrip, metadata drift and role
checks; combined line/branch coverage is **88.50%** (80% threshold unchanged).
Branch-only coverage is **78.18%** (1,523 / 1,948 branches); 6,451 / 7,062 lines are covered.
Frontend: **47 passed**, including a bounded fresh-version command retry that
preserves the idempotency key. Clean npm install/audit: **zero vulnerabilities**.
Python/frontend strict types and lint, generated contracts and secret scan pass.
Production build and **9 Playwright tests pass**, with zero desktop/mobile axe
violations or serious console errors. Browser API logs and frontend bundles contain
no secret canaries; desktop paused and mobile cancelled screenshots were reviewed.
The complete PostgreSQL-enabled **`scripts/verify.sh` passes** on the final source,
including the backoff pause regression, all Python/frontend/browser gates and
security checks. Diff and visual review are complete. Exact-commit GitHub CI
remains **pending**. No quality or security threshold was weakened.

## Scope and limitations

Adapters are deterministic injected test fixtures; real SSH/OpenHands, OpenAI,
Ollama and GitHub publication are not bound. M6's full demo experience is not built.
External timeouts with an unproven side effect fail closed for reconciliation.
Instruction text is never interpreted as commands, approvals or workflow rewrites.
Concurrency is bounded per instance and globally using live leases under the claim lock; worker capacity is a later
integration. UI history requests are bounded and use the existing polling/SSE
approach; the final Mission dashboard remains M10.

No homelab system was contacted. No deployment occurred. `/opt/jarvis` and
`/opt/jarvis-v1` were not touched. M6 was not started. Main is not merged.
