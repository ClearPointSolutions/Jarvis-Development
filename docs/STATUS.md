# Jarvis V1 Status

Last updated: 2026-09-07
Current phase: M2 — approved parallel foundation group in progress
Overall state: architecture approved; M0 and M1 complete; M2A/M2B/M2C active; M3 not started

## Active M2 parallel-group criteria

Integration base: frozen M1 contract commit `76d41c8c6193e7d541ca24e6fbf84dee5693e8c2`.

### M2A — Authentication and API Security

- [ ] Provide explicit one-time local owner bootstrap and Argon2id password verification.
- [ ] Persist only hashed opaque sessions with idle/absolute expiry, rotation, logout, and revocation.
- [ ] Enforce same-origin/CSRF protection, object authorization, login rate limiting, secure cookies/headers, and normalized API errors.
- [ ] Emit redacted authentication/session audit events and expose only anonymous liveness.
- [ ] Pass deterministic AUTH-001 through AUTH-005 tests and security boundary checks.

### M2B — Event Writer, Projections, and SSE

- [ ] Normalize and validate registered event payloads, recursively redact secrets, and extract oversized content to authorized artifact metadata/storage.
- [ ] Preserve globally commit-safe and per-run ordering, deduplication, append-only storage, and transactional projection watermarks.
- [ ] Implement authorized replay/pagination and SSE with `Last-Event-ID`, keepalive, reset semantics, and LISTEN/NOTIFY used only as a wakeup.
- [ ] Render unknown allowed event types safely and reject unsupported schema majors explicitly.
- [ ] Pass deterministic EVT-001 through EVT-008 concurrency, loss, replay, redaction, and boundary tests.

### M2C — Frontend Shell and Accessibility Baseline

- [ ] Build the responsive mission-control shell and required route skeletons using shared design tokens.
- [ ] Establish generated API-client consumption, TanStack Query server state, ephemeral Zustand state, and login/session boundaries without browser token storage.
- [ ] Provide honest loading/error/empty/demo states, sanitized Markdown, and a read-only terminal renderer.
- [ ] Pass production build, type/lint/component, keyboard, screen-reader, automated accessibility, and serious-console-error checks.

### Integration-owner gates

- [ ] Own all shared migrations/models, generated Python/TypeScript contracts, root lockfiles, central registries, shared Compose, and this status ledger.
- [ ] Merge only milestone branches that pass their focused gates, then run the full repository verification suite from the merged branch.
- [ ] Inspect the final diff and secret scan, record branch hashes/merge order/findings/evidence, and stop before M3.

## M1 completion criteria

- [x] Establish SQLAlchemy 2.x and Alembic with `control`, `event_store`, and LangGraph-owned schemas plus least-privilege logical roles.
- [x] Implement authoritative Pydantic IDs/statuses and versioned workflow, event, failure, command, configuration, snapshot, queue, lease, effect, and artifact contracts.
- [x] Generate deterministic TypeScript types and JSON Schema from the Python authority and enforce drift checks.
- [x] Implement the M1 relational model and transactional repositories with deterministic clock, ID, and idempotency utilities.
- [x] Enforce append-only event storage and ordering/deduplication invariants in PostgreSQL.
- [x] Bootstrap LangGraph Postgres checkpointing and prove stable-thread persistence, streaming APIs, and durable interrupt/resume behavior.
- [x] Prove PostgreSQL 16, OpenAI SDK, and React Flow compatibility for the selected pins required by ADR-022.
- [x] Pass migration up/down, constraints/race/idempotency, unit, integration, frontend, build, browser, audit, and secret gates.
- [x] Review M1; the coherent commit immediately following this status update is the milestone boundary. Stop before M2A/M2B/M2C.

## Active M0 criteria

- [x] Establish the backend, orchestrator, frontend, shared-contract, deployment, script, and test layout.
- [x] Pin a Python 3.12 and Node-compatible dependency set with reproducible lock files.
- [x] Establish formatting, linting, type checking, unit/component testing, Playwright, and production-build gates.
- [x] Add safe `scripts/dev.sh`, `scripts/demo.sh`, `scripts/verify.sh`, and `scripts/deploy-core.sh` behavior.
- [x] Add a names/safe-examples-only `.env.example` and deterministic secret scanning with a failing canary test.
- [x] Add CI using PostgreSQL 16 and the same verification entrypoint.
- [x] Prove a fresh local install can execute the empty/scaffold quality gates.
- [x] Review M0; commit is the milestone boundary immediately following this status update.

