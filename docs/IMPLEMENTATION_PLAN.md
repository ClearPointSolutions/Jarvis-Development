# Jarvis V1 Dependency-Ordered Implementation Plan

Status: approved plan; no application implementation has started.

## 1. Operating rules

Each milestone begins by copying its criteria into `docs/STATUS.md` and ends only after production code, migrations, deterministic tests, affected backend/frontend tests, type/lint checks, relevant browser tests, serious-console review, diff/security review, documentation/status update, and one coherent commit. UI scaffolding or mocked buttons are not feature completion.

Shared contracts—IDs/statuses, Pydantic/TypeScript schemas, event envelope, workflow spec, failure classes, and adapter interfaces—are owned by one integration line. Parallel worktrees consume a pinned contract revision and do not independently redefine it.

Suggested branch prefix is `codex/`. Worktree names below are planning labels, not commands that this architecture turn executes.

## 2. Dependency graph

```text
M0 repository foundation
  -> M1 persistence + shared contracts
      -> [M2A auth/security API || M2B event/SSE || M2C frontend shell]
          -> M3 configuration registries + provider routing
              -> [M4A workflow compiler || M4B workflow editor]
                  -> M5 durable runtime queue/control/recovery
                      -> M6 deterministic demo vertical slice
                          -> M7 Worker-01 protocol + source workspace
                              -> M8 verification/review/Git integration
                                  -> M9 approval interrupt/resume
                                      -> [M10A Mission dashboard/chat || M10B GitHub/CI || M10C health/usage]
                                          -> M11 local hardening/full gates
                                              -> M12 real homelab integration
                                                  -> M13 side-by-side deployment
```

Only bracketed groups are pre-approved as safe parallel work after their stated shared dependency is merged. Database migration numbers, generated API clients, lockfiles, central registries, Compose, and `docs/STATUS.md` remain integration-owner files to reduce conflicts.

## 3. Milestones

### M0 — Repository and verification foundation

Dependencies: architecture commit.
Parallel: no; one owner establishes layout/contracts.

Deliver:

- backend Python 3.12 project, frontend Next.js/TypeScript project, deploy/test/docs layout;
- pinned dependency/lock strategy, formatting/lint/type/test configuration;
- required scripts `scripts/dev.sh`, `scripts/verify.sh`, `scripts/demo.sh`, and `scripts/deploy-core.sh` with safe initial behavior;
- `.env.example`, secret scan, CI skeleton, architecture dependency checks;
- generated-client/schema ownership convention and test fixtures directories.

Exit: fresh checkout installs with documented commands; empty production builds/tests/type/lint run; verify script composes gates and fails on secret canary; no runtime feature is claimed.

### M1 — Persistence and shared contracts

Dependencies: M0.
Parallel: no; freezes the first cross-stack contract revision.

Deliver:

- SQLAlchemy/Alembic foundations and dedicated schemas/roles for the logical data model;
- Pydantic domain IDs/statuses, workflow/event/failure/command schemas and generated TypeScript types;
- configuration revision/snapshot primitives, jobs/runs/tasks/attempts/commands/leases/effects/artifact metadata;
- append-only event table protections and LangGraph checkpointer bootstrap integration;
- transactional repository/service layer and clock/ID/idempotency test utilities.

Exit: migration up/down on disposable DB; constraints/race/idempotency tests; event update/delete denied; schema generation deterministic; checkpoint smoke persists by thread ID.

### M2A — Authentication and API security foundation

Dependencies: M1.
Parallel group: safe with M2B/M2C in `codex/m2-auth`; avoid event/frontend contract files.

Deliver owner bootstrap, Argon2id login, hashed server sessions, logout/revocation, CSRF/origin checks, object authorization, rate limiting, secure headers, audit events, liveness/readiness, and API error contract.

Exit: auth/CSRF/IDOR/session expiry tests pass; only liveness is anonymous; synthetic credentials absent from responses/logs.

### M2B — Event writer, projections, and SSE

Dependencies: M1.
Parallel group: safe with M2A/M2C in `codex/m2-events`; coordinates audit event call points at merge.

Deliver normalizer, schema registry, recursive redactor, artifact extraction, run/global ordering, projection watermark, `LISTEN/NOTIFY` wakeups, replay/pagination/SSE, Last-Event-ID handling, keepalive/reset, and unknown-event behavior.

Exit: concurrency/order/dedup/append-only/redaction/gap/reconnect tests; committed events stream within target; NOTIFY loss does not lose delivery.

