# Jarvis V1 Status

Last updated: 2026-09-07
Current phase: Architecture (Prompt 01)
Overall state: architecture complete; application implementation not started

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

No V1 backend, frontend, database migration, Compose service, deployment, or remote change exists yet. This is intentional: Prompt 01 stops after the documentation commit.

The Git worktree was clean before documentation authoring. Reference/legacy files were read only and are not modified by this milestone.

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

Application test/build commands were not run because this repository still contains no V1 application and Prompt 01 forbids beginning implementation. Executable JSON/Markdown/Git validation is proportionate to this documentation-only milestone.

## Next milestone

After human review of the architecture commit, begin M0 in `docs/IMPLEMENTATION_PLAN.md` under Prompt 02. First actions:

1. put M0 criteria and active state here;
2. establish backend/frontend/repository verification scaffolding and lock strategy;
3. select/pin compatible dependency versions with focused LangGraph/Postgres interrupt/checkpoint spikes;
4. do not access or deploy to the real homelab during local implementation.

## Open gates and risks

The unresolved spikes in `docs/DECISIONS.md` are implementation gates, especially legacy runner idempotency/worktree compatibility, current LangGraph/checkpointer compatibility, SSE proxy behavior, deployed Ollama capabilities, GitHub credential form, and safe narrow health collection. Real Worker-01, GitHub, and restart tests remain Prompt 03 gates; side-by-side deployment remains Prompt 04.
