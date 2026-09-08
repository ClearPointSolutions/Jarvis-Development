# Jarvis V1 Side-by-Side Deployment Plan

Status: architecture plan only; this document does not authorize deployment in the architecture turn.

## 1. Boundaries

- Target Core host: configured value initially corresponding to Jarvis-Core (`192.168.40.105`).
- Target Worker host: configured value initially corresponding to Jarvis-Worker-01 (`192.168.40.106`).
- V1 root: `/opt/jarvis-v1`.
- Legacy root: `/opt/jarvis`; it MUST NOT be overwritten, renamed, stopped, deleted, mounted writable, or migrated during V1 development/staging.
- No DNS/reverse-proxy switch or production promotion occurs until an explicit later authorization.
- All addresses, ports, paths, model endpoints, keys, and credentials are runtime configuration; the values above are inventory, not source-code constants.

## 2. Repository/deploy layout

```text
/opt/jarvis-v1/
  current/                    # deployed immutable release checkout/bundle
  releases/<release-id>/      # optional atomic release directories
  deploy/                     # compose and non-secret config
  secrets/                    # operator-provisioned, untracked, restrictive modes
  data/
    postgres/                 # dedicated V1 database volume
    artifacts/                # V1 artifact store
    backups/                  # access-controlled logical backups/manifests
  logs/                       # only if not using container logging; redacted
  .env                        # runtime-only non-secret/secret refs; never committed
```

The repository will provide `deploy/`, `.env.example`, and scripts, but not real `.env`, keys, known-host contents, tokens, passwords, database dumps, or captured production logs.

## 3. Compose services

| Service | Responsibility | Exposure/mounts |
|---|---|---|
| `jarvis-v1-web` | Next.js production server | private/loopback ingress port; no secrets or host mounts |
| `jarvis-v1-api` | FastAPI auth/control/query/SSE | internal network, reached through same-origin proxy; session secret and artifact read access |
| `jarvis-v1-orchestrator` | queue, LangGraph, adapters, health | no public port; provider/GitHub/SSH secret refs, artifact read/write |
| `jarvis-v1-postgres` | dedicated PostgreSQL state/events/checkpoints | internal only or loopback admin binding; `/opt/jarvis-v1/data/postgres` |
| optional `jarvis-v1-proxy` | TLS and same-origin routing if no existing private proxy is used | one configured LAN/VPN port; certificate mounts only |

Names, networks, volumes, ports, database name/user, and health checks use a `jarvis-v1` prefix and cannot collide with legacy `jarvis-postgres` or its port/volume. V1 never connects to the legacy database unless a future explicit read-only migration is approved.

No service mounts the Docker socket. Health collectors use narrow OS/provider endpoints or a separately hardened exporter if needed.

## 4. Configuration and secrets

`.env.example` will document, without values:

- public origin, bind addresses, trusted proxy/CIDR, TLS mode;
- V1 database name/user/password-file reference;
- session/CSRF secret-file references and owner bootstrap controls;
- artifact root/limits;
- orchestrator concurrency/lease/heartbeat settings;
- Worker-01 host/user/port, pinned known-hosts file, key file, runner/workspace/invocation paths;
- Ollama endpoint and profile names;
- OpenAI secret reference and optional enablement;
- GitHub organization/repository allowlist and credential reference;
- retention, log level, demo enablement, and feature flags.

Secret files are provisioned manually/through operator automation beneath the V1 secret root with least ownership/mode and mounted read-only only into the consuming service. Compose variable interpolation and diagnostic output are checked so values cannot be printed. The existing `/opt/jarvis/secrets/github.env` may be referenced read-only by an explicitly configured staging adapter if authorized; it is never copied into the repo, image, browser, or V1 data.

## 5. Network plan

- Default access is LAN/VPN LAN only. Firewall/reverse proxy admits the configured private ranges.
- Browser sees one HTTPS origin; `/api/` and SSE proxy to the API with buffering disabled for the event stream and suitable idle timeout/keepalive.
- API, orchestrator, and PostgreSQL use a private Compose network. Orchestrator alone needs outbound SSH/provider/GitHub access.
- PostgreSQL is not exposed on LAN; optional maintenance binding is `127.0.0.1` on a non-conflicting configured port.
- Worker SSH and Ollama egress are limited to configured endpoints. Internet egress for OpenAI/GitHub is explicit.

## 6. Image and release construction

1. CI runs the whole-project gate and secret/dependency scans.
2. Build reproducible web/API/orchestrator images from pinned lockfiles/base digests using non-root runtime stages.
3. Label images with Git SHA, build time, schema compatibility, and workflow compiler version. No build secret remains in a layer.
4. Generate a release manifest containing image digests, migration head, required variables, compatibility range, and checksums.
5. Transfer/pull the immutable release to `/opt/jarvis-v1`; never build from or write to `/opt/jarvis`.

## 7. Migration strategy

