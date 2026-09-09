# V1 integration and hardening evidence

Authoritative active checklist, 2026-09-09. Branch `codex/v1-integration-hardening`.
Baseline: fetched main `1c61e70dcc6e526ebb0f0d7076e62a1909a91022`; exact
[CI 34309805401](https://github.com/ClearPointSolutions/Jarvis-Development/actions/runs/34309805401)
rechecked and failed. Historical milestone passes are not current validation.
The acceptance/product inventories in LOCAL_MVP_MATRIX.md remain required; this
matrix owns current work and evidence, superseding its historical progress table.

| Finding | Existing implementation | Remaining change | Executable acceptance | Exact evidence | Status |
| --- | --- | --- | --- | --- | --- |
| A baseline | Repaired real/demo fixtures, mandatory SSH fixture, composed startup coverage | Preserve full gate through later changes | Full PostgreSQL verify, real entrypoint, canonical demo | Exact `9d65e94` CI 34315858229 passed the whole verify script; 749 backend tests in preceding exact baseline; Windows wrapper follow-up passes all 5 instrumented tests | Passed baseline |
| B isolation | Candidate-bound broker, dedicated image, normal composition requires isolation; independent watchdog | Remote broker transport and complete packaging under O/P | Canary escape/authority denial and normal builds | 9 isolation tests passed against actual dedicated Docker image; crash/random-output reuse, timeout and abandoned-broker watchdog passed; both isolated normal-startup variants passed in 422.60s | Local acceptance passed; deployment gate pending |
| C binding | Exact project/workflow selection, explicit reusable-template mappings, immutable binding snapshot before inference | Preserve this gate through later changes | Cross-project run blocks before any model/worker call; snapshot rejects changed target | Unit/PostgreSQL freeze/reuse/mismatch passed; both normal-startup variants complete valid jobs then reject cross-project dispatch (393.85s) | Local acceptance passed |
| D lifecycle | Per-run source, fixed initial SHA | Accepted current base and isolated historical runs | Two jobs preserve accepted history | No current evidence | Open |
| E transfer | Verified bundle and receipt | Durable promotion intent, local receipt recovery, dependency-independent cancellation | Crash at import/ref/receipt boundaries | No current evidence | Open |
| F model receipts | Started/completed metadata | Immutable bounded response receipts and reconciliation | Crash after response before domain persistence | No current evidence | Open |
| G models/routes/budgets | Ollama/OpenAI adapters, runtime paid-call denial | Contract retries, context, health/fallback, paid limits | Protocol failures, actual Ollama planning/review | Historical enum result insufficient | Open |
| H instructions | Durable instruction queue; planner consumption | Truthful delivery at supported safe points | Follow-up during coding reaches next request | No current evidence | Open |
| I capability/limits | Wrapper and UTF-8 seals | Source version, actual model/tools, early project preflight | Capability mismatch and bounded project cases | No current evidence | Open |
| J approvals | Durable production approval API/UI | Normal-runtime protected effect and browser/restart cases | Reject/expire/tamper/duplicate/crash acceptance | Historical seven tests insufficient | Open |
| K publication | Missing runtime handler | Allowlisted approval-bound push/PR/reconciliation/CI | Protocol acceptance; separately authorized disposable GitHub | No publication target authorized | Open |
| L pagination | Cursor APIs, bounded first-page UI | Follow cursors and current projections | Run 51+, event 1001+, node 101+, reconnect | No current evidence | Open |
| M operator UX | Run evidence and partial views | Durable threads, required views, bootstrap, deliverables | Browser desktop/mobile/a11y operator journeys | Current build is not product acceptance | Open |
| N release | Archive and shared deployment env | Immutable image/config/schema manifest and rollback | Install A, B, restore A identities | No current evidence | Open |
| O packaging | Images/Compose/basic health | Dependency readiness, authenticated HTTPS/SSE topology | Fresh isolated authenticated install | Historical HTTP 200 insufficient | Open |
| P restore | Backup script | Quiescence/reconciliation, checksummed isolated restore | Pending workers, partial failures, identity checks | No current evidence | Open |
| Q operations | Usage aggregation | Health/stalls/retention/export/reconciliation/runbook | Fresh-environment commands and incident recovery | No current evidence | Open |

## Validation and continuation

### Phase 1 evidence in progress

- `tests/unit/test_foundations.py`: initial repaired startup suite 7 passed;
  subsequent explicit legacy concurrency cases await rerun.
- Node 20.19.0: frontend typecheck, 49 tests and production build passed.
- Full mypy: 203 files passed before the additional entrypoint coverage variant.
- Ruff lint and secret scanner/self-test passed; final format/full gate pending.
- Newly provisioned `jarvis-v1-hardening-protocol-worker-v3` on loopback 22250:
  normal subprocess entrypoint passed in 316.87s, including classified failure,
  repair, independent review and integration. `.tmp/hardening-entry.log`.
- Windows TerminateProcess did not flush child composition coverage. Added a
  second acceptance variant invoking actual normal `serve()` with the same
  external protocol transports; `.tmp/hardening-service.log` is in progress.
- Full baseline `.tmp/hardening-baseline-v3.log` still running. Old service-mode
  regressions are passing, but M8 full-suite failures require diagnosis. A focused
  unrelated-branch integration passed in 120.14s; do not waive the full failures.
- Browser first pass: 8 passed, 2 failed, 1 optional demo test skipped. Updated
  explicit real-mode selection and empty-dashboard assertions; preserved controls,
  CSRF/CSP, a11y and console checks. Rerun `.tmp/hardening-browser-v2.log` pending.

Latest: browser rerun passed all 10 applicable tests (canonical demo is a separate
job). Normal `serve()` acceptance passed in 325.32s and collected composition
coverage. Full mypy again passed 203 files; Ruff format/lint pass. The M8 failures
were reproduced as Git for Windows `fatal: '$GIT_DIR' too big` at long worktree
paths. Full unchanged `scripts/verify.sh` now runs with a fresh short `.tmp/hv`
temporary root and fresh database `jarvis_v1_test_hardening_verify`; evidence
`.tmp/hardening-verify.log`. Canonical demo `.tmp/hardening-demo-v2.log` pending.
This is an implementation commit, not Phase 1 closure or a readiness verdict.

Published implementation: `fd8bf0c5e0cd8ad9d429ed45ed5bf2f4b863032c`,
[draft PR #5](https://github.com/ClearPointSolutions/Jarvis-Development/pull/5),
[exact CI 34314724943](https://github.com/ClearPointSolutions/Jarvis-Development/actions/runs/34314724943)
in progress. Canonical demo browser acceptance passed in 4.1m. Normal-service
coverage includes 236 executed lines in `runtime/composition.py`. The long-path
baseline finished 732 passed / 13 failed / 1 skipped; failures are the old API
mode fixture (fixed) and reproduced Git for Windows worktree path limits.
Current short-path full gate has passed the repaired API and M5 fixtures so far.

- Supported local Python: `.venv/Scripts/python.exe` 3.12.14.
- Supported local Node: `.tmp/toolchains/node-v20.19.0-win-x64/node.exe` 20.19.0.
- Disposable PostgreSQL 16.10 at loopback 55439; new database
  `jarvis_v1_hardening_test` preserves earlier fixtures and history.
- Baseline log: ignored `.tmp/hardening-baseline.log`; JUnit
  `.tmp/hardening-baseline.xml`. Do not commit credentials or raw fixture logs.
- Work in A–Q order. Update each row with implementation paths and exact tests
  as changes land. Run affected checks, review diffs and commit coherently.
- Final gate includes contracts, migration/role/security checks, backend coverage,
  frontend types/lint/tests/build, browser/a11y/console, demo, normal real startup,
  multi-task/repeat-job recovery, isolated installation/restore/rollback.
- Protocol fixtures, actual local Ollama, actual compatible worker, disposable
  GitHub and authorized homelab deployment are separate evidence categories.
- No guessed homelab contact, legacy mutation, main merge or live deployment.
- Finish useful local work before requesting exact authorized worker/model,
  disposable publication repository and deployment target details.

CI `34314724943` at `fd8bf0c`: all 749 backend tests passed (no skips),
86% coverage with the unchanged 80% gate; both normal-entrypoint variants ran.
The next contract drift gate found missing generated approval/usage API types.
Regenerated from the unchanged authoritative OpenAPI; contract check and Node
20.19 TypeScript passed. Full frontend/browser CI remains pending the follow-up.

Local full PostgreSQL run: 748 passed / 1 failed, 84.99% coverage; both normal
entrypoint variants passed. The remaining Windows wrapper fixture stopped on a
transient unknown heartbeat during instrumented startup; durable status later
proved that same invocation succeeded. Polling now waits for a terminal result
within the existing bound without relaunch or guard changes. All five wrapper
tests pass with subprocess coverage (49.8s). CI for `9d65e94` is still running.

Phase B local implementation evidence: dedicated image build, 9 confinement/
identity/recovery tests (17.75s), both normal-entrypoint variants with the actual
isolated executor (422.60s), all 42 existing verification unit tests (26.37s),
210-file mypy, Ruff and secret scan passed. Existing Git/PostgreSQL integration
regression is still running separately; no deployment completion is claimed.
Exact baseline `c0aeb54750ee06e7d3eca646cf64dc0d92ba0a5e` also passed both CI
34316772524 and 34316776758. Executor transport/systemd packaging remains under O/P.
