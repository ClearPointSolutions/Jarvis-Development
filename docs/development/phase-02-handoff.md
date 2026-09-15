# Phase 2 handoff

## Identity

- Base SHA: `5b7a5caefba9d9acccd21085c2232c515ed31dcc`
- Branch: `phase/02-bounded-autonomy`
- Validated implementation SHA: `b83b69c7ebf320a93e1c3055e464836dda3bd801`
- Draft PR: [#10](https://github.com/ClearPointSolutions/Jarvis-Development/pull/10)
- Implementation CI: [verify run 34921650915](https://github.com/ClearPointSolutions/Jarvis-Development/actions/runs/34921650915), passed
- Final branch-tip CI: use the draft PR check attached to the current tip; evidence is
  valid only when its checked SHA is the current branch SHA

## IMPLEMENTED

- Mission lifecycle now distinguishes active, idle, capacity/approval waiting,
  blocked, paused, cancelling/cancelled, completed, and archived. Autonomous
  continuation is explicit and off by default.
- Versioned global/team/mission controls gate manager inference and external
  worker dispatch. Mission controls expose pause/resume, drain, safe-point
  instruction, and cancellation; active work receives the existing ordered,
  audited run commands and retains its immutable directive snapshot.
- Worker saturation is a durable waiting state. Slot acquisition precedes attempt
  activation, waits with bounded backoff under the same logical request/attempt/
  effect identity, renews held leases, and does not classify saturation as bad
  configuration or spend a semantic coding attempt. Expiry is never treated as
  proof that a remote process terminated.
- `POST /api/v1/runs/{run_id}/reconciliation` is owner/CSRF/version/idempotency
  protected and audited. It can only schedule inspection of an existing
  dispatched/running/cancel-requested/unknown effect identity; it cannot assert
  success, replace an invocation, or erase ambiguity.
- Transactional maximum-liability reservations cover UTC-aligned windows, calls,
  input/output tokens, active jobs, wall time, iterations, new work items, and
  compatible currency/price units at all three scopes. Known results reconcile
  to actual usage; unknown outcomes keep their maximum liability. The old
  `bytes/3` estimate was replaced by a fail-closed bound that charges every UTF-8
  request/schema/tool byte plus explicit envelope overhead.
- The legacy worker's process runtime/output/result bounds continue to enforce
  unpaid local compute limits. Because worker-managed model credentials cannot
  yet be proven to pass through a metered gateway, paid unattended mode is
  deliberately unavailable in the API and UI; no unknown use is shown as zero
  and no paid fallback exists.
- User direction, accepted completion, classified terminal failure, approval
  projection, and scheduled deadlines use durable deduplicated wakeups. A wakeup
  freezes directive/team/source cursor and accepted target/source provenance,
  materializes at most one stable management turn, and never fires merely because
  polling or idle time passed. Decisions create bounded work transactionally;
  deterministic job/run identities make enqueue recovery convergent.
- One direction can create DEV-001, project its accepted result into one wakeup
  despite 50 repeated deliveries, automatically enqueue DEV-002 from the accepted
  source, and complete after its accepted result. Budget races, currency mismatch,
  admission-before-inference, idle-no-inference, existing-identity reconciliation,
  and browser management-state paths have focused regressions.
- The mission detail UI shows governing and active directive versions, next action
  and basis, waiting/user-action reason, admission scope, reservations/actuals,
  unknown liability, durable wakeups, and the paid-unattended limitation.

## Changed files

```text
api/app/jarvis_api/auth/routes.py
api/app/jarvis_api/missions.py
api/app/jarvis_api/runtime.py
api/migrations/versions/0013_phase_02_bounded_autonomy.py
docs/ARCHITECTURE.md
docs/DATA_MODEL.md
docs/EVENT_SCHEMA.md
docs/STATUS.md
docs/development/phase-02-handoff.md
orchestrator/app/jarvis_orchestrator/mission_resources.py
orchestrator/app/jarvis_orchestrator/missions.py
orchestrator/app/jarvis_orchestrator/providers/budget.py
orchestrator/app/jarvis_orchestrator/runtime/composition.py
orchestrator/app/jarvis_orchestrator/workers/leases.py
orchestrator/app/jarvis_orchestrator/workers/runtime.py
packages/contracts/generated/*
packages/contracts/src/jarvis_contracts/event_registry.py
packages/contracts/src/jarvis_contracts/generate.py
packages/contracts/src/jarvis_contracts/missions.py
packages/contracts/src/jarvis_contracts/runtime_api.py
packages/persistence/src/jarvis_persistence/models.py
tests/integration/test_m7_workers.py
tests/integration/test_phase_02_bounded_autonomy.py
tests/unit/test_phase_02_bounded_autonomy.py
web/src/components/mission-detail.tsx
web/src/components/missions-page.tsx
web/src/lib/api/missions.ts
web/tests/e2e/phase-01-missions.spec.ts
```

No Compose topology or secret/environment setting was required. Readiness is
pinned to migration `0013`; normal side-by-side deployment migration behavior is
unchanged and `/opt/jarvis` was not touched.

## LOCALLY VERIFIED

- Ruff formatting/lint and mypy passed: `305` formatted Python files and `249`
  typed source files.
- Focused Python regressions passed: `51 passed`; the migration pin plus Phase 2
  contract guards passed: `4 passed`.
- Generated Pydantic schema, integrated OpenAPI, and both TypeScript contract
  outputs report current.
- The complete non-PostgreSQL repository gate executed with repository-local temp
  storage: `687 passed, 10 skipped, 200 deselected`. `scripts/verify.sh` then
  stopped at the unchanged coverage requirement: 52.60% versus 80%. This is a
  failed whole-project gate caused by excluding the database integration suite,
  not a pass and not a weakened threshold.
- Phase 2 PostgreSQL tests collect successfully but report `5 skipped` because
  `TEST_DATABASE_URL` is unavailable. Docker does not respond on this workstation,
  so migration, transaction-race, and database crash/recovery evidence is not
  inferred locally.
- Prettier, ESLint, TypeScript, and contract checks passed. Vitest passed `26`
  suites / `54` tests using one worker. The Next.js production build passed with
  one build worker and contains the mission routes. `npm audit --audit-level=high`
  reported `0 vulnerabilities`.
- Focused Phase 1/2 Chromium acceptance passed `2 passed`. The full mocked browser
  suite passed `7 passed, 6 skipped` with one worker; the skips require the absent
  database runner. An initial eight-worker browser run exhausted this host's
  memory and is not counted as a product failure or a pass.

## CI VERIFIED

The exact implementation commit `b83b69c7ebf320a93e1c3055e464836dda3bd801`
passed repository `verify` run
[`34921650915`](https://github.com/ClearPointSolutions/Jarvis-Development/actions/runs/34921650915).
That run covered PostgreSQL 16 migration round trip/drift/privileges, the full
Python suite (`893 passed, 4 live-model skipped`) at the unchanged coverage
threshold, generated-contract drift, frontend checks/build/audit, the mandatory
worker protocol fixture, and database-backed browser/demo paths. The draft PR's
current-tip check is the source of truth after this handoff-only documentation
commit.

## LIVE VERIFIED

UNVERIFIED. No authorized Jarvis-Core/Jarvis-Worker staging shell was used. No
deployment, real remote invocation, paid provider call, or soak is claimed.

## Remaining gates and exact next action

After the draft PR check is green on the current branch tip, use an explicitly
authorized V1 staging target to migrate `/opt/jarvis-v1`, run an unpaid local
two-job autonomous mission, exercise capacity wait and pause/reconciliation
during a controlled outage, restart API/orchestrator, and retain the
run/event/usage evidence. Leave `/opt/jarvis` and the legacy worker environment
untouched. Do not merge or deploy from this handoff.
