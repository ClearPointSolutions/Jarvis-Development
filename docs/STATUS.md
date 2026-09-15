# Jarvis V1 Status

## Phase 2 bounded autonomy (2026-09-14, in progress)

Branch `phase/02-bounded-autonomy`; fetched clean base
`5b7a5caefba9d9acccd21085c2232c515ed31dcc` (current `origin/main`, including
the merged Phase 1 mission work). Milestone criteria:

- [ ] Enforce an explicit durable mission state machine and autonomous opt-in,
  with mission/team/global admission pause, drain, safe-point instruction, and
  cancellation controls checked immediately before inference and dispatch.
- [ ] Persist event-driven manager wakeups, deduplication identities, frozen
  input cursors/snapshots, receipts, decisions, enqueue intents, and crash-safe
  recovery so accepted outcomes create at most one logical next assignment.
- [ ] Reserve worker capacity atomically before dispatch; represent saturation
  as durable capacity waiting without spending a semantic coding attempt, and
  require evidence-backed reconciliation for expired or ambiguous invocations.
- [ ] Enforce mission/team/global and time-window resource limits with
  transactional maximum-liability reservations, worker-inclusive accounting,
  unknown-liability retention, currency/unit compatibility checks, and paid
  unattended execution disabled until worker spending cannot bypass controls.
- [ ] Expose governing directive, active snapshot, next intended action/basis,
  wait/user-action reasons, controls, budgets, reservations, actual/unknown
  usage, observed worker/model evidence, and honest freshness in the API/UI.
- [ ] Prove two successive useful jobs from one direction, duplicate/crash
  convergence, stale-proposal rejection, budget races/unknown charges, capacity
  waits, outages, approval expiry, pause/dispatch races, and idle-no-inference;
  add all deterministic tests to the normal gate.
- [ ] Run focused and full local gates, browser/console/generated-contract
  checks, review the diff, update canonical docs, write the Phase 2 handoff,
  commit cohesively, push the branch, and open/update a draft PR when authorized.

No live staging, paid provider call, legacy-path change, deployment, main merge,
or repository-protection change is authorized by this milestone. Live and CI
evidence remain UNVERIFIED until actually observed against the exact final SHA.

## Phase 1 persistent missions (2026-09-14, code + CI complete; live gate open)

Branch `phase/01-persistent-missions`; fetched base
`29780ba722f93d72ed725fff64a85b2eef7fda43` (merged Phase 0 tip). Milestone
criteria:

- mission goals, immutable directive/team versions, chat, manager turns, and
  bounded dependency-checked work items survive API/orchestrator restart;
- one fixed manager/developer/reviewer team freezes active registry revisions,
  an exclusive worker, and a published workflow whose resolved snapshot contains
  the execution bindings;
- the bounded manager queue persists input before inference and a private
  response receipt before applying validated proposals, rejects stale direction,
  separates real/demo routing, and requires per-turn paid authorization;
- manual work-item launch is idempotently linked through the ordinary job/run
  enqueue service and completion is accepted only from the existing verified run
  lifecycle;
- authenticated paginated APIs and a usable mission/chat/backlog/run-evidence UI
  pass migrations, focused tests, generated-contract checks, frontend checks,
  browser acceptance, and the normal verification gate; unavailable CI/live
  staging evidence remains explicitly unverified.