V1 starts with a fresh dedicated database. Alembic owns application schemas. The LangGraph checkpointer setup/migration path is pinned and tested separately.

For upgrades:

1. Back up V1 database and artifact manifest; verify backup readability.
2. Put orchestrator in drain mode: stop claiming new runs and reach checkpoints/safe boundaries.
3. Apply backward-compatible expand migrations with the dedicated migrator role.
4. Start compatible new API/orchestrator, run health/smoke and checkpoint-resume tests.
5. Perform backfill via resumable recorded jobs where needed.
6. Contract/remove fields only in a later release after all running/rollback versions no longer depend on them.

Published workflow specs/events/config snapshots remain immutable. Readers use upcasters. No migration rewrites event history.

## 8. First staging deployment procedure

This sequence belongs to Prompt 04 after local and homelab integration gates pass:

1. Confirm repository clean, approved commit/tag, release manifest, `scripts/verify.sh`, production builds, and no tracked secrets.
2. Resolve and print canonical target paths; fail unless every V1 write target is under `/opt/jarvis-v1`. Check legacy service/path status read-only and record it.
3. Create V1 directories with restrictive ownership. Provision non-secret config and secrets out of band.
4. Validate compose config with redacted output; verify service/port/volume names do not collide.
5. Start V1 PostgreSQL only, wait for health, apply migrations, and validate database roles.
6. Start API and orchestrator, then web/proxy. Check liveness, readiness, authentication boundary, SSE headers, and service logs for serious errors/secrets.
7. Bootstrap/login owner through the approved mechanism.
8. Run harmless deterministic demo E2E.
9. Run real Worker-01 staging E2E, harmless approval interrupt/resume, provider health, and configured GitHub test against a disposable private repository.
10. Restart API during SSE and orchestrator during a checkpointed/waiting run; confirm history/resume.
11. Record service status, URLs, image/migration versions, exact tests, and rollback command in `docs/STATUS.md`/deployment report.

No switch from legacy occurs.

## 9. Worker-side staging

The initial adapter validates the existing runner and paths read-only. If the durable V1 compatibility wrapper is deployed, it lives in a configured V1-specific Worker-01 directory and calls the unchanged `/opt/jarvis-worker/developer_task.py`. Deployment verifies target containment, existing-file non-overwrite, file hashes, permissions, and rollback. The wrapper stores invocation metadata under a V1-specific persistence directory and no secret content.

Worker staging starts with `max_concurrency=1`. It increases only after isolated worktrees, invocation idempotency, cancel targeting, and merge serialization pass acceptance tests.

## 10. Health checks and operations

- Web liveness: process serves static/app route; readiness includes API-origin config.
- API liveness: event loop; readiness: database migrations/current connection and event writer.
- Orchestrator liveness: process; readiness: database, compiler registry, lease heartbeat, mandatory adapters configured. Optional OpenAI absence is degraded, not global failure.
- PostgreSQL: `pg_isready` plus migration/schema checks.

Compose uses `unless-stopped`, bounded health intervals, log rotation, graceful shutdown, and resource reservations/limits. Orchestrator shutdown drains new claims, records lease state, and checkpoints at safe boundaries within a deadline.

## 11. Backup and restore

- Scheduled logical/physical backup policy covers the dedicated V1 database; artifact manifests and content are backed up consistently.
- Encryption/access/retention are operator-configured outside Git.
- Restore is tested into an isolated database/artifact root and verifies event integrity hashes, configuration snapshots, checkpoint linkage, artifact digests, login reset procedure, and historical playback.
- A database restore and artifact snapshot identify the same backup watermark. Missing artifact content is surfaced, not hidden.

## 12. Rollback

Because legacy stays live and untouched, platform rollback is:

1. stop only the `jarvis-v1-*` Compose project/services using the exact V1 compose/project name;
2. leave V1 data intact for diagnosis;
3. continue using existing `/opt/jarvis` services;
4. if rolling back a V1 release while retaining V1 service, restore the prior compatible image manifest only when its declared database schema compatibility permits it; otherwise restore the matching V1 backup to a new isolated data directory.

The deployment script MUST print the exact non-destructive V1-only rollback command before applying changes. It never uses a broad recursive delete. Promotion/DNS switch and permanent V1 data cleanup require separate approval.

## 13. Promotion criteria

Promotion is out of scope until all acceptance tests pass on real staging; V1 has run reliably for an agreed observation window; security/residual worker risks are reviewed; backup restore succeeds; operator runbook and rollback are rehearsed; and the user explicitly authorizes traffic/DNS changes. Even promotion does not imply deleting legacy.

## M7 worker package staging plan

The [versioned compatibility wrapper](../worker-wrapper/v1/README.md) documents
checksum verification, a separate Python environment, immutable revision binding,
independently pinned host keys, protected invocation storage and the later staging
test sequence. This is documentation only. M7 local validation does not deploy or
contact any homelab service, and preserves the existing runner and environments.
