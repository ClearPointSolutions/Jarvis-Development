# Phase 1 handoff

## Identity

- Base SHA: `29780ba722f93d72ed725fff64a85b2eef7fda43`
- Branch: `phase/01-persistent-missions`
- Final implementation SHA: `7e739cd5d960609e091b61bb0cb4aff29e934d8a`
- Final branch SHA: record from `git rev-parse HEAD` after the evidence commit
- CI identity: UNVERIFIED until the draft-PR workflow completes against the exact
  final commit

## IMPLEMENTED

- Migration `0012` and SQLAlchemy models for missions, immutable directive/team
  versions, ordered durable messages, leased management turns, stable work items,
  dependency edges, and management-owned model receipts.
- A registry-backed fixed development team with manager/developer/reviewer roles,
  structured manager/reviewer profiles, one exclusive developer worker, and a
  published workflow whose resolved execution revisions are frozen and validated.
- A bounded on-demand manager consumer that records input before inference, records
  call intent and response receipt before application, requires explicit paid-call
  authorization, never falls back from real to demo, rejects stale replies, and
  applies only schema-valid backlog changes. Pending items can be updated without
  replacing stable identity; started/terminal items cannot.
- Owner/CSRF protected, expected-version and idempotency-aware mission create/list/
  detail/directive/message/turn/work-item/start APIs with pagination for growing
  histories. Manual start uses the existing durable `create_job` service and
  a stable assignment-derived enqueue identity to reconcile double-clicks, changed
  client keys, and crash windows to one linked run. Only ready items governed by
  the current directive may launch.
- Mission list/detail UI with durable manager conversation, explicit queued versus
  delivered/stale/failed state, goal/constraint revision, fixed-team selection,
  backlog/dependency lifecycle, per-turn paid authorization, explicit launch, and
  links into the existing run evidence/approval experience.
- Generated Pydantic, JSON Schema, OpenAPI, and TypeScript contracts; normalized
  mission/management/work-item events; deterministic demo configuration; focused
  unit/integration tests; and a mocked Chromium journey from mission creation to a
  linked run.

## Changed files

```text
.env.example
api/app/jarvis_api/auth/routes.py
api/app/jarvis_api/main.py
api/app/jarvis_api/missions.py
api/app/jarvis_api/registry/service.py
api/migrations/versions/0012_phase_01_missions.py
deploy/compose.production.yml
docs/ARCHITECTURE.md
docs/DATA_MODEL.md
docs/EVENT_SCHEMA.md
docs/STATUS.md
docs/development/phase-01-handoff.md
orchestrator/app/jarvis_orchestrator/demo/bootstrap.py
orchestrator/app/jarvis_orchestrator/main.py
orchestrator/app/jarvis_orchestrator/missions.py
orchestrator/app/jarvis_orchestrator/runtime/service.py
packages/contracts/generated/jarvis-api.openapi.json
packages/contracts/generated/jarvis-api.ts
packages/contracts/generated/jarvis-contracts.schema.json
packages/contracts/generated/jarvis-contracts.ts
packages/contracts/src/jarvis_contracts/event_registry.py
packages/contracts/src/jarvis_contracts/generate.py
packages/contracts/src/jarvis_contracts/missions.py
packages/contracts/src/jarvis_contracts/registry.py
packages/persistence/src/jarvis_persistence/models.py
tests/integration/test_phase_01_missions.py
tests/unit/test_phase_01_missions.py
web/src/app/(control)/missions/[missionId]/page.tsx
web/src/app/(control)/missions/page.tsx
web/src/app/(control)/registry/page.tsx
web/src/app/(control)/roles/page.tsx
web/src/app/(control)/teams/page.tsx
web/src/app/globals.css
web/src/components/app-shell.tsx
web/src/components/mission-detail.tsx
web/src/components/missions-page.tsx
web/src/components/registry-fields.tsx
web/src/lib/api/missions.ts
web/tests/e2e/phase-01-missions.spec.ts
```

## LOCALLY VERIFIED

- `.venv/Scripts/python.exe -m pytest tests/unit/test_phase_01_missions.py -q`:
  `2 passed`.
- Ruff lint and mypy passed (`246` typed source files); generated Python schema,
  integrated OpenAPI, generated TypeScript contracts, Prettier, ESLint, and
  TypeScript checks passed.
- Vitest passed: `14` files / `54` tests. Next.js production build passed and
  includes `/missions`, `/missions/[missionId]`, and `/roles`.
- Focused Chromium Phase 1 journey passed: `1 passed` after rebuilding the
  production bundle. The initial pre-build run returned the expected stale-bundle
  404 and is not counted as a pass.
- The first broad non-integration pytest attempt was invalidated by Windows denying
  pytest's default AppData temp directory (`59` setup errors); it is not a product
  failure and is not counted as a pass. A repository-local basetemp rerun and the
  complete result is recorded below.

- With `TEMP`, `TMP`, `TMPDIR`, and `PYTEST_ADDOPTS=--basetemp=...` pointed at a
  fresh repository-local directory, `scripts/verify.sh` passed secret scanning,
  `pip check`, Ruff format/lint, mypy, and executed the non-database suite as
  `678 passed, 10 skipped, 195 deselected`. The script then stopped at the
  unchanged 80% coverage gate because excluding PostgreSQL integration tests left
  aggregate coverage at 54.63%. This is a FAILED/UNVERIFIED complete gate, not a
  pass; no threshold or test was weakened.
- `npm run test:e2e` after a fresh production build: `6 passed, 6 skipped`. The
  skips are the repository's database-backed scenarios requiring the disposable
  runner variables. `npm audit --audit-level=high`: `0 vulnerabilities`.

PostgreSQL migration/integration tests are UNVERIFIED locally: the configured local
port accepts a TCP attempt but PostgreSQL authentication/handshake times out, and
Docker commands do not return on this workstation. No migration or integration
result is inferred from that unavailable prerequisite.

## CI VERIFIED

UNVERIFIED. Record the workflow name/run ID, exact commit SHA, and result here after
the feature branch is pushed and the draft PR workflow finishes.

## LIVE VERIFIED

UNVERIFIED. No authorized Jarvis-Core/Jarvis-Worker staging shell is available in
this session. No deployment, real manager model call, real worker launch, or soak
is claimed, and no paid inference was performed.

## Remaining gates and exact next action

Push the branch, open/update the draft PR, and record exact-commit CI (including
the PostgreSQL migration/integration/coverage/protocol fixtures). Then, from an explicitly
authorized V1 staging target, migrate a disposable/current V1 database, configure a
real manager profile and the published fixed-team workflow, create a real mission,
authorize one manager turn, explicitly launch one ready item, and retain the linked
ordinary worker/verifier/reviewer/integration evidence. Leave `/opt/jarvis` and the
legacy worker environment untouched.
