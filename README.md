# Jarvis V1 / Mission Control

Jarvis V1 is the durable human control plane for a LangGraph-based development
system. M2 adds durable owner authentication, redacted event replay/SSE and the
accessible Mission Control shell. Runtime execution and provider configuration
remain later milestones; the legacy prototype is unchanged.

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
`scripts/demo.sh` and `scripts/deploy-core.sh` intentionally refuse to run until
their later milestones are implemented.

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

The `/runs` screen accepts an existing run ID and displays its authorized event
projection and replayable feed. M2 deliberately provides no run-creation or
execution endpoint. Other route shells explain their upcoming milestone.

With `TEST_DATABASE_URL` configured, `scripts/verify.sh` creates a fresh disposable
browser-test database, starts the actual API, exercises Chromium through the same-
origin web proxy, and drops that database afterward. It never contacts the homelab.
The proxy treats all browsers as one network source for conservative network login
limiting; account limiting remains independent. Session polling counts as request
activity, while SSE never extends session lifetime or mutates authentication state.
