# Jarvis V1 / Mission Control

Jarvis V1 is the durable human control plane for a LangGraph-based development
system. The current implementation scope is the repository foundation and durable
contracts; the legacy prototype remains untouched under `docs/reference/legacy/`.

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

Architecture and milestone authority lives in `docs/`. Never put secrets in the
repository or browser-visible environment variables.
