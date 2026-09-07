# Jarvis V1 Status

Last updated: 2026-09-07
Current phase: M0 — Repository and verification foundation complete
Overall state: architecture approved; M0 complete; M1 queued; M2 not started

## Active M0 criteria

- [x] Establish the backend, orchestrator, frontend, shared-contract, deployment, script, and test layout.
- [x] Pin a Python 3.12 and Node-compatible dependency set with reproducible lock files.
- [x] Establish formatting, linting, type checking, unit/component testing, Playwright, and production-build gates.
- [x] Add safe `scripts/dev.sh`, `scripts/demo.sh`, `scripts/verify.sh`, and `scripts/deploy-core.sh` behavior.
- [x] Add a names/safe-examples-only `.env.example` and deterministic secret scanning with a failing canary test.
- [x] Add CI using PostgreSQL 16 and the same verification entrypoint.
- [x] Prove a fresh local install can execute the empty/scaffold quality gates.
- [x] Review M0; commit is the milestone boundary immediately following this status update.

M1 criteria will be activated only after the M0 commit. M2A, M2B, and M2C are explicitly out of scope for this turn.

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

M0 provides importable Python 3.12 API/orchestrator/contract packages, a minimal
Next.js application, exact Python and npm locks, an isolated PostgreSQL 16 local
Compose definition, safe scripts, CI, and deterministic verification. No database
model, migration, production runtime behavior, deployment, or remote change exists
yet. Reference and legacy files remain unmodified.

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

During Prompt 01, application test/build commands were not run because the
repository contained no V1 application and that prompt forbade implementation.
Executable JSON/Markdown/Git validation was proportionate to that earlier
documentation-only milestone; the M0 application gates are recorded above.

## Next milestone

Begin M1 only after the coherent M0 commit. Activate the M1 criteria in this file,
then implement the durable contracts, PostgreSQL/Alembic foundation, shared-contract
generation, and ADR-022 compatibility spikes. Do not begin M2 or access/deploy to
the real homelab.

## Open gates and risks

The unresolved spikes in `docs/DECISIONS.md` are implementation gates, especially legacy runner idempotency/worktree compatibility, current LangGraph/checkpointer compatibility, SSE proxy behavior, deployed Ollama capabilities, GitHub credential form, and safe narrow health collection. Real Worker-01, GitHub, and restart tests remain Prompt 03 gates; side-by-side deployment remains Prompt 04.