M3 and all remote staging/deployment work are explicitly out of scope for this turn.

## Architecture milestone criteria

- [x] Read `AGENTS.md`, the complete base idea, current prototype description, all legacy reference files, and Prompt 01.
- [x] Inspect repository/tracked files, downstream prompt expectations, legacy LangGraph graph, Postgres checkpoint usage, SSH worker invocation, verification/reviewer behavior, and legacy Compose boundary.
- [x] Define V1 product scope and measurable quality requirements.
- [x] Define process/component architecture and source-of-truth boundaries.
- [x] Define durable relational data model, immutable configuration/snapshots, queue/leases/effects, and event storage.
- [x] Define normalized versioned event envelope, taxonomy, ordering, redaction, replay, and SSE delivery.
- [x] Define the exact visual-workflow schema validation and LangGraph compilation process.
- [x] Define parallel-job/task/repository races, worker leases/concurrency/fencing, and command ordering.
- [x] Define process-restart/checkpoint/effect recovery.
- [x] Define failure classification and class-specific retry semantics.
- [x] Define generic worker protocol and the existing Worker-01 OpenHands SSH compatibility path.
- [x] Define first-class OpenAI/Ollama provider abstraction, routing, health, and accounting.
- [x] Define authentication, authorization, approval, secret, network, worker, and deployment security boundaries.
- [x] Define side-by-side deployment/migration/backup/rollback with `/opt/jarvis` preserved.
- [x] Trace at least three complete workflows, including retry/restart, infrastructure recovery, and parallel integration race.
- [x] Define deterministic demo and exact 15-step real E2E acceptance tests.
- [x] Produce a dependency-ordered implementation plan with safe parallel worktree groups.
- [x] Record architecture decisions and unresolved rework risks.
- [x] Validate documentation structure/links/whitespace and review the final diff.
- [x] Commit the architecture documentation coherently as the final action of Prompt 01.

## Architecture deliverables

- `docs/PRODUCT_SPEC_V1.md`
- `docs/ARCHITECTURE.md`
- `docs/DATA_MODEL.md`
- `docs/EVENT_SCHEMA.md`
- `docs/WORKFLOW_RUNTIME.md`
- `docs/WORKER_PROTOCOL.md`
- `docs/PROVIDER_ROUTING.md`
- `docs/SECURITY_MODEL.md`
- `docs/DEPLOYMENT_PLAN.md`
- `docs/IMPLEMENTATION_PLAN.md`
- `docs/ACCEPTANCE_TESTS.md`
- `docs/DECISIONS.md`
- `docs/STATUS.md`

## Prototype findings carried forward

- The legacy CLI loop is proven for Architect -> Developer -> deterministic verification -> independent Reviewer -> retry/advance.
- Verification must execute at the real repository root; invented absolute paths are invalid.
- Reviewer evidence must represent authoritative cumulative repository state, with latest diff only supplemental.
- Worker execution must be adapter-based; initial compatibility is the configured base64/sentinel OpenHands runner on Worker-01.
- Large output stays outside graph state.
- The fixed seven-attempt loop becomes versioned class-specific retry policy.
- The synchronous SSH call/shared workspace are not restart/concurrency safe; V1 adds invocation identity, reconciliation, fencing, and worktree/exclusive-resource rules.
- Legacy PostgreSQL/container/application remain isolated and untouched.

## Current implementation state

M0 provides the Python 3.12 API/orchestrator package layout, minimal Next.js shell,
exact Python/npm locks, safe scripts, CI, secret scanning, and local PostgreSQL
Compose definition. M1 adds authoritative frozen Pydantic contracts and generated
JSON Schema/TypeScript, 20 `control` tables, three append-only/ordering
`event_store` tables, LangGraph-owned checkpoint tables, logical roles, an Alembic
baseline, transactional event/command/idempotency/effect/lease repositories, and
deterministic test utilities. No M2 API, SSE, authentication, frontend shell feature,
deployment, or remote change has begun. Reference and legacy files remain unmodified.

## Validation evidence

Architecture validation on 2026-09-07:

