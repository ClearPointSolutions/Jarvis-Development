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
| G models/routes/budgets | Ollama/OpenAI adapters; durable budget gateway `providers/budget.py` + migration `0010`; provider retry preflight in `runtime/composition.py` | Health/fallback breadth; paid live acceptance needs a real key | 9 budget tests (`tests/integration/test_model_budget.py`), 4 preflight tests (`tests/unit/test_real_preflight.py`), 4 live tests (`tests/integration/test_live_model.py`) | Live `qwen3:1.7b` on loopback 11439: connection `network_checked`, organizer+architect schemas satisfied, exact usage 483/50 tokens, uninstalled tag classified. Paid path is fixture-only. | Local acceptance passed; paid live open |
| H instructions | Durable instruction queue; planner consumption | Truthful delivery at supported safe points | Follow-up during coding reaches next request | No current evidence | Open |
| I capability/limits | Wrapper and UTF-8 seals | Source version, actual model/tools, early project preflight | Capability mismatch and bounded project cases | No current evidence | Open |
| J approvals | Durable production approval API/UI | Normal-runtime protected effect and browser/restart cases | Reject/expire/tamper/duplicate/crash acceptance | Historical seven tests insufficient | Open |
| K publication | No real handler; real composition now refuses a `github_publish` node before any billed inference or worker dispatch | Full allowlisted approval-bound push/PR if publication becomes in scope | Real-mode build raises `RuntimeDependencyError` naming the node | Truthfully excluded from the V1 local MVP, not disguised as working | Excluded and disabled |
| L pagination | Cursor APIs, bounded first-page UI | Follow cursors and current projections | Run 51+, event 1001+, node 101+, reconnect | No current evidence | Open |
| M operator UX | Run evidence and partial views | Durable threads, required views, bootstrap, deliverables | Browser desktop/mobile/a11y operator journeys | Current build is not product acceptance | Open |
| N release | Archive and shared deployment env | Immutable image/config/schema manifest and rollback | Install A, B, restore A identities | No current evidence | Open |
| O packaging | Images/Compose/basic health | Dependency readiness, authenticated HTTPS/SSE topology | Fresh isolated authenticated install | Historical HTTP 200 insufficient | Open |
| P restore | Backup script | Quiescence/reconciliation, checksummed isolated restore | Pending workers, partial failures, identity checks | No current evidence | Open |
| Q operations | Usage aggregation | Health/stalls/retention/export/reconciliation/runbook | Fresh-environment commands and incident recovery | No current evidence | Open |

## Validation and continuation

### Live model and paid-budget evidence (2026-09-09, later session)

Local infrastructure actually contacted: Ollama at loopback `11439`
(`qwen3:0.6b`, `qwen3:1.7b`) and PostgreSQL 16.10 at loopback `55432`
(fresh database `jarvis_v1_budget`, migrations `0001`-`0010`). No homelab,
no OpenAI endpoint and no GitHub repository was contacted.

- G budget gateway: `providers/budget.py` replaces the blanket paid-call refusal
  with a durable per-call authorization evaluated inside the same fenced
  transaction that records the call intent. Migration `0010` adds private
  immutable `control.model_budget_grants`, revoked from `jarvis_v1_api` and
  update/delete-blocked by trigger. A grant binds the call to the request digest
  and to the exact bound route revision, so a later permissive revision cannot
  release a recorded call. Denials commit before they raise, so a refusal is
  durable evidence rather than a rolled-back decision. Nine PostgreSQL tests
  cover allow, no-bound-policy, `allow_paid` disabled, exceeded run ceiling,
  unknown pricing, indeterminate prior spend, restart-without-second-charge,
  replayed denial with tamper rejection, and the untouched free-provider path.
- Fail-closed scope correction: an indeterminate durable run total blocks only a
  policy that sets `max_run_cost`. A policy that does not cap the run does not
  depend on that total, so requiring it would deny without protecting anything.
- Duplicate paid inference: unchanged receipt semantics remain the guard. A grant
  and its `model.call_started` event commit together, so a started call without a
  receipt still raises `AmbiguousEffectError` instead of re-billing.
- Live Ollama acceptance (`tests/integration/test_live_model.py`, opt-in through
  `JARVIS_LIVE_OLLAMA_URL`/`JARVIS_LIVE_OLLAMA_MODEL`): connection validation
  reports `network_checked` against the real server; the live model satisfied the
  actual `OrganizerOutput` and `TaskPlan` planning schemas; usage was recorded
  with `provenance: "exact"` (for example 483 input / 50 output tokens) and no
  cost amount was invented; an uninstalled tag produced a classified failure and
  a durable `failed` accounting row rather than a crash. The documented probe
  reported `qwen3:0.6b` at 243/7 tokens in 22.1s.
- Honest model-capability finding: `qwen3:0.6b` satisfies the planning contracts
  but not the stricter `ReviewDecision` schema. Small tags intermittently return
  malformed structured output, which the system classifies as
  `provider.contract_failure`. The reviewer test therefore accepts either a valid
  decision or that classification, and asserts the durable outcome either way.
