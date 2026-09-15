# Phase 4 handoff

## Identity

- Base SHA: `3d3c7c564f05ccf255e1879a9749a513c9dee14c`
- Branch: `phase/04-teams-and-worker-pools`
- Final SHA: use `git rev-parse HEAD` after the handoff commit
- CI identity: UNVERIFIED until the exact branch tip is pushed and checked
- Live identity: UNVERIFIED; no authorized V1 staging target was contacted

## IMPLEMENTED

- Registry contracts now support customizable team members and `worker_pool`
  revisions. Members bind role, model route, allowed tools, permission policy,
  permitted worker pools and independent execute/review responsibilities. Team
  budgets reserve management/review admission and bound active assignments,
  execution time and inference calls. Protected reviewers cannot also execute.
- Worker revisions record stable physical-resource identity, permitted projects,
  supported execution profiles and observed wrapper/build identity. Pool writes
  validate every worker revision and capability requirement. Existing legacy
  workers remain one slot each.
- Mission creation freezes the concrete eligible-worker revision list and its
  hash. Mission team edits create a new immutable version used only by future
  assignments. Existing turns/work items continue to reference their original
  team version.
- Mission admission now permits multiple isolated jobs up to the lower of the
  mission and frozen-team limits. Least-recently-served mission ordering is
  durable, and each admitted job reserves bounded execution time. Team inference
  call budgets are checked under a PostgreSQL advisory lock across manager turns
  and run model nodes before the unknown-call intent is persisted.
- Real composition selects a worker deterministically from that immutable pool
  using current enabled/archive vetoes, fresh health, project/profile/capability
  eligibility and physical-resource load. Atomic leases are keyed by stable
  physical resource, so duplicate configuration registrations cannot create
  capacity. Saturation reaches the existing durable capacity-wait path before a
  semantic coding attempt is consumed; ambiguous invocations retain their lease.
- Each mission assignment has durable state, its team/pool snapshot, queue reason,
  selected worker and lease identity. Role/member tools, worker capabilities and
  the current permission policy are intersected at request construction; a
  current stricter disable or deny fails closed.
- The isolated workspace-per-attempt path remains intact. No legacy workspace,
  deployment path, secret boundary or Docker authority was broadened.
- Integration now initializes one accepted head per repository/target branch.
  Every candidate records exact run/attempt/base/candidate/profile/verification/
  review/directive identities in a cross-run FIFO queue. A fenced target lease
  uses compare-and-swap against the expected accepted head. Advancement requires
  an authorized immutable snapshot and combined-gate artifact. Conflicts are
  durable explicit outcomes; accepted-head generations are shared across teams.
  If the accepted head changes while a candidate waits, Jarvis rebuilds and
  verifies the merge tree, then renews independent review against that exact
  sealed snapshot before the fenced compare-and-swap advancement.
- The UI adds worker-pool management, safe disabled-by-default cloning, mission
  team-version changes, version history, selected worker/model, queue reason,
  assignment status and merge-queue status. Existing cursor consumers load past
  50 runs, 1,000 events and 100 node executions; mission listing now follows all
  server cursors too.

## Changed areas

- `packages/contracts/src/jarvis_contracts/{registry,missions,workers,generate}.py`
- `packages/persistence/src/jarvis_persistence/models.py`
- `api/migrations/versions/0015_phase_04_teams_worker_pools.py`
- `api/app/jarvis_api/{missions.py,registry/service.py,auth/routes.py}`
- `orchestrator/app/jarvis_orchestrator/{missions.py,runtime,workers,verification}`
- `web/src/{app/(control)/worker-pools,components,lib/api}`
- `tests/unit/test_phase_04_teams_scheduler.py`
- `tests/integration/test_phase_04_merge_queue.py`
- generated JSON Schema, OpenAPI and TypeScript contracts

## LOCALLY VERIFIED

- `python -m ruff check ...`: passed.
- `python -m mypy packages/contracts/src api/app orchestrator/app packages/persistence/src`:
  passed, 152 source files.
- Focused Phase 4/schema/contracts: passed (16 tests on the last focused run).
- Final broader non-database Python run: 695 passed, 24 skipped, 202 deselected.
- Frontend TypeScript and ESLint: passed.
- Frontend Vitest: 54 passed.
- Generated Pydantic/OpenAPI/TypeScript contracts regenerated successfully.
- `git diff --check`: passed before the final documentation updates.
- The production Next.js build completed compilation and TypeScript validation,
  then the Windows host exhausted memory while spawning page workers. It is not
  recorded as passed and remains part of the CI gate.

The workstation's global pytest cache directory is ACL-denied; tests use the
repository `.tmp` directory successfully. This does not affect test results.

## CI VERIFIED

UNVERIFIED. The branch has not yet run exact-tip CI.

## LIVE VERIFIED

UNVERIFIED. Docker/PostgreSQL are not available locally and no explicitly
authorized V1 multi-worker staging target was available. No homelab, paid model,
legacy `/opt/jarvis`, or deployment operation was performed while collecting the
evidence above.

## Remaining gates and exact next action

Run `scripts/verify.sh` in the repository's PostgreSQL 16 CI environment. This
must exercise migration `0015`, the two-instance physical-slot race, duplicate
wakeups, unknown-invocation retention, cross-run merge queue/CAS test, production
build and Playwright. Fix any exact-tip failure, then push
`phase/04-teams-and-worker-pools`, open/update a draft PR, and require green CI on
that exact SHA. After CI, configure two explicitly authorized V1 worker
deployments with distinct physical-resource IDs and perform the real concurrent
browser journey; record it separately as LIVE VERIFIED. Do not touch `/opt/jarvis`
or merge the PR as part of that validation.
