# Jarvis V1 deployment runbook

Operator procedures for standing up and maintaining a Jarvis V1 / Mission
Control Core machine. This is the authoritative how-to; `docs/DEPLOYMENT_PLAN.md`
holds the architecture rationale.

The legacy `/opt/jarvis` installation is never touched by anything here. No
command runs `docker compose down -v`, deletes a data volume, or promotes over
legacy.

## Lifecycle entry points

| Task | Command | Notes |
| --- | --- | --- |
| First install (homelab) | `scripts/install-homelab.sh` | Directories, secrets, env file, images, DB, migrations, API, web, readiness. |
| First install (production) | `scripts/install-homelab.sh --mode production` | Same steps; keeps production mode, HTTPS origin, Secure cookies, loopback ports. Does not configure TLS. |
| Secret provisioning | `python3 scripts/provision_secrets.py --secret-dir <dir>` | Idempotent; run standalone or via the installer. POSIX only. |
| Preflight / config validation | `scripts/preflight.sh --mode <mode> --env-file <file>` | PASS/FAIL/SKIP per check; also `scripts/deploy-core.sh preflight`. |
| Create / recover the owner | `scripts/owner-bootstrap.sh --env-file <file> [--homelab]` | Wraps the `owner-bootstrap` Compose service (migrator identity). |
| Promote a new immutable release | `scripts/deploy-core.sh deploy` | SSH release swap on an already-provisioned target. |
| Roll back a release | `scripts/deploy-core.sh rollback` | Switches to `previous`; refuses a schema downgrade. |
| Backup | `scripts/backup-v1.sh` | Quiesced DB + checkpoints + artifacts + source. |
| Restore | Manual, see [Restore](#restore) | Not scripted in M12A. |

## Secret model

`deploy/compose.production.yml` mounts five file-backed secrets, read-only, into
only the service that consumes each:

| File | Consumer | Length |
| --- | --- | --- |
| `bootstrap_password` | Postgres superuser + `scripts/bootstrap_database.py` | 24–1024 |
| `migrator_password` | `alembic upgrade` / checkpoint bootstrap / `owner-bootstrap` | 24–1024 |
| `api_password` | `jarvis_v1_api_login` | 24–1024 |
| `orchestrator_password` | `jarvis_v1_orchestrator_login` | 24–1024 |
| `csrf_key` | `JARVIS_CSRF_HMAC_KEY_FILE` | 32–4096 |

`scripts/provision_secrets.py` creates the directory and every file, generates
values with the `secrets` module inside those bounds, and sets **owner `10001`,
group `10001`, mode `0600`** (directory `0700`). That UID/GID is what
`deploy/python.Dockerfile` runs as; outside Swarm, Docker Compose bind-mounts a
secret file with its host ownership, so a root-owned `0600` file would be
unreadable to the container. The script is idempotent (an in-range value is
kept, only its metadata repaired), refuses a symlink or a non-regular file, and
refuses to overwrite an out-of-range value without `--force`. It never prints a
value. Ownership changes need root; run the installer with `sudo`.

`scripts/preflight.sh` and `scripts/install-homelab.sh` both call
`provision_secrets.py --check`, which fails with a specific reason
(missing / not-a-regular-file / group-readable mode / wrong owner / length) so a
misconfigured secret is never reported as a generic "startup failed".

## Homelab first install (trusted private LAN, HTTP)

Prerequisites on a clean Ubuntu 24.04 Jarvis-Core: Docker Engine + the Compose
v2 plugin (**≥ 2.24**, for the `!override` merge), `git`, `python3`, `openssl`,
and this repository cloned somewhere under a path that is **not** `/opt/jarvis`.

```sh
sudo scripts/install-homelab.sh \
  --root /opt/jarvis-v1 \
  --lan-origin http://192.168.40.105:13000
```

What it does, in order (each step is labelled in the output):

1. validate prerequisites (Docker, Compose ≥ 2.24, daemon, tools);
2. validate repository state (records HEAD; warns on a dirty tree);
3. create `/opt/jarvis-v1/{shared,secrets,config}`, refusing any path that
   resolves inside `/opt/jarvis`;
4. `provision_secrets.py` + `--check`;
5. write `/opt/jarvis-v1/shared/homelab.env` from the detected/`--lan-origin`
   value (never overwrites an existing file without `--force-env`);
6. build `jarvis-v1-python:local-<sha>` and `jarvis-v1-web:local-<sha>` unless
   `--python-image` / `--web-image` immutable refs are supplied, and record the
   resolved refs back into the env file;
7. `docker compose ... config --quiet` on the merged
   production + homelab model;
8. `up -d --wait postgres`;
9. `run --rm bootstrap` (creates the `jarvis_v1_migrator/api/orchestrator`
   roles and their logins, sets database ownership, revokes PUBLIC);
10. `run --rm migrate` (`alembic upgrade head` then
    `python -m jarvis_persistence.checkpoints`);
11. `up -d --wait api`;
12. `up -d --wait web`;
13. verify readiness: API `/health` 200, the web port answers, and
    `GET /api/v1/session` through the web app returns **401** (the proxy reached
    the API). A 503 means the web app has no `JARVIS_API_URL`; a 502 means it
    cannot reach the API.

Then create the owner:

```sh
scripts/owner-bootstrap.sh --env-file /opt/jarvis-v1/shared/homelab.env --homelab
```

and sign in at `http://192.168.40.105:13000`.

The homelab overlay (`deploy/compose.homelab.yml`) changes exactly two things
against production: the web port is published on `0.0.0.0` (LAN) instead of
loopback, and the API runs `JARVIS_ENV=development` with
`JARVIS_COOKIE_SECURE=false` because the LAN transport is intentionally HTTP.
The API maintenance port stays on loopback. Nothing else is relaxed.

## Production first install (reverse proxy, HTTPS)

```sh
sudo scripts/install-homelab.sh --mode production \
  --root /opt/jarvis-v1 \
  --lan-origin https://jarvis.your-domain.example \
  --python-image <registry>/jarvis-v1-python@sha256:... \
  --web-image <registry>/jarvis-v1-web@sha256:...
```

Same 13 steps, but `compose.homelab.yml` is not layered in, so:

* `JARVIS_ENV=production`, `JARVIS_COOKIE_SECURE=true`, and the config validator
  requires an `https://` `JARVIS_PUBLIC_ORIGIN` and a CSRF key file;
* the web (`127.0.0.1:13000`) and API (`127.0.0.1:18000`) ports stay on
  loopback.

The installer does **not** terminate TLS. Front the loopback ports with the
reviewed proxy in `deploy/reverse-proxy.nginx.conf.example`, whose `server_name`
and certificate paths you replace. `JARVIS_PUBLIC_ORIGIN` must equal the origin
the browser uses at the proxy.

Owner creation is the same command without `--homelab`:

```sh
scripts/owner-bootstrap.sh --env-file /opt/jarvis-v1/shared/production.env
```

## Owner bootstrap

The first `control.users` row needs an identity with `INSERT` on that table. The
least-privilege `jarvis_v1_api_login` deliberately does not have it (regression:
`tests/integration/test_00_migrations.py`,
`tests/integration/test_bootstrap_identity.py`). The `owner-bootstrap` Compose
service therefore runs `python -m jarvis_api.auth.bootstrap` **as
`jarvis_v1_migrator_login`** through the container entrypoint, which resolves
`DATABASE_URL` from the mounted migrator password file. `docker compose exec api`
would skip that entrypoint and use the wrong identity, so it is never the
supported path.

```sh
# interactive password prompt (default)
scripts/owner-bootstrap.sh --env-file <file> [--homelab]

# non-interactive: mount a host password file (must not be a symlink)
scripts/owner-bootstrap.sh --env-file <file> [--homelab] \
  --password-file /path/to/owner_password

# local recovery: reset the existing owner's password, revoke every session
scripts/owner-bootstrap.sh --env-file <file> [--homelab] --reset-password
```

The command enforces the password policy, creates exactly one owner, refuses a
duplicate bootstrap (`Owner bootstrap refused: owner bootstrap has already
completed`), records `auth.owner_bootstrapped` (and `auth.session_revoked` /
`auth.owner_password_reset` on reset), and never echoes the password.

## Preflight

```sh
scripts/preflight.sh --mode homelab --env-file /opt/jarvis-v1/shared/homelab.env
# add --runtime to force the live checks even if the stack looks stopped
```

Checks: Docker + daemon, Compose version, the env file exists and is
`KEY=value`, the secret and config directories exist, `provision_secrets.py
--check`, `docker compose config` validity, `JARVIS_API_URL=http://api:8000`,
exactly one web port mapping, the mode-appropriate `JARVIS_ENV` /
`JARVIS_COOKIE_SECURE` / origin scheme / port bind, image refs resolve, and —
when the stack is running — PostgreSQL reachability, the schema revision matches
the code pin, API `/health`, the web port, and `/api/v1/session` → 401.

## Release promotion and rollback

`scripts/deploy-core.sh` is **only** release promotion over SSH to a target that
already completed a first install and has
`/opt/jarvis-v1/shared/deployment.env`.

```sh
JARVIS_DEPLOY_TARGET=jarvis@core.lan \
JARVIS_DEPLOY_KEY=~/.ssh/jarvis_v1_deploy \
JARVIS_DEPLOY_KNOWN_HOSTS=~/.ssh/jarvis_v1_known_hosts \
scripts/deploy-core.sh deploy      # transfer a committed archive, swap `current`
scripts/deploy-core.sh rollback    # swap back to `previous`; refuses a schema downgrade
scripts/deploy-core.sh check       # local preflight, contacts nothing
```

Host-key verification is strict (`StrictHostKeyChecking=yes`, pinned
`UserKnownHostsFile`); the script prints the exact non-destructive V1-only
rollback command before changing anything and never uses a recursive delete.

## Backup

```sh
scripts/backup-v1.sh   # on the Core host, against the `current` release
```

Stops `api` and `orchestrator`, `pg_dump --format=custom` of `jarvis_v1`
(including the `langgraph` checkpoint schema), tars the `artifacts` and `source`
volumes, writes `SHA256SUMS`, then restarts the services.

## Restore

Not scripted in M12A. Manual outline, into an **isolated** data directory, never
over a live volume:

1. `scripts/backup-v1.sh` first if the current data is still wanted.
2. Create a fresh data directory / a throwaway Compose project name.
3. `pg_restore --no-owner` the dump into a fresh `jarvis_v1` owned by
   `jarvis_v1_migrator_login`; untar `artifacts` and `source`.
4. Verify against `SHA256SUMS`; check the schema revision matches a release's
   pin; confirm event integrity and that a login works via
   `scripts/owner-bootstrap.sh --reset-password`.
5. Only then repoint the real project at the restored data.

Row P of `docs/V1_HARDENING_MATRIX.md` tracks turning this into a tested script.

## What is out of scope here

The orchestrator (`docker compose up -d orchestrator`) needs a private
`runtime.json` under `JARVIS_PRIVATE_CONFIG_DIR` describing the worker, provider
allowlist and verification commands — see `docs/FIRST_OLLAMA_TEST.md`. The
installer creates the directory but does not start the orchestrator. GitHub
publication is excluded from V1.