### M2C — Frontend shell and accessibility baseline

Dependencies: M1 API schema.
Parallel group: safe with M2A/M2B in `codex/m2-web`; uses fixtures until merge.

Deliver design tokens, responsive app shell, routes, generated API client, TanStack Query setup, ephemeral UI store, login/session boundary, error/loading/empty states, sanitized Markdown, read-only xterm renderer, component/a11y/console test harness.

Exit: production build/type/lint/component tests pass; keyboard/screen-reader smoke; no secret/browser-token storage.

### M3 — Configuration registries and provider routing

Dependencies: merged M2 group.
Parallel: backend provider adapter tests and non-secret GUI forms may use separate worktrees after API schemas land; integration owner owns migrations/generated client.

Deliver worker/revision GUI/API, provider connections, OpenAI/Ollama model profiles, route/retry/permission policies, secret-reference write-only semantics, health/circuit states, deterministic routing, structured-output validation, usage/cost records, and deterministic demo provider.

Exit: configuration revision/snapshot and capability routing tests; OpenAI/Ollama contract tests with local fakes; optional provider degradation; no secret round-trip.

### M4A — Workflow specification and compiler

Dependencies: M3.
Parallel group: safe with M4B in `codex/m4-compiler`; spec/schema fixtures are pinned first.

Deliver JSON Schema/canonical hash, validation passes, static node factory registry, safe predicate evaluator, StateGraph compiler, bounded retries/iterators/fan-out/join reducers, PostgresSaver use, resolved snapshots, compile cache, and compiler contract tests.

Exit: valid fixtures compile and execute; dangling/unbounded/unsafe graphs reject; identical snapshots hash/compile identically; published versions immutable.

### M4B — Executable workflow editor

Dependencies: M3 plus pinned workflow schema.
Parallel group: safe with M4A in `codex/m4-editor`; no local execution engine.

Deliver React Flow draft editor, typed palette/forms, per-node worker/model/retry/verification/approval controls, edge predicate/fallback editing, layout persistence, server validation display, publish/version history, read-only published view.

Exit: Playwright creates/edits/validates/publishes a real spec; invalid graphs show node/edge errors; edit after publish creates a new draft/version.

### M5 — Durable orchestrator, queue, commands, and recovery

Dependencies: M4A and event/auth foundations.
Parallel: no for scheduler core; command UI can follow a frozen endpoint contract.

Deliver dedicated service, `SKIP LOCKED` claims, run leases/fencing, concurrency limits, async execution, command ordering, cooperative pause/resume/cancel, node/effect ledger middleware, backoff, failure classifier/counters, restart reconciliation, graceful drain, and projections.

Exit: two orchestrators cannot double-commit; kill/restart resumes checkpoint; command races resolve deterministically; infrastructure retry does not spend code budget; API requests remain short.

### M6 — Deterministic demo vertical slice

Dependencies: M5 and M4B.
Parallel: no; proves end-to-end architecture before remote integration.

Deliver deterministic Organizer/Architect/worker/verifier/reviewer/GitHub/health adapters, fixture clock/delays/failures, clearly marked demo events, full UI live graph/feed/task/artifact/log/retry/approval/history flow, and demo script.

Exit: demo E2E in `ACCEPTANCE_TESTS.md` passes twice identically; network-deny proves no real adapter/secret access; API/orchestrator restart and SSE reconnect preserve outcome.

### M7 — Worker-01 adapter and isolated source workspace

Dependencies: M6.
Parallel: protocol adapter and local SSH fixture may be separate; remote integration itself waits for Prompt 03 authorization.

Deliver OpenHands SSH adapter matching legacy base64/sentinel contract, pinned known hosts, capability/health validation, worker slot leases, bounded logs, structured results, cancellation/reconciliation, task branch/worktree manager, and versioned durable remote invocation wrapper plan/package.

Exit local: fake-SSH/container contract tests cover success, malformed/missing sentinel, timeout, disconnect/reconcile, duplicate start, cancellation, stale fence, traversal, and output redaction. Real Worker-01 remains a recorded staging gate.

### M8 — Verification, review, artifacts, and Git integration

Dependencies: M7.
Parallel: artifact/download UI can proceed beside backend verification/review after schemas freeze.

Deliver structured verification commands at actual root, legacy normalization event, test parsing, immutable artifact storage/download, repository snapshots, authoritative Reviewer context, review invalidation on HEAD change, per-task branches, serialized integration lease, conflict handling, and combined gates.

