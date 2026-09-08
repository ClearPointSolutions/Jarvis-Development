# M6 deterministic demo vertical slice

Status: local acceptance verification complete. Exact-commit
branch CI is required before COMPLETE / READY FOR M7. M7 has not started.

## Source and scope

Base: `26fcdc5694f73adaf864227dd21579b3a61f6033`, fetched clean main after
M5 branch `9ad204ccaeeb3199c2cc30c2ab0c29264501048a` passed
[verify 34180910635](https://github.com/ClearPointSolutions/Jarvis-Development/actions/runs/34180910635),
[PR #2](https://github.com/ClearPointSolutions/Jarvis-Development/pull/2) merged,
and main passed [verify 34181196662](https://github.com/ClearPointSolutions/Jarvis-Development/actions/runs/34181196662).
M6 branch: `codex/m6-deterministic-demo`. Final source SHA and CI evidence are
recorded when publication verification completes.

No homelab contact, SSH, production provider credentials, runtime GitHub calls,
deployment, production approval authorization, legacy edits, or M7 work occurred.
Development Git/GitHub access is used only to publish and verify this branch.

## Architecture

Authentication, CSRF, owner authorization, enqueue, PostgreSQL, M5 claim/lease
fencing, M4 WorkflowSpec validation/compiler, PostgresSaver, effects, retries,
structured events, immutable artifacts, SSE, and browser rendering are real.
`JARVIS_ORCHESTRATOR_RUNTIME_MODE=demo` binds an explicit type allowlist to the
existing EffectLedger. It refuses real-mode runs and non-demo immutable provider
or worker revisions. No alternate graph engine or browser execution timer exists.

The Organizer and Architect invoke the existing normalized M3 DemoAdapter;
Organizer bounds and normalizes the objective and Architect persists two weighted
tasks with a dependency. DEV-001 implements a greeting and DEV-002 documents it.
The worker emits bounded command/file activity and immutable source artifacts
without executing shell text. Verifier and Reviewer bind their reports to the
current attempt snapshot digest. Feedback survives in checkpoint channels and
report artifacts. The reusable WorkerAdapter and PublicationAdapter runtime
protocols use M5 dispatch/inspect/cancel identities; M7's external transport and
worker-side invocation protocol remain future work.

Canonical workflow `demo-m6-canonical`, initially published version 1:
Organizer → Architect → Dispatch → Developer → Verify → Reviewer → Integrate →
Dispatch; after tasks finish, final Verify → final Review → DEMO decision →
DEMO publication → Finalize. The explicit final evidence nodes also close the
zero-task static path. The browser test edits and publishes version 2 through
Workflow Studio before running it. Retry edges are validated WorkflowSpec data.

Canonical attempt 1 fails `code.test_failure`, consumes one of two semantic
retries, and succeeds on attempt 2. Separate infrastructure, reviewer, and
provider fixtures consume their respective existing M5 retry classes. Rejecting
the demo decision finalizes cancelled with no publication. Publication records
a deterministic DEMO identity, pending then success/failure CI, and final artifact.
Seed 6 and UTC clock 2026-01-01 are defaults; delays, scenario, health, and CI are
bounded typed controls. Runtime UUIDs and recorded timestamps remain genuine.

The decision is a durable LangGraph interrupt with owner/CSRF/version/idempotency
checks. It authorizes only a local simulated publication, never a protected real
effect. M9 approval grants, policy decisions, and production security are not
implemented or implied.

Effects, task attempts, artifact metadata, and normalized M3 usage accounting
share one fenced transaction. Reconstruction inspects the committed receipt
before dispatching again. Accounting uses estimated fixture tokens and ordinary
pricing/cost validation, with no invented real spend. No migration is needed;
migrations 0001–0006 remain unchanged.
Linked whole-run retries retain the selected demo fixture while clearing transient
wait/execution state; the existing RUN-009 history test covers this boundary.

## Running locally

Install the locked Python dependencies in `.venv`, Node 20.19, `npm ci` in `web`,
and Chromium (`npx playwright install chromium`). Use a local PostgreSQL 16 with
the existing logical roles from `deploy/postgres/init/001_roles.sql`; the existing
local development Compose service is suitable. Build with `npm run build` in web.
Set `TEST_DATABASE_URL` to a disposable loopback PostgreSQL administration URL
(the default uses 127.0.0.1:55432 and jarvis_v1_dev).

- Interactive: `scripts/demo.sh` (or `.venv/Scripts/python.exe -m scripts.demo`
  on Windows). Enter a local demo password at the private terminal prompt.
- Automated: `scripts/demo.sh --e2e` / `python -m scripts.demo --e2e`.
- Full gates: `TEST_DATABASE_URL=... scripts/verify.sh`, which also runs M6 E2E.

Open http://127.0.0.1:3000 and log in as `demo-owner`. Create a project, choose
the DEMO workflow and scenario, and enter "Build a greeting fixture". All workers,
provider/profile/route/retry/permission revisions and the workflow are bootstrapped
idempotently through the real service layer. Interactive data survives restarts
in `jarvis_demo_local`. E2E creates and drops only its own randomly named
`jarvis_demo_<uuid>` database. Local logs/artifacts are under ignored `.tmp`.

## Isolation and security

The launcher refuses non-loopback/non-disposable database names, repository
or web `.env*` files (except the example), and explicitly real runtime mode.
Child environments are allowlisted;
production provider tokens, secret refs, endpoints, tracing configuration and
deployment credentials are not inherited. An empty dedicated `PGPASSFILE` prevents
implicit personal PostgreSQL credential lookup. No resolver or network adapter is
constructed by the demo binding. Immutable snapshots are checked again at start
and dispatch, including loopback Ollama rejection.

API and orchestrator install an irreversible Python audit guard: only the
configured loopback PostgreSQL TCP port is allowed; external DNS, datagrams,
other local service ports, subprocesses and shell calls are denied. The guard is
installed after asyncio's Windows wake-up sockets are created. Psycopg's native
transport is limited by the validated local database URL. Playwright intercepts
and permits only the browser's local app origin, including its exact port. This is strict application-level test
interception, not an OS sandbox for executing arbitrary hostile native code;
the demo never loads such code. Tests attempt forbidden internet/Ollama/SSH
destinations and complete the actual browser flow with interception enabled.

Synthetic worker-output secret canaries exercise the real artifact redaction
boundary. Existing owner, CSRF, IDOR, XSS, immutable event, fencing, migration and
secret-scan gates remain enabled. No hidden reasoning or raw shell endpoint exists.

## UI and evidence

`/runs` creates objectives and chooses an explicit DEMO scenario; `/runs/{id}`
loads the published workflow and persisted node attempts, task weights, retries,
health, model usage, decisions, artifacts and final summary. SSE invalidates
authoritative query data. Graph edges reflect `graph.route_selected` events;
graph presentation never mutates runtime state. Activity supports event-type
filtering and a bounded recent-event window. Evidence panels read persisted
history independently of that window. Artifact links use the existing authorized
M2 download endpoint.

Primary browser acceptance includes real registry revision edits, Workflow Studio
publication, objective/start, queue receipt, task/retry/graph/feed, API and
orchestrator restart at the decision, reconnect, approve, completion, another
restart and historical artifacts/attempts. It also runs infrastructure recovery,
rejection and a second canonical fixture with an identical normalized event and
route sequence. Python tests reconstruct at the post-dispatch/pre-checkpoint
crash boundary and compare independent canonical histories. Browser axe,
page/console errors, and external request attempts must all remain empty.

Current local evidence: 593 Python tests pass with 88.82% combined coverage
(91.61% statements; 78.78% branches), including migration round-trip/drift/roles,
all M0–M5 regressions and eight M6 PostgreSQL acceptance tests. All 49 frontend
tests pass. Clean npm installation/audit reports zero vulnerabilities. Generated
schema, integrated OpenAPI and both TypeScript artifacts pass drift checks;
strict Python/TypeScript, formatting, lint, production build and secret scans pass.

The expanded M6 browser acceptance passed four runs in one real process-based
test: canonical, identical canonical repeat, infrastructure recovery and reject.
It reports zero axe violations, serious console/page errors or external requests.
Visual review improved graph ordering, task/usage readability and activity-filter
spacing. The complete PostgreSQL-enabled `scripts/verify.sh` passed, including
all nine foundation browser tests and M6 acceptance (four runs; 2.9 minutes).
Exact-commit GitHub CI remains the publication gate.
The first branch CI run (34187988596) passed all 593 Python tests at 88.89%
combined coverage and the original 48 frontend tests, then exposed a Workflow
Studio keyboard/layout race. Node position and viewport callbacks now use
functional state updates so a viewport event cannot restore stale positions.
A focused regression covers callbacks arriving before a render, and the browser
gate retains its exact five-pixel keyboard movement and mouse-drag assertions.
The second CI run also exposed deferred React Flow selection during keyboard
movement and Linux graceful shutdown waiting on live SSE clients. The canvas now
moves the focused node directly with bounded layout updates and a screen-reader
announcement, while retaining native selection/deletion keys. The demo launcher
allows three seconds of graceful shutdown before killing its own child process;
this exercises durable crash recovery instead of waiting indefinitely for SSE.
The dedicated empty PostgreSQL password file uses mode 0600 on Unix.
The post-review linked-retry correction also passed all three affected control
integration tests plus strict types/lint. Cold SSE replay retains authorization
for every frame; browser acceptance allows at most 30 seconds to catch up to the
persisted publication event after a complete service restart.

Windows verification uses dedicated `PYTEST_ADDOPTS` basetemp/cache and
`COVERAGE_FILE` paths under ignored `.tmp`. The desktop sandbox and ordinary user
have different ACLs on the default shared pytest directory; the first elevated
full-script attempt failed during fixture setup there. No test was disabled or
coverage threshold lowered. A later check caught a stale generated API path-type
artifact; it was regenerated, and all contract drift checks now pass.

## Deliberate limits

The repository fixture is an in-memory deterministic source snapshot sealed in
artifacts; verification does not run untrusted user code. Health is a controlled
demo observation, not a host probe. The local decision is not M9 authorization.
The history UI bounds event/node/task pages for this small fixture; arbitrary
large-run history exploration and complete dashboards belong to later milestones.
M7, M8, M9, production integration, and staging deployment remain unstarted.
