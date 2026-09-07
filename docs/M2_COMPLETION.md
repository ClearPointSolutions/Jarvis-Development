# M2 integration evidence

Date: 2026-09-07. Scope: M2A, M2B and M2C only. All local gates passed.
Subsequent reconciliation: the user reports M2 complete; fetched main contains
merge `ac6206b3b1bfb8e4adca1f414f81807e0a92ebcc`. The local push/credential
blocker recorded below is historical. M3 evidence is in `M3_COMPLETION.md`.
No homelab contact or deployment occurred during M2.

## Provenance and merge order

Fetched main was `1fc4c8ecdcb46291efc8896c0edcd652b9f70b61`; no newer remote work
was present. The original three branches were based on `8ff74a7`. Their dirty
worktrees were scanned and preserved as commits `1bbd1b8` (auth), `65beabf`
(events), and `817e91c` (web), with `codex/backup-m2-*-20260907` refs.

Shared contracts landed at `f40755e`; migration/test isolation at `e0f39f6`.
Integration order was events (`988f7d1`), auth (`33a850a`), frontend (`1bfd9c5`),
Windows bootstrap correction (`9ebdadb`, integrated as `6700e0a`), then the event
authorization/lock-order followup (`fff5a8b`). Final fixes were reviewed centrally.
No competing private schemas remain: both Pydantic JSON Schema/TypeScript and the
actual FastAPI OpenAPI/TypeScript paths are generated and drift-checked.

M2A branch: `codex/m2-auth` at `9ebdadb`.
M2B branch: `codex/m2-events` at `fff5a8b`.
M2C branch: `codex/m2-web` at `1bfd9c53c47b22f0baaa6ebf807605c965653a93`.
The final integration commit is recorded in the final evidence section.

## Implemented boundaries

- Auth: explicit local bootstrap and password reset, Argon2id, 256-bit opaque
  sessions stored as hashes, CSRF hashes, rotation, idle/absolute expiration,
  persisted revocation, account/network backoff, exact Origin/Host checks, bounded
  JSON bodies, secure headers, normalized errors and redacted audit events.
- Events: typed producer intent and registry validation, recursive secret/reasoning
  removal, server summaries, immutable oversized artifacts, global-first locking,
  per-run gap-free order, duplicate suppression and transactional watermarks.
- Delivery: authorized pagination, one-statement snapshot/cursor boundary, real
  PostgreSQL LISTEN/NOTIFY plus polling fallback, authenticated SSE, Last-Event-ID,
  keepalive, per-owner/process connection limits, frame-by-frame authorization,
  explicit reset for unsupported major/gaps/expired or future cursors.
- Artifacts: run/job/project namespaces, immutable DB metadata, authorized visible
  originating event, contained filesystem paths, forced safe download and digest
  validation. Failed/duplicate transactions may leave unreferenced redacted bytes;
  those have no authorized download path. Retention/garbage collection is later work.
- Frontend: responsive dark Mission Control with Organizer/graph/status/activity
  regions; honest future-feature states; real login/logout/session recovery;
  generated API client; TanStack Query server state and ephemeral Zustand UI state;
  real run event monitor with dedup/reconnect/authoritative refresh; safe Markdown,
  read-only xterm, mobile focus trapping/restoration and reduced-motion styles.

## Routes and migration

API routes:

| Method | Route | Behavior |
| --- | --- | --- |
| GET | `/health` | Minimal anonymous liveness |
| POST | `/api/v1/auth/login` | Owner authentication and session rotation |
| POST | `/api/v1/auth/logout` | CSRF-protected durable revocation |
| GET | `/api/v1/session` | Current session, no raw session token |
| GET | `/api/v1/system/readiness` | Protected database/migration readiness |
| GET | `/api/v1/runs/{run_id}/event-snapshot` | Authorized projection/cursor |
| GET | `/api/v1/runs/{run_id}/events` | Authorized durable pagination |
| GET | `/api/v1/runs/{run_id}/events/stream` | Authenticated replay/live SSE |
| GET | `/api/v1/artifacts/{artifact_id}` | Authorized immutable content download |

Web: `/`, `/login`, `/projects`, `/runs`, `/runs/[runId]`, `/workflows`,
`/workers`, `/providers`, `/registry`, `/approvals`, `/artifacts`, `/health`,
`/settings`, `/debug`; `/api/[...path]` is transport only, with no independent
authorization or runtime execution. Auth/event modules, event delivery wiring,
safe content/session/feed/shell components, generated OpenAPI and browser fixture
runner were added. No orchestrator execution service was enabled.

