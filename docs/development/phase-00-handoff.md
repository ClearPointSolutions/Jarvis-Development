# Phase 0 handoff

## Identity

- Base SHA: `c0b3a03dc07b435f16c2af73829cfcb4ed42ac19`
- Branch: `phase/00-operational-baseline`
- Final implementation SHA: `ab0258aa97af68837b7e81b00b713d3e005fe17b`
- Final branch SHA: the evidence-only documentation commit containing this file;
  record it from the draft PR or `git rev-parse HEAD` (a commit cannot contain
  its own SHA)
- CI identity: UNVERIFIED

## IMPLEMENTED

- Strict curl exit/status/timeout/Host/contract checks shared by installer and
  preflight; production public-origin checks retain TLS verification.
- Explicit control-plane and real-execution readiness in CLI/API/UI, including
  stale/demo/missing configuration states and persisted manifest identity.
- Migration `0011`, local `jarvis-admin runtime inspect`, explicit real
  orchestrator validation/start command, and a committed disposable target.
- Cancellation constructs real adapters without provider/worker dependency
  probes; unreachable workers still reconcile to unknown.
- A committed small Python target and refusing repeat-setup command make the
  forced-failure/continuation procedure reproducible without using Jarvis as the
  workload.

Changed areas: `scripts/install-homelab.sh`, `scripts/preflight.sh`, the new
strict probe/runtime-start/project-setup scripts, migration `0011`, persistence
and orchestrator runtime identity, operations/auth API contracts, generated
schemas/types, the health UI, Phase 0 fixtures, and focused unit/integration/
deployment tests. `docs/M12C_HANDOFF.md` now names the installed V1 console
script as the wrapper while retaining the separate legacy runner Python.

## LOCALLY VERIFIED

- `.venv/Scripts/python.exe -m pytest tests/unit tests/compatibility -q`:
  `640 passed, 2 warnings`.
- With functional Git Bash selected,
  `.venv/Scripts/python.exe -m pytest tests/deploy/test_http_probe.py
  tests/deploy/test_phase_00_project.py -q`: `14 passed, 1 pytest-cache
  warning`. These execute the shell behavior, including curl exit `7`/HTTP
  `000`, wrong statuses, arbitrary `401`, unsafe redirects, and refusing a
  repeated project destination without mutation.
- `.venv/Scripts/python.exe -m ruff format --check .`, `ruff check .`, and
  `mypy`: passed (`294` formatted files and `241` typed source files at the
  recorded runs). `pip check`, the secret scanner/self-test, shared schema
  generation check, and integrated OpenAPI check passed.
- Under repository-supported Node `v20.19.0`: generated TypeScript contract
  check, Prettier, ESLint, TypeScript, Vitest (`14` files / `54` tests), and the
  Next.js production build passed.
- `npm run test:e2e`: `5 passed, 6 skipped`. The five mocked shell/browser tests
  ran in Chromium with no reported failure. Six database-backed scenarios were
  correctly skipped because their disposable PostgreSQL runner variables were
  absent; they are not claimed as passed.
- The disposable fixture itself ran `pytest` successfully (`1 passed`) in a
  manually prepared committed repository.

Unavailable local gates: Docker CLI calls did not return on this workstation
and were terminated without altering the daemon; direct PostgreSQL access on
`127.0.0.1:55432` timed out. Consequently migrations against disposable
PostgreSQL, integration/protocol tests, the six database-backed Playwright
scenarios, and an uninterrupted `scripts/verify.sh` are UNVERIFIED.
`npm audit --audit-level=high` also did not return and is UNVERIFIED. No passing
result is inferred from any of these unavailable checks.

## CI VERIFIED

UNVERIFIED pending the corrected exact-commit rerun. GitHub Actions run
`34886588243` completed against earlier SHA
`e190610230f59f5015ee1addd6b584d5eae7bcd3` with `858 passed, 4 skipped` and
three failures: the new constraint did not use the repository naming
convention, one older integration assertion retained the pre-Phase-0 readiness
shape, and Linux exposed missing `0600` modes on fixture credentials. All three
were corrected in implementation SHA `d73b964da736d2aaa20cae1249cc4667c3e3244e`;
the failed run is evidence, not a passing gate. Run `34888213064` then reached
`860 passed, 4 skipped`; its only failure was Alembic detecting that two
migration server defaults were absent from model metadata. Implementation SHA
`ab0258aa97af68837b7e81b00b713d3e005fe17b` mirrors those defaults using the
repository's existing model pattern. Neither failed run is a passing gate.

## LIVE VERIFIED

UNVERIFIED. This workstation has no authorized Jarvis-Core/Worker shell in the
current session, so no live deployment, model call, worker invocation or soak is
claimed. No paid inference call was made.

## Remaining gates and exact next action

On a host with working Docker/PostgreSQL, check out the exact draft-PR SHA, start
the disposable database, set `TEST_DATABASE_URL`, and run `scripts/verify.sh`
without skips. Verify that exact SHA in CI. Then run
`docs/development/phase-00-acceptance.md` from an authorized Jarvis-Core shell
and replace LIVE UNVERIFIED only with the complete recorded evidence; do not
merge until those gates are reviewed.