Implemented through `304017e`: migration `0012`; registry-backed fixed team
templates and role revisions; persistent missions/directives/messages/turns/work
items; bounded receipt-backed manager execution; idempotent explicit launch through
the ordinary job service; normalized events; generated contracts; and the mission/
team UI. The repository-local non-database test execution completed with `678
passed, 10 skipped`; local `scripts/verify.sh` could not satisfy its unchanged 80%
coverage gate without PostgreSQL and reached 54.63%. Static/generated/frontend
gates, Vitest (`54 passed`), production build, npm audit, and mocked Playwright (`6
passed, 6 database-backed skipped`) pass. Exact implementation CI run
[`34910019452`](https://github.com/ClearPointSolutions/Jarvis-Development/actions/runs/34910019452)
passed PostgreSQL migrations/full Python (`879 passed, 4 skipped`, 84.42%), generated
contracts, frontend/build/audit, mandatory protocol fixture, database-backed
Playwright (`11 passed, 1 skipped`), and the deterministic demo browser run. Real V1
staging remains UNVERIFIED; see `docs/development/phase-01-handoff.md`.

## Phase 0 operational baseline (2026-09-14, code complete; live gate open)

Branch `phase/00-operational-baseline`; fetched base
`c0b3a03dc07b435f16c2af73829cfcb4ed42ac19` (the same SHA as `origin/main` at
branch creation). Milestone criteria:

- required HTTP probes reject curl transport failure/HTTP 000, timeouts,
  unexpected statuses, arbitrary 401 responses and unsafe redirects;
- control-plane readiness is reported separately from freshness-bounded real
  execution configuration/capability;
- private runtime setup is repeatable and validates separate wrapper/runner
  environments, pinned credential references, repository bindings and the
  immutable verifier identity without inference;
- pause/cancel construction does not require a successful provider probe;
- the deterministic protocol acceptance covers first-attempt test failure,
  classified retry, accepted integration, continuation and restart/lease
  recovery, while actual homelab evidence remains explicitly separate;
- affected tests, generated contracts, frontend checks and the unchanged full
  gate pass before phase completion.

Implemented: strict shared shell probes used by install/preflight;
control-plane versus execution-readiness API/UI projections; migration `0011`
for orchestrator runtime mode/manifest identity/summary; `jarvis-admin runtime
inspect`; explicit `scripts/start-real-orchestrator.sh`; provider-independent
cancel construction; and a disposable Phase 0 Python project fixture with a
non-destructive preparation command. The available unit, compatibility,
contract, frontend, shell-behavior and mocked-browser checks pass. Exact-commit
CI run `34889857600` passed the full PostgreSQL/protocol/browser gate after two
failed runs exposed and drove corrections to the Phase 0 migration/test
fixtures. Local Docker remains unavailable and Jarvis-Core/Worker acceptance
remains open for the reasons recorded in
`docs/development/phase-00-handoff.md`.

## M12B real homelab (2026-09-10, in progress)

Branch `codex/m12b-real-homelab` from `codex/m12a-deployment-hardening` HEAD
`0893c19f7b00673cc568a674fba8b237a7830da3` (M12A is the completed prior phase;
its exact-commit CI is green, not yet merged, so M12B stacks on it). Fetched
`origin`; `main` is `b1da876`. Not merged.

### Environment constraint and scope

This session runs on a Windows workstation, not on Jarvis-Core. It has **LAN
reachability** to the homelab (Ollama `192.168.40.94:11434` answers, Core
`192.168.40.105:13000` serves the V1 API, Worker `192.168.40.106:22` is open)
but **no interactive shell** on Jarvis-Core or Jarvis-Worker: the SSH connect
was denied by the environment's command policy, and there is no owner login for
Core's Mission Control. The operator chose to land the work that does not need
that shell now and defer the live run.

**Done this phase (code + real Ollama):**

* **Failure-class propagation fix.** `orchestrator/.../runtime/nodes.py` — a
  `WorkerBoundaryError` or provider `BoundaryError` that escaped its adapter's
  handlers lost its declared `failure_class`, degraded to
  `orchestration.runtime_error` and hard-blocked even when it declared a
  retryable class. New `boundary_failure_class(error)` extracts the class; only
  the enum crosses, never the boundary's `code`/message. Retryable → class
  retry; non-retryable → still blocks, with the accurate class recorded.
  Regression: 6 unit (`test_boundary_diagnostics.py`) + 2 integration
  (`test_boundary_retry.py`).
* **`jarvis-admin runtime build`** (`orchestrator/.../admin.py`, `project.scripts`
  entry). Assembles + validates the private `RealRuntimeConfiguration` from an
  operator infrastructure fragment + per-binding descriptors, builds the nested
  `project_workflows` map, re-checks every cross-reference (worker deployment
  present, workspace = deployment root + slug, host in allowlist, project ids
  consistent, no duplicate), atomically installs at `0600` or prints to stdout,
  and never reads or prints a credential value. `--check-registry` (needs
  `DATABASE_URL`) verifies each workflow version against its published resolved
  snapshot for the same worker-selector / provider-retry-class / structured-JSON
  invariants `RealComposition` enforces at startup — surfaced earlier, preflight
  not bypassed. Immutable binding unchanged. 13 unit + 5 integration tests.
* **Real homelab Ollama acceptance** — see the dedicated section below.

**Deferred to a Jarvis-Core-access session (M12C handoff):** V1 wrapper build
and install on `192.168.40.106` under `/opt/jarvis-worker/v1-wrapper/` (separate
venv, unchanged legacy runner + `runner_python_path`), the SSH worker boundary
verification, the isolated verification executor account/broker/image pin on
Core, non-demo Mission Control registry configuration + workflow publish, the
complete real disposable-project run, the forced retry, and orchestrator/API/web
restart recovery. None of these can be done without a shell on Core.

## M12A deployment hardening (2026-09-09)

Branch `codex/m12a-deployment-hardening` from verified `main`
`b1da87679132bff3cb1d578f009b67c625736473` (PR #5 merge; post-merge CI green).
Fetched `origin`, working tree clean at branch creation. Scope: make V1
reproducibly installable on a Core machine without weakening the production
security model. No `/opt/jarvis` contact, no homelab contact, no main merge.

### Deployment defects fixed

1. **Production web → API URL.** `deploy/compose.production.yml` `web` now sets
   `JARVIS_API_URL=http://api:8000`. Before, a normal production stack answered
   every `/api/...` with 503 `api.unavailable` unless the operator added an
   undocumented override. Regression: `tests/deploy/test_compose_contract.py`.
2. **Official homelab overlay.** `deploy/compose.homelab.yml` — layered on the
   production file with `-f`. It publishes the web port on `0.0.0.0` via a
   `ports: !override` (replace, not append) and runs the API with
   `JARVIS_ENV=development` / `JARVIS_COOKIE_SECURE=false`. Production stays
   production mode, HTTPS-only origin, Secure cookies, loopback ports; the API
   maintenance port stays on loopback in homelab too. Merged model validated in
   `tests/deploy/test_compose_contract.py` via `docker compose config`.
3. **Secret provisioning.** `scripts/provision_secrets.py` (stdlib only, POSIX
   only) creates the directory and the five secret files
   (`bootstrap_password`, `migrator_password`, `api_password`,
   `orchestrator_password`, `csrf_key`), generates values inside each consumer's
   length bounds, sets owner `10001` / group `10001` / mode `0600` (dir `0700`),
   is idempotent, refuses a symlink / non-regular file / out-of-range value
   (without `--force`), never prints a value, and has a `--check` mode.
   Regression: `tests/deploy/test_provision_secrets.py` (9 tests, root and
   non-root).
4. **First-install command.** `scripts/install-homelab.sh` (`--mode
   homelab|production`) runs the 13 steps end to end and prints the Mission
   Control URL and the owner-bootstrap command. It refuses a V1 root under
   `/opt/jarvis`, never deletes data, never runs `down -v`.
5. **Owner bootstrap.** New `owner-bootstrap` Compose service (profile-gated) +
   `scripts/owner-bootstrap.sh`. Runs `python -m jarvis_api.auth.bootstrap` as
   the database-owning `jarvis_v1_migrator_login` through the container
   entrypoint (which resolves `DATABASE_URL` from the migrator password file),
   so `docker compose exec api` is never needed and the least-privilege
   `jarvis_v1_api_login` gains no `INSERT` on `control.users`. Regressions:
   `tests/integration/test_00_migrations.py` (api/orchestrator lack INSERT),
   `tests/integration/test_bootstrap_identity.py` (api role INSERT denied;
   owning identity can; CLI never prints the password), plus the existing
   one-time-bootstrap test.
6. **Preflight.** `scripts/preflight.sh` — PASS/FAIL/SKIP per check with a
   specific reason (Docker, Compose version, env file, directories, secret
   readability, `docker compose config`, `JARVIS_API_URL`, one web port,
   mode-appropriate env/cookie/origin/bind, image refs, and — when running —
   PostgreSQL, schema revision vs the code pin, API `/health`, web, and
   `/api/v1/session` → 401). `scripts/deploy-core.sh preflight` delegates to it.
7. **Deploy script reconciliation.** `scripts/deploy-core.sh` header now states
   it is release-promotion + rollback only and lists the separate lifecycle
   entry points; added a `preflight` passthrough. `check` output points to
   `install-homelab.sh` for first install. `docs/DEPLOYMENT_RUNBOOK.md` is the
   new authoritative operator doc.

### Live local acceptance actually performed

On the development workstation (Windows 11 + Docker Desktop, Linux containers),
**not on Jarvis-Core** — this environment has no network path to
`192.168.40.105`. Target proxied as `http://localhost:13000`. Images
`jarvis-v1-python:m12a` / `jarvis-v1-web:m12a` built from this checkout.
Compose project `jarvis-v1`, `-f deploy/compose.production.yml -f
deploy/compose.homelab.yml`.

* `docker compose config --quiet` on the merged model: OK.
* `up -d --wait postgres`: healthy.
* `run --rm bootstrap`: `Dedicated V1 database roles ready`, exit 0.
* `run --rm migrate`: `alembic upgrade` 0001→0010 then
  `LangGraph checkpoint schema ready`, exit 0.
* `up -d --wait api web`: both running; web published `0.0.0.0:13000`, API
  `127.0.0.1:18000`.
* API `/health` (with the configured Host): 200. Web `/`: 200.
* `GET /api/v1/session` through the web proxy: **401 `auth.required`** — reached
  the API, not a 502/503.
* `scripts/owner-bootstrap.sh --env-file … --homelab --password-file …`:
  `Owner bootstrap complete`, exit 0; password absent from output.
* `POST /api/v1/auth/login` through the proxy: 200, `jarvis_session` cookie set;
  authenticated `/api/v1/session` 200; authenticated
  `/api/v1/system/readiness` `{"status":"ready","database":"ready"}`.
* Browser at `http://localhost:13000`: unauthenticated → "Your session is
  required"; signed in as `owner` → Mission Control overview renders, only
  console errors are the expected pre-login 401s. No serious console errors, no
  secret strings in `api`/`web` logs.
* Teardown: `docker compose … down` (no `-v`); disposable volumes then removed
  manually.

### Exact-commit CI

`2886781551c27bf955b02700451e8d774c949eb1` on `codex/m12a-deployment-hardening`
passed [verify 34425702845](https://github.com/ClearPointSolutions/Jarvis-Development/actions/runs/34425702845),
every step green including the mandatory real-entrypoint protocol worker
provisioning and the complete unchanged `scripts/verify.sh`. Not merged to main.

Local pre-push gates: `ruff format --check` (280 files), `ruff check`, `mypy`
(232 files), secret scan + self-test, a scoped PostgreSQL suite of 674 passed / 9
skipped (the 9 POSIX-only `provision_secrets` tests, run separately root and
non-root in a Linux container: 9 + 9 passed), `contracts:check`, frontend
format/lint/types + 54 tests, and the production web build. The full 822-test
`pytest --cov` + Playwright + demo stages were left to CI (a pre-existing
Windows local-run slowness in the real-runtime integration tests, unrelated to
this change); CI ran them green.

### Known limitations / unproven

* Acceptance was on Windows/Docker Desktop against `localhost`, not on the
  Jarvis-Core VM at `192.168.40.105:13000`. Docker Desktop bind mounts do not
  reproduce Unix secret ownership; `provision_secrets.py`'s `0600 10001:10001`
  behaviour is proven separately on native Linux (root and non-root) via
  `tests/deploy/test_provision_secrets.py` and a manual container run.
* The orchestrator is not started by the installer (needs a private
  `runtime.json`). Real OpenHands / Ollama runtime acceptance is **not** claimed
  by this phase.
* Restore is documented in the runbook but not scripted (matrix row P).
* Node 20.15 on this workstation is below the supported 20.19 line; the web
  image builds on `node:20.19.0` and CI uses 20.19.0.

Continue the existing integration branch from `dd8c3f8`. Completion requires
the A–Q matrix, current full verification, browser/operator acceptance, and
documented real-worker/model staging evidence. Historical logs are supporting
evidence only. Current implementation criteria include durable model-response
recovery without duplicate inference, complete cursor-based history and current
node projections, and truthful runtime instruction delivery. Preserve all
existing security, coverage, isolation and legacy boundaries. No readiness claim
until the remaining product and staging gates pass.

## Paid budget gateway and live model acceptance (2026-09-09, later session)

Continued `codex/v1-integration-hardening` from `f4f6355`. The prior session's
full gate reached 775 backend tests at 85.62% coverage and then stopped at the
frontend Prettier check; that was a local CRLF artifact in two Playwright specs,
not a repository defect. The committed bytes are LF, so CI was never affected.

Implemented the durable paid-inference budget gateway (`providers/budget.py`,
migration `0010`) that replaces the unconditional paid-call refusal. Nine
PostgreSQL tests and four composition preflight tests pass.

Live local Ollama was actually contacted at loopback `11439`. Connection
validation reported `network_checked`; the real model satisfied the actual
`OrganizerOutput` and `TaskPlan` planning schemas; usage was recorded with
`provenance: "exact"`. Two honest findings came out of that: the stricter
`ReviewDecision` schema is beyond `qwen3:0.6b` and only intermittently met by
`qwen3:1.7b`, and an unmatched failure class has no retries, so one malformed
structured response blocked a whole run. Real composition now refuses, before any
billed inference, a model node whose bound retry policy lacks the provider and
infrastructure classes. It also refuses a `github_publish` node: V1 has no
publication handler, so publication is excluded truthfully rather than failing
late after real spend.

Migration `0010` also moved the Alembic head while the readiness endpoint still
pinned `0009`, so a correctly migrated deployment would have reported itself
permanently unready. The full gate caught it; `1039cdd` fixes the pin and adds a
unit test comparing it to the actual head.

Exact commit `1039cddd7cb6a02d9b45481bf9b991bf0f8272d4` passed
[verify 34410979797](https://github.com/ClearPointSolutions/Jarvis-Development/actions/runs/34410979797)
with every step green, including mandatory real-entrypoint worker provisioning
and the complete unchanged `scripts/verify.sh`. The earlier `f4f6355` failure was
the external `npx playwright install` browser-dependency step, not a repository
defect.

No OpenAI endpoint, GitHub repository or homelab host was contacted. Paid
execution and publication remain unproven by design. Rows D-F, H-J and L-Q of the
hardening matrix are open, so this is a gate result, not a readiness claim.

## Active integration and hardening (2026-09-09)

Branch: `codex/v1-integration-hardening`, clean starting commit `1c61e70`.
Fetched remote main and exact CI run 34309805401: unchanged, failing.
The current user's authorization covers all local A–Q implementation and verification.
Authoritative checklist: [V1_HARDENING_MATRIX.md](V1_HARDENING_MATRIX.md).
Phase 1 baseline passed exact `9d65e94` CI 34315858229: full PostgreSQL verify,
mandatory normal-entrypoint SSH acceptance, coverage and canonical demo.
The Windows wrapper polling correction is separately committed as `c0aeb54`.
Phase 2B local acceptance passed: candidate-bound disposable verification,
denied authority/network canaries, normal project tests and durable recovery.
Executor production packaging remains under O/P. Phase 2C local acceptance passed:
exact project/repository/workflow/worker/target binding before inference and
immutable identity on recovery, including normal-startup cross-project rejection.
Phase 2D requires repeat jobs to inherit accepted source and Core Git history
without manifest edits, while historical-base work uses an isolated workspace.
No product/deployment readiness claim yet.


Last updated: 2026-09-08
Current phase: local MVP runtime and M9–M11 implementation in progress.
Overall state: M7 complete; M8 code is on main. Current changes are unverified as a whole.

Current authorization covers all remaining local implementation and hardening; historical
milestone-only scope statements below do not limit this work. See
[LOCAL_MVP_MATRIX.md](LOCAL_MVP_MATRIX.md) for current requirements and evidence.

## Historical M8 criteria

Base: `e62b7e8a44a6af99d54c6e6c760eaaf2657f2250`.
Branch: `codex/m8-verification-review-git`.

- [x] Fetch clean main and verify exact M7 branch and post-merge CI; record closure.
- [x] Structured bounded verification at adapter-confirmed root; explicit legacy correction.
- [x] Deterministic parsers and immutable artifact-backed execution evidence.
- [x] Sealed cumulative source snapshots and separate latest-attempt diffs.
- [x] Authoritative current-task Reviewer evidence, SHA binding and invalidation.
- [x] Correct verification/review retry classes and durable feedback.
- [x] Isolated attempts, durable integration HEAD, serialized queue and fenced leases.
- [x] Deterministic local merge/conflict policy, combined gates and integration snapshots.
- [x] Authenticated evidence API and real Mission Control evidence panels.
- [x] PostgreSQL/M5/M7 local E2E, adversarial acceptance and crash recovery.
- [ ] Full unchanged Python/database/contracts/frontend/browser/security gates.
- [ ] Completion report, clean committed branch, push and exact-commit green CI.

M8 only: no homelab/Worker-01 contact, production runtime credentials, deployment,
M9 authorization or M10 dashboard/publication implementation.

Progress evidence is recorded in [M8_COMPLETION.md](M8_COMPLETION.md). Focused
local Git/PostgreSQL, Reviewer and eight crash-boundary tests passed (78 focused
tests). The 42 verification security/unit tests and ten foundation/M8 browser tests
also passed. Frontend format/lint/types, 49 tests and production build passed.
Full gate and exact branch CI remain pending; M8 is not complete.

## M7 formal merge closure

Fetched origin on 2026-09-08; current main is the clean M7 merge
`e62b7e8a44a6af99d54c6e6c760eaaf2657f2250` (PR #4).
Exact branch commit `01f64fe360e1055824f4fa08dcdface82b18961f` passed
[verify 34232277520](https://github.com/ClearPointSolutions/Jarvis-Development/actions/runs/34232277520).
The exact post-merge main passed
[verify 34232309196](https://github.com/ClearPointSolutions/Jarvis-Development/actions/runs/34232309196).
M7 COMPLETE / READY FOR M8. M8 branch `codex/m8-verification-review-git`
starts from that verified merge. M8 implementation and gates remain pending.

## Historical M7 criteria (complete)

Base: fetched clean main `bb6646210e9f6a96f0d165aa3b13ac96fc0f60ed`.
Branch: `codex/m7-worker-adapter`.
M6 branch publication at `c10fdd281e4fcbfe5e971d11ab8c468f7ca739ea` passed
[verify 34218524317](https://github.com/ClearPointSolutions/Jarvis-Development/actions/runs/34218524317).
PR #3 merged; the exact post-merge main passed
[verify 34218540048](https://github.com/ClearPointSolutions/Jarvis-Development/actions/runs/34218540048).
This supersedes historical unmerged M6 statements below: M6 COMPLETE / READY FOR M7.

- [x] Fetch main and confirm exact M6 branch and post-merge CI.
- [x] Generic worker lifecycle and durable invocation contracts.
- [x] OpenHands compatibility adapter, pinned SSH transport and health/capabilities.
- [x] Durable numbered slots, generation fencing and M5 ownership integration.
- [x] Versioned local wrapper package, idempotency, cancellation and reconciliation.
- [x] Workspace containment, isolated worktrees and authoritative result inspection.
- [x] Bounded sentinel/result validation and immutable redacted log artifacts.
- [x] Local fake SSH acceptance and PostgreSQL/orchestrator E2E; demo safety retained.
- [x] Truthful worker API/UI facts, full local gates and exact-commit GitHub CI.
- [x] Completion report, coherent commits and clean working tree.

M7 evidence: 650 Python tests, 86.44% local coverage (86.37% Linux CI), 57 focused
M7 tests, 49 frontend tests, production build, nine foundation browser tests and
the four-run M6 browser acceptance test. Accessibility, serious console checks,
secret scans, dependency audit, migration round-trip and full `scripts/verify.sh`
pass. Implementation `8fbd99acc202ca81873e097dd169338d9f2064ea` passed
[exact-commit CI 34227977202](https://github.com/ClearPointSolutions/Jarvis-Development/actions/runs/34227977202).
See [M7 completion evidence](M7_COMPLETION.md). The final completion-record commit
and its exact CI are verified before handoff.

No homelab contact, worker SSH, wrapper deployment or M8 work is authorized here.

## Historical M6 criteria (complete)

Fetched clean main/base: `26fcdc5694f73adaf864227dd21579b3a61f6033`.
Branch: `codex/m6-deterministic-demo`. M5 branch commit
`9ad204ccaeeb3199c2cc30c2ab0c29264501048a` passed
[verify 34180910635](https://github.com/ClearPointSolutions/Jarvis-Development/actions/runs/34180910635).
[PR #2](https://github.com/ClearPointSolutions/Jarvis-Development/pull/2) merged that branch;
post-merge main passed
[verify 34181196662](https://github.com/ClearPointSolutions/Jarvis-Development/actions/runs/34181196662).
These verified results supersede the historical M5 pending-publication entries below.

- [x] Fetch main, verify M5 exact-commit branch and post-merge CI, create M6 branch.
- [x] Read current architecture, implementation, contracts, tests and legacy references.
- [x] Explicit fail-closed demo mode, deterministic adapters and idempotent bootstrap.
- [x] Real compiled workflow, durable tasks/attempts, retries, artifacts and demo decision.
- [x] Authenticated objective/start, live graph/feed/progress and persistent history UI.
- [x] Network-denied canonical browser E2E, secondary failures, restart/reconnect and determinism.
- [x] Full PostgreSQL, Python, frontend, browser, accessibility, security and script gates.
- [x] Completion evidence, clean committed branch, push and exact-commit green CI.

M6 only. No homelab, real runtime credentials, deployment, legacy edits or M7 work.

M6 local evidence: 593 Python tests, 88.82% combined coverage, 49 frontend tests,
9 foundation browser tests plus the four-run M6 acceptance test, zero M6 axe or
serious console findings, clean dependency audit/secret scans, production build,
and the complete PostgreSQL-enabled `scripts/verify.sh` pass. The final linked-run
fixture preservation correction also passes all three affected control tests.
Final implementation SHA: `42522847da6464d67fe07fe31bc2300c564fdac7`.
[Exact-commit verify 34190353517](https://github.com/ClearPointSolutions/Jarvis-Development/actions/runs/34190353517)
passed all gates: 593 Python tests at 88.74% combined coverage, 49 frontend tests,
nine foundation browser tests and the four-run M6 acceptance, with no browser
retries. See `docs/M6_COMPLETION.md` for architecture, limits and CI corrections.

## Historical M5 criteria (publication resolved above)

Base/main: `4367599eeed256d345296dff8f85c52cdc87d38a`, fetched and confirmed on 2026-09-07.
M4 exact-commit [verify run 34171942359](https://github.com/ClearPointSolutions/Jarvis-Development/actions/runs/34171942359) completed successfully.
Branch: `codex/m5-durable-orchestrator`. Earlier M4 publication blockers below are historical and superseded by this evidence.

- [x] Complete current-system and read-only legacy review.
- [x] Dedicated bounded orchestrator, ordered PostgreSQL queue, renewable fenced leases.
- [x] Durable enqueue and ordered authenticated/idempotent control APIs and functional UI.
- [x] Compiled M4 graph, PostgresSaver, node/effect middleware and safe reconciliation.
- [x] Cooperative pause/resume/cancel, class-specific retry budgets and durable backoff.
- [x] Recovery, graceful drain, authoritative event-backed projections.
- [x] RUN-001 through RUN-009, applicable FAIL tests, two-instance and crash-window tests.
- [x] Full PostgreSQL/Python/frontend/browser/accessibility/security/verify gates.
- [x] Completion documentation, coherent commits, branch push and exact-commit green CI.

M5 only: no homelab contact, real provider credentials, deployment, legacy edits, or M6 work.

M5 evidence: **570 Python tests**, **88.50% combined line/branch coverage** (78.18% branch-only), **47 frontend tests**, and **9 Playwright tests** pass. RUN-001-009, FAIL-001-007, two-instance concurrency/recovery, all eight crash boundaries, backoff pause/resume, migration roundtrip/drift/roles and API security checks pass. Desktop/mobile axe and serious-console checks report zero findings. Generated contracts, strict types, lint, clean npm install/audit, production build, secret scans and the complete PostgreSQL-enabled `scripts/verify.sh` pass. Diff and visual review are complete. Exact-commit branch CI and post-merge main CI passed as recorded above. See `docs/M5_COMPLETION.md`.

## Historical M4 criteria (publication resolved above)

Fetched main/base: `940cd631d54ba4bcc976b9175dd42b1fedd7386f`.
GitHub verify run [34167362184](https://github.com/ClearPointSolutions/Jarvis-Development/actions/runs/34167362184)
completed successfully for that exact SHA. The prior M3 publication blocker is historical.
Integration branch: `codex/m4-workflow-system`. This section records the prior milestone.

- [x] Pin authoritative workflow/config/API contracts and regenerate schema/TypeScript before parallel implementation (`20dd880ccb724116a77af4055df2320f887fa215`).
- [x] Implement static registry, safe validation/routing, bounded loops, deterministic reducers/join, LangGraph compilation and PostgreSQL reconstruction tests.
- [x] Implement durable owner-authorized draft/publication/version API with immutable published versions, snapshots, audit and concurrency controls.
- [x] Implement Workflow Studio using the same contract, typed inspectors, real M3 references, validation, layout and version history.
- [x] Pass WF-001–005, security, PostgreSQL migrations, complete backend/frontend/browser/accessibility/build and scripts/verify.sh gates.
- [x] Review secrets/diff, fix integration findings, record M4 completion evidence and commit the local milestone coherently.
- [x] Publication and exact-commit GitHub verify confirmed at main `4367599eeed256d345296dff8f85c52cdc87d38a`.

Final local evidence: **524 Python tests**, **88.68% combined line/branch coverage**
(branch-only: 78.68% overall, 86.19% workflow API/compiler), **41 frontend tests**,
**8 Playwright tests**, zero desktop/mobile axe violations or serious console
errors. Clean npm install/audit (zero vulnerabilities), production build,
PostgreSQL migration round trip/drift/roles, generated contract checks, secret
scanner and full `scripts/verify.sh` pass. Compiler: `1e71dcb`; editor: `636869e`;
code integration: `943a179`. See [`M4_COMPLETION.md`](M4_COMPLETION.md) for exact
SHAs, merge order, schema/compiler versions, controls, limits and evidence.

Historical publication blocker (resolved by the verified main/CI evidence above): native GitHub HTTPS credentials returned invalid username/token
(HTTP 401 preflight); connected GitHub repository writes return HTTP 403
`Resource not accessible by integration`. No M4 branch or CI was published.
The final native push exited 128 because no usable saved GitHub credential was
available (`could not read Username ... terminal prompts disabled`).
Restore write authentication, push `codex/m4-workflow-system`, and require a green
verify run for the exact HEAD before recording READY FOR M5. No main merge,
homelab contact, deployment or M5 work occurred.

## Active M3 criteria

Base: fetched clean origin/main `ac6206b3b1bfb8e4adca1f414f81807e0a92ebcc`.
The user reports M2 complete and merged; the prior local push blocker below is historical.
Branch: `codex/m3-config-routing`. No homelab contact, production keys, or deployment.

- [x] Persistent, validated worker/provider/model/route/retry/permission registries with immutable revisions and snapshot isolation.
- [x] Owner-only real GUI/API, optimistic concurrency, idempotent mutations, normalized audit, and write-only opaque references.
- [x] Distinct OpenAI SDK/Ollama/demo adapters with deterministic local transports and normalized results/errors/streams.
- [x] Deterministic routing, capability/data/health/circuit filtering and explicit permitted failover.
- [x] Durable bounded health/circuit state, usage/pricing snapshots, unknown cost and typed spend decisions.
- [x] Security canaries, SSRF denial, missing-provider behavior and least-privilege migration gates.
- [x] Full Python/frontend/production/browser/accessibility/secret gates and scripts/verify.sh.
- [x] M3 published to main at `940cd631d54ba4bcc976b9175dd42b1fedd7386f`; verify CI succeeded (run 34167362184).

Final local gate: 383 Python tests, 88.05% branch coverage; 32 frontend tests;
seven Playwright tests; desktop/mobile accessibility and console checks passed.
Production build, migrations, generated contracts, secret scan and npm audit passed.
See `docs/M3_COMPLETION.md`. M3 publication and exact-commit CI are confirmed.

## Historical M2 parallel-group criteria

Integration base: fetched authoritative main `1fc4c8ecdcb46291efc8896c0edcd652b9f70b61`.
Uncommitted work in all three original worktrees was scanned and committed before
reconciliation; backup branches preserve it. No reset, clean or worktree deletion
was used. M2 delivery evidence is recorded in `docs/M2_COMPLETION.md`.

### M2A — Authentication and API Security

- [x] Provide explicit one-time local owner bootstrap and Argon2id password verification.
- [x] Persist only hashed opaque sessions with idle/absolute expiry, rotation, logout, and revocation.
- [x] Enforce same-origin/CSRF protection, object authorization, login rate limiting, secure cookies/headers, and normalized API errors.
- [x] Emit redacted authentication/session audit events and expose only anonymous liveness.
- [x] Pass deterministic AUTH-001 through AUTH-005 tests and security boundary checks.

### M2B — Event Writer, Projections, and SSE

- [x] Normalize and validate registered event payloads, recursively redact secrets, and extract oversized content to authorized artifact metadata/storage.
- [x] Preserve globally commit-safe and per-run ordering, deduplication, append-only storage, and transactional projection watermarks.
- [x] Implement authorized replay/pagination and SSE with `Last-Event-ID`, keepalive, reset semantics, and LISTEN/NOTIFY used only as a wakeup.
- [x] Render unknown allowed event types safely and reject unsupported schema majors explicitly.
- [x] Pass deterministic EVT-001 through EVT-008 concurrency, loss, replay, redaction, and boundary tests.

### M2C — Frontend Shell and Accessibility Baseline

- [x] Build the responsive mission-control shell and required route skeletons using shared design tokens.
- [x] Establish generated API-client consumption, TanStack Query server state, ephemeral Zustand state, and login/session boundaries without browser token storage.
- [x] Provide honest loading/error/empty/demo states, sanitized Markdown, and a read-only terminal renderer.
- [x] Pass production build, type/lint/component, keyboard, screen-reader, automated accessibility, and serious-console-error checks.

### Integration-owner gates

- [x] Own all shared migrations/models, generated Python/TypeScript contracts, root lockfiles, central registries, shared Compose, and this status ledger.
- [x] Merge only milestone branches that pass their focused gates, then run the full repository verification suite from the merged branch.
- [x] Inspect the final diff and secret scan, record branch hashes/merge order/findings/evidence, and stop before M3.


### Remote completion gate

- [x] M2 integrated into main at ac6206b, confirmed by fetch; the user reports M2 complete. Earlier local push evidence below is historical.

## M1 completion criteria

- [x] Establish SQLAlchemy 2.x and Alembic with `control`, `event_store`, and LangGraph-owned schemas plus least-privilege logical roles.
- [x] Implement authoritative Pydantic IDs/statuses and versioned workflow, event, failure, command, configuration, snapshot, queue, lease, effect, and artifact contracts.
- [x] Generate deterministic TypeScript types and JSON Schema from the Python authority and enforce drift checks.
- [x] Implement the M1 relational model and transactional repositories with deterministic clock, ID, and idempotency utilities.
- [x] Enforce append-only event storage and ordering/deduplication invariants in PostgreSQL.
- [x] Bootstrap LangGraph Postgres checkpointing and prove stable-thread persistence, streaming APIs, and durable interrupt/resume behavior.
- [x] Prove PostgreSQL 16, OpenAI SDK, and React Flow compatibility for the selected pins required by ADR-022.
- [x] Pass migration up/down, constraints/race/idempotency, unit, integration, frontend, build, browser, audit, and secret gates.
- [x] Review M1; the coherent commit immediately following this status update is the milestone boundary. Stop before M2A/M2B/M2C.

## Active M0 criteria

- [x] Establish the backend, orchestrator, frontend, shared-contract, deployment, script, and test layout.
- [x] Pin a Python 3.12 and Node-compatible dependency set with reproducible lock files.
- [x] Establish formatting, linting, type checking, unit/component testing, Playwright, and production-build gates.
- [x] Add safe `scripts/dev.sh`, `scripts/demo.sh`, `scripts/verify.sh`, and `scripts/deploy-core.sh` behavior.
- [x] Add a names/safe-examples-only `.env.example` and deterministic secret scanning with a failing canary test.
- [x] Add CI using PostgreSQL 16 and the same verification entrypoint.
- [x] Prove a fresh local install can execute the empty/scaffold quality gates.
- [x] Review M0; commit is the milestone boundary immediately following this status update.

Historical M0 scope: M4 was authorized; staging/deployment and M5 were out of scope.

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

M0 provides the Python 3.12 API/orchestrator package layout, minimal Next.js shell,
exact Python/npm locks, safe scripts, CI, secret scanning, and local PostgreSQL
Compose definition. M1 adds authoritative frozen Pydantic contracts and generated
JSON Schema/TypeScript, 20 `control` tables, three append-only/ordering
`event_store` tables, LangGraph-owned checkpoint tables, logical roles, an Alembic
baseline, transactional event/command/idempotency/effect/lease repositories, and
deterministic test utilities. M2 now adds real authentication, event normalization,
authorized replay/SSE/artifact delivery and the frontend shell; the integrated
Chromium/API/PostgreSQL vertical test passes. Final full-gate and CI evidence is
recorded below and in `docs/M2_COMPLETION.md`. Reference and legacy files remain
unmodified. No deployment or homelab change has occurred.

M3 adds immutable configuration, provider routing, health and usage accounting.
M4 adds the WorkflowSpec compiler and Workflow Studio. M5 adds durable orchestration,
fenced effects, controls and recovery. M6 now exercises that real system end to end
with isolated deterministic adapters, persisted tasks/attempts, live run evidence,
durable demo decisions, network-denied browser acceptance and restart recovery.

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

M1 validation on 2026-09-07:

- Python 3.12.14 installed `requirements.lock`; `pip check` reported no broken requirements.
- Local `postgres:16.10-bookworm` reported PostgreSQL 16.10. Alembic downgrade/upgrade and metadata-drift check passed while excluding the package-owned `langgraph` schema.
- `pytest --cov`: 25 passed with 92.99% branch coverage. Tests cover constraints, immutable revisions/snapshots/published workflows, append-only events, concurrent gap-free ordering, event/command/effect/request idempotency conflicts, command sequencing/optimistic versions, lease expiry/fencing, logical-role permissions, and deterministic clocks/IDs.
- LangGraph 1.2.11 compiled/invoked and produced `astream(..., stream_mode="updates")` plus `astream_events(..., version="v2")`; `langgraph-checkpoint-postgres` 3.1.2 setup was idempotent and an interrupt survived saver closure/reopen before same-thread `Command(resume=...)` completion.
- OpenAI 3.8.0 Responses API types/client succeeded against an in-process `httpx2` 2.12.0 mock transport with no external request.
- React 19.2.8 and React Flow 12.11.6 initialized typed nodes/edge in Vitest; all three frontend tests, TypeScript, ESLint, Prettier, Next 16.3.4 production build, and the Chromium Playwright smoke/console check passed.
- JSON Schema and TypeScript generation checks passed byte-for-byte. `npm audit --audit-level=high` reported zero vulnerabilities.
- `scripts/verify.sh` passed every enabled M0/M1 gate with the disposable database configured; the secret canary was detected and the repository scan was clean.
- ADR-022 exposed one runtime contract correction: arbitrary non-empty `checkpoint_ns` is interpreted as a LangGraph subgraph path. ADR-023 reserves that field for LangGraph and uses the stable run thread ID plus immutable snapshot metadata for Jarvis correlation.
- No homelab address was contacted, no SSH was attempted, and no deployment was run.

During Prompt 01, application test/build commands were not run because the
repository contained no V1 application and that prompt forbade implementation.
Executable JSON/Markdown/Git validation was proportionate to that earlier
documentation-only milestone; the M0 application gates are recorded above.

## Next milestone

M8 remains the active milestone until its full local and exact-commit branch CI
gates pass. M9 has not started. No automatic main merge or deployment is authorized.

## Open gates and risks

The unresolved spikes in `docs/DECISIONS.md` remain implementation gates, especially legacy runner idempotency/worktree compatibility, SSE proxy behavior, deployed Ollama capabilities, GitHub credential form, and safe narrow health collection. LangGraph/checkpointer API/schema compatibility is resolved for M1 by ADR-023 and the pinned tests; M5 now covers fenced pending writes and injected checkpoint/effect crash windows. Real Worker-01, GitHub, and restart tests remain Prompt 03 gates; side-by-side deployment remains Prompt 04.

Historical M3 publication review (superseded by confirmed main/CI above): the final push was rejected before Git executed by automatic
approval review. It requires explicit approval to export the private M3 source
and history to `https://github.com/ClearPointSolutions/Jarvis-Development.git`.
No workaround was attempted. Earlier dry-run authentication also failed; that
credential issue has not been verified as resolved. GitHub CI remains unrun.