- Required-deliverable validator: 13/13 files present.
- Markdown structure validator: code fences balanced; deployment headings ordered 1 through 13.
- Embedded contract validation: workflow JSON parsed with 10 nodes and 14 edges; all event and worker JSON examples parsed.
- Requirement validator: exact 15 real E2E steps and three full workflow traces present.
- Local-reference validator: all 20 backtick document references resolved.
- `rg -n -g '*.md' "[ \\t]+$" docs`: no trailing whitespace after cleanup.
- `git diff --cached --check`: passed.
- Staged-scope review: exactly the 13 required new architecture documents; no application or reference/legacy file is modified.
- Synthetic secret-pattern review of staged content: no private-key block, live-token prefix, credential assignment, or bearer value found.

M0 validation on 2026-09-07:

- Python 3.12.14 lock installation and `pip check`: passed.
- `npm install` from the exact package manifest and `npm audit --audit-level=high`: passed with zero vulnerabilities after selecting patched Vite/Vitest releases.
- `scripts/verify.sh`: passed (Ruff format/lint, strict mypy, 5 pytest tests at 88.46% coverage, frontend Prettier/ESLint/TypeScript/Vitest, Next production build, and one Chromium Playwright smoke test).
- Secret scanner self-test detected its synthetic private-key canary; repository scan was clean.
- All shell scripts parse; `demo.sh` and `deploy-core.sh` refuse safely with exit code 2.
- PostgreSQL integration is intentionally not active until M1 adds its migration and deterministic tests.

M1 validation on 2026-09-07:

- Python 3.12.14 installed `requirements.lock`; `pip check` reported no broken requirements.
- Local `postgres:16.10-bookworm` reported PostgreSQL 16.10. Alembic downgrade/upgrade and metadata-drift check passed while excluding the package-owned `langgraph` schema.
- `pytest --cov`: 25 passed with 92.99% branch coverage. Tests cover constraints, immutable revisions/snapshots/published workflows, append-only events, concurrent gap-free ordering, event/command/effect/request idempotency conflicts, command sequencing/optimistic versions, lease expiry/fencing, logical-role permissions, and deterministic clocks/IDs.
- LangGraph 1.2.11 compiled/invoked and produced `astream(..., stream_mode="updates")` plus `astream_events(..., version="v2")`; `langgraph-checkpoint-postgres` 3.1.2 setup was idempotent and an interrupt survived saver closure/reopen before same-thread `Command(resume=...)` completion.
- OpenAI 3.8.0 Responses API types/client succeeded against an in-process `httpx2` 2.12.0 mock transport with no external request.
- React 19.2.8 and React Flow 12.11.6 initialized typed nodes/edge in Vitest; all three frontend tests, TypeScript, ESLint, Prettier, Next 16.3.4 production build, and the Chromium Playwright smoke/console check passed.
- JSON Schema and TypeScript generation checks passed byte-for-byte. `npm audit --audit-level=high` reported zero vulnerabilities.
- `scripts/verify.sh` passed every enabled M0/M1 gate with the disposable database configured; the secret canary was detected and the repository scan was clean.
- ADR-022 exposed one runtime contract correction: arbitrary non-empty `checkpoint_ns` is interpreted as a LangGraph subgraph path. ADR-023 reserves that field for LangGraph and uses the stable run thread ID plus immutable snapshot metadata for Jarvis correlation.
- No homelab address was contacted, no SSH was attempted, and no deployment was run.

During Prompt 01, application test/build commands were not run because the
repository contained no V1 application and that prompt forbade implementation.
Executable JSON/Markdown/Git validation was proportionate to that earlier
documentation-only milestone; the M0 application gates are recorded above.

## Next milestone

After the M1 commit, the contracts are stable enough to begin the approved parallel
M2A authentication/security, M2B event/SSE, and M2C frontend-shell group from the
same pinned contract revision. M2 remains explicitly unstarted in this turn.

## Open gates and risks

The unresolved spikes in `docs/DECISIONS.md` remain implementation gates, especially legacy runner idempotency/worktree compatibility, SSE proxy behavior, deployed Ollama capabilities, GitHub credential form, and safe narrow health collection. LangGraph/checkpointer API/schema compatibility is resolved for M1 by ADR-023 and the pinned tests; pending-write crash injection remains an M5 runtime-node concern. Real Worker-01, GitHub, and restart tests remain Prompt 03 gates; side-by-side deployment remains Prompt 04.