- Consequence for real configuration: `evaluate_retry` gives an unmatched failure
  class no retries and a `block` exhaustion action, so a single malformed real
  model response blocked an entire run. Real composition now refuses, before any
  billed inference, a model node whose bound retry policy has no retries for
  `provider.contract_failure`, `provider.transient`, `provider.rate_limited`,
  `infrastructure.timeout` or `infrastructure.service_unavailable`. Retry policy
  stays configuration; only the missing-coverage refusal is code. The real
  entrypoint fixture was corrected because it lacked exactly those rules.
- K publication: real composition refuses a `github_publish` node up front. The
  node already failed closed at invocation, but only after planning, worker
  dispatch, verification and integration had already spent real time and money.

### Windows long-path acceptance constraint (2026-09-09, later session)

Real-entrypoint acceptance failed four consecutive times on this machine with a
`WorkerBoundaryError` from candidate import, blocking the run. It was neither an
application defect nor the model/budget work: three protocol model calls always
completed first, and the fixture provider is unpaid so the budget gateway is
inert. A freshly provisioned worker fixture failed identically, which refuted the
stale-container explanation.

The cause is the Windows path limit. `test_real_entrypoint` takes `source_root`
from `tempfile.mkdtemp()`, so it inherits `TMPDIR`. With the repository checkout
as `TMPDIR` the source root is about 90 characters, and `import_candidate` then
adds `<32 hex>/c/<key>` before `git worktree add`. This is the same class of
failure recorded above as Git for Windows `fatal: '$GIT_DIR' too big`.

With `TMPDIR=C:/jv/t` (a 27-character source root, 62 shorter),
`test_normal_real_entrypoint[process]` **passed in 465.43s** against a freshly
provisioned worker and a dedicated database, exercising candidate import,
worktree checkout, a failing attempt, its retry and multiple source stores.
CI is unaffected: it runs on Linux under `/tmp`.

Diagnosis cost four runs because a blocked run reported only
`exception_type=RuntimeBlockedError` while the conftest resets the event store
between tests. Both the node and service handlers now report the boundary's
curated safe constant; `tests/unit/test_boundary_diagnostics.py` (4 tests) fixes
the accept/reject shapes so no URL, path or credential assignment can reach that
channel.

Known remaining gap, deliberately unchanged: a `WorkerBoundaryError` that escapes
the worker adapter's own handlers loses its declared `failure_class`, because
`nodes.py` honours only `ClassifiedNodeError`. It degrades to
`orchestration.runtime_error` and hard-blocks even when the boundary declared a
retryable class. That conflicts with the class-specific retry principle and needs
its own change with its own acceptance.

### Current continuation evidence (2026-09-09)

- D/E: normal process and service startup both pass (1082.76s), including
  completed work, a second job inheriting accepted history, isolated historical
  work and cross-project rejection. Composition now actually uses the durable
  candidate store and recovers local receipts before requesting a worker export.
  Eight candidate interruption/tampering tests pass after fixing ambiguous Git
  short-ref comparison. Dependency-independent cancellation remains open.
- F: migration `0009` adds private immutable normalized model-response receipts.
  Request/profile/provider digests prevent substitution. Completed responses
  survive the model/domain persistence window; missing receipts remain ambiguous.
  Two PostgreSQL gateway/role/immutability tests pass. Planning permits guarded
  re-entry; model review reuses original evidence and a stable persisted timestamp.
  Four review recovery/current-source tests pass (115.71s).
- H: only supported planning/worker nodes consume instructions. Worker requests
  now include frozen instructions in their architecture artifact; queued/delivered
  events distinguish safe-point attachment. Seven control/recovery tests pass.
  A real worker receiving a follow-up during coding remains an acceptance gap.
- L: runtime list clients follow cursors for runs/projects/tasks/nodes/commands
  and evidence. Tests cover run 51, node 101 and event 1001, later-page errors and
  repeated cursors. Reconnect refreshes runtime projections and latest execution
  numbers determine graph state. Full browser history boundary tests remain open.
- M/Q: Projects and Artifacts use actual authorized history/downloads. Health
  reports persisted heartbeats, owned queue counts and expired leases. Its API
  authentication/ownership/staleness test passes. Settings links real registries;
  Developer opens the runtime inspector. Durable standalone conversations,
  retention, incident exports and the full operator acceptance inventory remain open.
- Frontend: 54 tests passed; production build and types passed before final
  presentation edits. Added browser navigation/download/health/a11y checks.
- Whole-gate revalidation is running in `.tmp/finish-verify-v3.log` on an isolated
  database, with mandatory HTTP/SSH/isolated-executor acceptance. No skipped gate,
  product completeness, staging, publication, or merge-readiness claim is made.

The original A–Q requirements above remain authoritative; these focused results
do not close their remaining acceptance cases. Real Worker-01/model/disposable
repository configuration was requested for staging; no homelab contact occurred.

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
