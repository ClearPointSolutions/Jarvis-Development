# Phase 5 handoff

## Identity

- Base SHA: `dca6a9c1fbb5dfbe5f997c7f2f1ef7ae862a45c1`
- Branch: `phase/05-unattended-operations`
- Implementation SHA: `f63a601c5a5a6206d3d755893ea741152cc2901c`
- Final branch SHA: the documentation commit containing this handoff; obtain it
  from `git rev-parse HEAD` because a commit cannot contain its own identity
- CI identity: UNVERIFIED
- Live identity: UNVERIFIED
- Published branch: `origin/phase/05-unattended-operations`
- Draft PR: not created because GitHub CLI is unavailable in this environment;
  use the [pre-filled compare page](https://github.com/ClearPointSolutions/Jarvis-Development/compare/main...phase/05-unattended-operations?expand=1)

## IMPLEMENTED

- Migration `0016` and persistence models for deduplicated operational alerts,
  bounded outbound outbox attempts, retention tombstones, recovery generation,
  backup manifests, and wall-clock qualification records.
- Owner-scoped diagnostics for real/demo identity, orchestrator freshness,
  accepted progress, queue/assignment age, stalled workers, ambiguous effects,
  provider health, maximum liabilities, approval age, integration backlog and
  artifact growth. Heartbeat uncertainty and actionable reasons are explicit.
- Alert evaluation opens one durable incident per owner/signal identity,
  increments repeated observations and records recovery instead of creating a
  notification storm. In-app is the default; no outbound destination is enabled.
- Mission/team/global controls remain in the Phase 2 machinery. Phase 5 adds a
  confirmation-bound emergency stop which closes global admission, requests
  cancellation, increments the recovery generation, disables dispatch, and
  reports remote outcomes as pending evidence.
- Run claiming and every fenced transaction now require the current durable
  recovery generation and enabled dispatch. Database loss therefore cannot
  authorize a new effect; restored/old executors lose authority.
- Owner/run-scoped retention preview with configurable age limits. Active and
  ambiguous work plus receipt/source/candidate/verification/review provenance is
  protected. A tombstone ledger exists, but executable blob deletion is not yet
  exposed because the current artifact adapter cannot atomically tombstone and
  delete while proving every reference safe.
- `backup-v1.sh` now creates a checksummed manifest tying the quiesced database,
  checkpoints, artifacts, source, app SHA, images, schema, runtime manifest,
  recovery generation and surviving external-effect inventory. Secrets are
  explicitly excluded.
- New `restore-v1.sh` validates without mutation by default and, with
  `--execute`, restores only into a fresh `jarvis-v1-restore-*` namespace,
  refuses existing volumes, checks schema/blobs, increments the fence, disables
  dispatch, inventories ambiguous effects, and starts neither API nor
  orchestrator.
- Persistent 24h/72h/7d qualification APIs capture exact environment/release,
  fault/effect/cost/storage observations and reject `complete` until actual UTC
  elapsed duration satisfies the selected profile.
- Health UI shows operational signals, uncertainty and durable alert lifecycle.
  Generated Pydantic, OpenAPI and TypeScript contracts are current.

## LOCALLY VERIFIED

- Ruff format/check: passed (`324` files checked at the recorded run).
- Strict mypy: passed (`260` source files).
- Focused Phase 5/schema/contracts/Phase 4 annotation regression: `19 passed`.
- Earlier focused ownership/contracts run: `22 passed, 3 PostgreSQL skipped`.
- Broad non-PostgreSQL run: `694 passed, 24 skipped, 203 deselected, 4 failed`.
  Two failures were Docker Compose plugin unavailability (`unknown flag:
  --project-name`), and two candidate-recovery subprocess failures occurred
  while two broad suites were accidentally competing and Windows reported paging
  file exhaustion. They are not claimed as passing; an isolated CI rerun is
  required.
- Frontend Prettier, ESLint and TypeScript: passed. Vitest with one worker:
  `14 files / 54 tests passed`.
- Next.js production build compiled successfully and entered TypeScript, then
  made no progress for two minutes on the memory-constrained Windows host and was
  terminated. It is UNVERIFIED, not passed.
- JSON Schema and integrated OpenAPI checks passed; both generated TypeScript
  contract checks passed after regeneration.
- Alembic offline SQL generation for `0015 -> 0016` passed and shows all six
  tables, singleton recovery generation, grants, and revision update.
- POSIX shell execution is unavailable (the `bash` command resolves to WSL with
  no distribution), so backup/restore runtime syntax and behavior are UNVERIFIED
  locally.

## CI VERIFIED

UNVERIFIED. No exact-tip workflow has run yet. The normal gate must exercise
PostgreSQL migration roundtrip/drift/least-privilege grants, the recovery fence,
alert dedup/recovery integration test, existing protocol/fault tests, generated
contracts, production build, Playwright and the Phase 3 fixture.

## LIVE VERIFIED

UNVERIFIED. No authorized Jarvis-Core/Worker staging target was contacted. No
deployment, restore drill, remote cancellation, provider call, paid call, or
elapsed-time soak was performed. The 24h, 72h and seven-day gates are pending.

## Remaining gates and exact next action

Implement the storage adapter transaction that creates an identity tombstone and
deletes only an exact unreferenced digest, then add PostgreSQL race/reference
tests and a disposable-workspace cleanup test. Run `scripts/verify.sh` in the
repository PostgreSQL 16/protocol/browser environment and require green CI on the
exact branch tip. After that, use an explicitly authorized `/opt/jarvis-v1`
staging target for an isolated backup/restore drill with surviving remote work,
then start the 24-hour canary qualification. Do not mark longer profiles passed
until their real elapsed time is recorded; do not touch `/opt/jarvis` or merge.