Existing migration 0002 is preserved. New 0003 grants only API artifact INSERT and
readiness version SELECT, revokes orchestrator artifact UPDATE, and adds immutable
artifact metadata enforcement. Clean migration, M1-to-head, downgrade/upgrade,
metadata drift and real logical-role tests cover the chain.

## Security review

Integration review corrected audit normalization bypass, runless artifact IDOR,
artifact tamper detection, metadata redaction, command/event lock inversion,
future cursor stalls, lost REST reset codes, API-role readiness grants, proxy Host
replacement, and Windows Uvicorn/Psycopg loop incompatibility. Both body boundaries
are bounded; SQLAlchemy logs hide parameters. Raw exceptions/validation input never
reach client errors. The real API-role test checks exact stored session/CSRF hashes,
current rotated-token logout across restart, auth audit source canary redaction,
owned/unowned event routes, REST/SSE schema-major reset, and nonmutating SSE GET.

The browser test uses a freshly created loopback PostgreSQL database and actual API
and Next production processes. It verifies secure cookie flags, valid/invalid CSRF,
missing Origin denial, persisted event delivery, offline/online recovery, explicit
Last-Event-ID replay, authoritative projection, accessibility and logout/revoked
reads. Passwords are generated in memory, never command arguments. API logs,
event output, rendered DOM and frontend bundles are checked for synthetic canaries;
the resulting screenshot was visually reviewed. No production provider, Ollama,
GitHub runtime credential or worker connection is used by these tests.

## Verification commands

Supported local runtimes: Python 3.12.14, Node 20.19.0, PostgreSQL 16.10.
The machine default Node 20.15.1 was not used for final gates. A repository-local
ignored Node 20.19.0 runtime supplied PATH. Git Bash executes the POSIX entrypoint.

```sh
python -m pip check
(cd web && npm ci)
export TEST_DATABASE_URL=postgresql+psycopg://jarvis_v1_dev@127.0.0.1:55432/jarvis_v1_test
export DATABASE_URL="$TEST_DATABASE_URL"
scripts/verify.sh
```

The script runs the scanner+self-test, Ruff format/lint, strict mypy (including
verification scripts), complete pytest/coverage and migrations, deterministic
JSON Schema/OpenAPI/TypeScript drift checks, Prettier, ESLint, TypeScript, Vitest,
standard Next Turbopack production build, high-severity npm audit, and the real
Chromium vertical suite through `python -m scripts.verify_m2_browser`.

## Final evidence

Verified implementation SHA: `61de8b7f899ed7e1c3f9c0a27ebbac96fb84e0ed`.

`scripts/verify.sh`: PASS, exit 0. Exact pytest result: **204 passed, 1 warning
in 40.94s**, **85.62%** branch coverage. Strict mypy: 64 source files. Vitest:
**23 tests, 8 files passed**. Chromium: **6 passed in 21.2s**, including the real
database test. Axe found
no violations on the integrated monitor, desktop/mobile shell had no serious or
critical violations, and serious console/page errors were absent. Standard
Turbopack production build passed. Dependency installation reported zero npm
vulnerabilities; pip check and secret scanner passed. Reachable Git-history scan:
258 blobs, zero high-confidence findings. Legacy/reference diff is empty.

Local Windows gate environment additionally set `PYTEST_DEBUG_TEMPROOT` to the
ignored `.worktrees/m2-gate-temp` directory and `PYTEST_ADDOPTS` to
`-o cache_dir=<checkout>/.worktrees/m2-pytest-cache`, isolating Windows temp/cache
ownership. Artifact publication and reading now support extended Windows paths.
No test, lint, type, CSP or grant requirement was relaxed.

GitHub CI: pending push. Automatic approval review initially rejected a four-branch
push on the basis of public source/history egress authorization. After reviewing
the exact destination, authorization and scanned outgoing scope, the narrower
integration-branch push was approved. GitHub then rejected the local Git credentials
with "Invalid username or token." No push occurred. The connected GitHub API can
create new commits but cannot preserve the existing author/committer metadata;
the reviewed local history is retained pending refreshed Git credentials. M2 is not
marked fully complete until the branch is pushed and the remote CI gate passes.

Known nonblocking warnings: upstream Starlette/AnyIO BlockingPortal deprecation,
Node NO_COLOR/FORCE_COLOR diagnostic, and package-manager notices for pinned
transitive dependencies. No security/type/lint rule was weakened. ADR-024 records
the transport/artifact decisions; historical ADRs remain intact.