Exit: behavioral tests prove wrong-root prevention, cumulative state review, large-log references, parallel branch integration, conflict retry classification, and SHA-bound reviews.

### M9 — Human approval interrupt/resume

Dependencies: M5 and protected effects from M8.
Parallel: no for end-to-end security-critical path.

Deliver policy evaluation, approval request/decision API/UI, LangGraph `interrupt()`/same-thread `Command(resume=...)`, expiry/reject/cancel, digest-bound grants, re-auth option, and idempotent protected effect check.

Exit: restart while waiting then approve/reject; duplicates/stale/tampered grants reject; effect executes at most once and only after valid approval.

### M10A — Mission dashboard and Organizer chat

Dependencies: M6, M8, M9 APIs/events.
Parallel group: safe with M10B/M10C in `codex/m10-dashboard`.

Deliver conversation threads/messages, explicit objective creation, safe runtime instruction, live runtime graph, task-based progress, feed filters, node inspector, artifacts/diffs/commands/tests panels, history/playback, responsive simplified mobile, and read-only display/debug views.

Exit: Playwright/operator flows and a11y pass; no fake timers/activity; reconnect state is correct; hidden reasoning absent.

### M10B — GitHub publishing and CI

Dependencies: M8/M9.
Parallel group: safe in `codex/m10-github`.

Deliver least-privilege adapter for configured auth, repository allowlist, push/PR idempotency, approval binding, PR/CI projection and polling, disposable-repository tests, and degraded-not-configured behavior.

Exit: local fake contract passes; no push without approval; repeated request returns one PR; exact real test remains Prompt 03 gate.

### M10C — Health, usage, and operations

Dependencies: M3/M5 event paths.
Parallel group: safe in `codex/m10-ops`.

Deliver service/worker/provider/host health collectors without Docker socket, queue/lease/stall view, token/cost aggregation with provenance, retention jobs, and redacted incident export.

Exit: health transition/retention/unknown-cost tests; optional outage cannot break core; UI distinguishes stale/unknown/down.

### M11 — Local hardening and whole-project gate

Dependencies: all M10 branches merged.
Parallel: audit tasks may run in parallel; fixes merge through one owner.

Deliver production Compose, migrations/backup-restore test, performance/concurrency tests, security threat cases, dependency/image scans, documentation/runbooks, fresh-checkout reproducibility, browser console review, and complete `scripts/verify.sh`.

Exit: every non-homelab acceptance test passes; demo and production build pass; status lists exact commands/results and only real integration/deployment gates remain.

### M12 — Real homelab integration (Prompt 03)

Dependencies: M11 and explicit integration authorization.
Parallel: no uncoordinated remote mutation.

Validate non-secret facts, Worker-01 runner/wrapper, real root verification, heartbeats/failures, Ollama and optional OpenAI health, checkpoint restart, SSE facts, harmless approval, and GitHub against a disposable private repository. Never mutate `/opt/jarvis`.

Exit: the complete real E2E passes and status records evidence/known limits. V1 is not promoted.

### M13 — Side-by-side deployment (Prompt 04)

Dependencies: M12 and explicit deployment authorization.

Deploy under `/opt/jarvis-v1` with dedicated names/data/secrets, run migration/health/demo/real E2E/restart tests, record URLs/services/rollback, and leave `/opt/jarvis` untouched. No DNS switch/promotion.

## 4. Integration discipline for parallel worktrees

1. Integration owner publishes a contract commit and assigns non-overlapping path ownership.
2. Each branch rebases on that commit, adds tests, and reports migration/schema impact.
3. Central migrations/generated types/lockfiles are regenerated once by the integration owner.
4. Merge backend contract/provider before dependent UI; regenerate client; run cross-contract tests.
5. Run `scripts/verify.sh` after the group merge, not only branch-local tests.
6. Delete/retire worktrees only after commit integration and never with broad destructive commands.

## 5. Critical path and rework controls

The critical path is data/event contracts -> compiler -> durable orchestrator -> demo proof -> real worker/Git/review -> approvals -> full UI/integrations -> hardening -> homelab -> deploy. Building the dashboard before the event/runtime contract is proven risks a fake second workflow engine and is intentionally avoided.

Before M7, spike the installed LangGraph/checkpointer APIs and legacy worker observability/idempotency in tests. Before M10B, decide available GitHub authentication from non-secret staging facts. Any change to event/workflow major schemas requires an explicit decision record and migration/upcaster plan.
