# Jarvis V1 / Mission Control

Jarvis V1 is the durable human control plane for a LangGraph-based development
system. A configured real workflow plans tasks, dispatches an SSH coding worker,
verifies exact candidate commits in isolated containers, reviews the results,
retries failures, and integrates accepted work. PostgreSQL preserves runs,
commands, approvals, events, model receipts and checkpoints across restarts.

The integration branch is still undergoing MVP acceptance. See
[current status](docs/STATUS.md) and the [hardening matrix](docs/V1_HARDENING_MATRIX.md)
for remaining gates. Protocol tests do not establish actual model quality or
Worker-01 compatibility. The legacy prototype remains the recovery option.

## Use Mission Control

1. Install the supported dependencies and bootstrap the database and owner below.
2. Configure provider, model, route, retry, permission and worker revisions in
   the corresponding screens. Publish a workflow through Workflow Studio.
3. For real work, provision the private runtime manifest and isolated verification
   broker using [the real-runtime guide](docs/FIRST_OLLAMA_TEST.md) and
   [executor configuration](docs/VERIFICATION_EXECUTOR.md).
4. Start the API, web and separate orchestrator. Open Runs, select the project,
   published workflow and Real mode, then submit an objective.
5. Use the run view to inspect tasks, source/test/review evidence, approve a
   protected step, or pause, resume, cancel and queue follow-up instructions.
   Instructions wait for a supported, instruction-enabled planning or worker node.
6. Projects links persistent run history. Artifacts lists authorized downloads.
   Health shows database access, orchestrator heartbeats and queue/lease state.

Initial real execution supports small committed UTF-8 projects and an exclusive
compatible worker. Paid model calls remain blocked until the budget gateway is
implemented; live GitHub publication and deployment/restore acceptance are still
open. Demo mode uses the same durable runtime with deterministic dependencies.

The API enqueues work and returns 202. Run `python -m jarvis_orchestrator.main`
as a separate process with its own `DATABASE_URL` and the
`jarvis_v1_orchestrator` database role after migrations. Run
`python -m jarvis_persistence.checkpoints` once with the migration/bootstrap
database identity to create the package-owned checkpoint tables and grants.
The orchestrator has no HTTP listener and performs no schema DDL.
`JARVIS_ORCHESTRATOR_MAX_CONCURRENCY`, `GLOBAL_CONCURRENCY`, `LEASE_SECONDS`, `POLL_SECONDS`, and
`GRACE_SECONDS` (each with the same `JARVIS_ORCHESTRATOR_` prefix) configure
capacity and shutdown. See `docs/M5_COMPLETION.md` for runtime semantics and gates.

## Supported toolchain

- Python 3.12
- Node.js 20.19 or newer in the Node 20 line
- PostgreSQL 16 for integration tests
- Docker Compose v2 for the isolated local database

## Fresh checkout

```sh
python -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install -e . --no-deps
(cd web && npm ci)
```

On Windows, use `.venv/Scripts/python.exe` in place of `.venv/bin/python` and
run `npm ci` with `web` as the working directory.

Run the complete local gate with `scripts/verify.sh`. Database tests run when
`TEST_DATABASE_URL` is set; CI always supplies an isolated PostgreSQL 16 service.
After building `web`, run `scripts/demo.sh` for the local deterministic demo or
`scripts/demo.sh --e2e` for disposable browser acceptance. On Windows use
`.venv/Scripts/python.exe -m scripts.demo --e2e`. See
[M6 demo operation and boundaries](docs/M6_COMPLETION.md).
`scripts/deploy-core.sh check` performs local preflight. Deployment requires an
explicitly configured V1 target and its private configuration; it is a separate
acceptance gate, not part of the demo.

Start the disposable local PostgreSQL database and include its M1 gates with:

```sh
docker compose -f deploy/compose.dev.yml up -d --wait postgres
export TEST_DATABASE_URL=postgresql+psycopg://jarvis_v1_dev@127.0.0.1:55432/jarvis_v1_test
scripts/verify.sh
```

The Compose database uses loopback-only trust authentication and is for isolated
local testing only. Production credentials and roles are supplied outside Git.

Architecture and milestone authority lives in `docs/`. Never put secrets in the
repository or browser-visible environment variables.

## Local M2 operation

After migrations, initialize the owner explicitly on the API host:

```sh
python -m jarvis_api.auth.bootstrap --username owner
```

The command prompts twice without echoing the password. There is no public signup.
For local recovery, add `--reset-password`; this changes the existing owner's
password and durably revokes all sessions. It never creates another owner.

Set `JARVIS_PUBLIC_ORIGIN` to the exact browser origin including its port and set
the web server's `JARVIS_API_URL` to the internal API origin. For local development
these are `http://127.0.0.1:3000` and `http://127.0.0.1:8000` respectively. Start
the API with `python -m jarvis_api.main` and the web application with `npm run dev`
from `web`. Use the production build for CSP/browser acceptance checks.

Production configuration requires an HTTPS public origin, Secure cookies and a
private persistent `JARVIS_CSRF_HMAC_KEY_FILE` containing 32–4096 bytes. API database
credentials should assume the least-privilege `jarvis_v1_api` role; migrations and
owner bootstrap use the separate local administrative identity. No infrastructure
credential belongs in web configuration.

The `/runs` screen creates projects, enqueues published workflows and displays
authorized run history. Individual runs show actual/desired state, command
acknowledgements and the replayable event feed, with durable M5 controls. Worker,
provider, model, routing and policy screens provide configuration management.

With `TEST_DATABASE_URL` configured, `scripts/verify.sh` creates a fresh disposable
browser-test database, starts the actual API, exercises Chromium through the same-
origin web proxy, and drops that database afterward. It never contacts the homelab.
The proxy treats all browsers as one network source for conservative network login
limiting; account limiting remains independent. Session polling counts as request
activity, while SSE never extends session lifetime or mutates authentication state.

## M3 configuration

Use `/workers`, `/providers`, `/models`, `/routing`, and `/policies` to create,
edit, validate and inspect immutable configuration revisions. The `/registry`
page links these resources. Create a provider connection, then a model profile
referencing that connection revision, then a route referencing model revisions.
No model identifier or endpoint is an architectural default. DEMO is available
without credentials or network access.

Network-provider endpoints must be explicitly listed in the API's server-side
`JARVIS_PROVIDER_ALLOWED_ENDPOINTS` JSON array. It defaults to an empty allowlist.
Provider adapters independently require exact endpoint authorization,
disable redirects and ambient proxy credentials, and accept injected transports.
M3 tests only local mock transports; no live validation is performed by GUI/API.

Secret-reference fields accept opaque server-managed locators, never actual API
keys or file contents. References do not round-trip; the UI reports whether a
reference is configured, not whether a live provider credential has been verified.
Server-only worker deployment manifests describe future pinned-host-key SSH
configuration, while the browser sees an opaque deployment status and host label.
No SSH worker execution is implemented in M3.

Edits produce new immutable revisions; existing references remain pinned. Explicit
current disable/archive acts as a safety veto during route previews. Preview
returns candidate rejection reasons and a reproducible snapshot hash. A spend
limit can deny or produce a persisted `require_approval` decision; it does not
execute the M9 approval workflow. Unknown usage/cost is never displayed as zero.

See `docs/M3_COMPLETION.md` for API routes, adapter limitations, migration and
verification evidence.
