# Phase 0 real-execution acceptance

This is an evidence procedure, not a claim that the homelab passed. Run it only
from an authorized Jarvis-Core shell against `/opt/jarvis-v1`; never use
`/opt/jarvis` or the Jarvis repository as the coding target.

## 1. Record immutable inputs

```sh
cd /opt/jarvis-v1/src
git fetch origin
git rev-parse HEAD
git status --short
docker compose --project-name jarvis-v1 --env-file /opt/jarvis-v1/shared/homelab.env \
  -f deploy/compose.production.yml -f deploy/compose.homelab.yml images
docker image inspect "$JARVIS_VERIFICATION_IMAGE" --format '{{.Id}}'
scripts/start-real-orchestrator.sh --mode homelab \
  --env-file /opt/jarvis-v1/shared/homelab.env --validate-only
```

Save the manifest SHA-256, V1 commit, image IDs, wrapper and runner paths, worker
revision, requested model profile/tag and each separately observed runtime
identity. Never label a requested model as observed.

## 2. Create the disposable committed target

```sh
scripts/prepare-phase-00-project.sh /opt/jarvis-v1/acceptance/phase-00-project
```

Register that repository/project through Mission Control. Use its printed SHA as
the initial base and the published software-development workflow bound in
`runtime.json`. Do not edit the base SHA between the two jobs.

## 3. Start and submit through the normal boundary

```sh
scripts/start-real-orchestrator.sh --mode homelab \
  --env-file /opt/jarvis-v1/shared/homelab.env
```

Sign in through Mission Control and submit a REAL job through the normal Runs
UI/API. Record project, job, run, task, attempt, node execution, worker
invocation and effect IDs. The event/evidence record must show planning, worker
dispatch, source export/import, isolated deterministic verification, independent
review and accepted local integration.

For the mandatory forced retry, use only the checked-in protocol acceptance
fixture (`tests/fixtures/runtime-worker/runner.py`) or an explicitly configured
equivalent fault boundary that makes attempt 1 write `ANSWER = 0` and attempt 2
write `ANSWER = 42`. Do not rely on prompt wording. Required evidence is
`test.failed` plus `failure.classified=code.test_failure`, a later attempt whose
request contains the feedback artifact, then test/review/integration success.
The fixture-based result must be labelled FIXTURE VERIFIED, never LIVE VERIFIED.

Submit the continuation objective `Extend completed project`. It must start from
the accepted current source automatically, preserve the first job's file/tree,
and produce a descendant accepted integration commit.

## 4. Recovery and control matrix

Restart API and web during event viewing; reconnect must replay from the durable
cursor. Restart the orchestrator once during a safe boundary, then simulate an
outage longer than `JARVIS_ORCHESTRATOR_LEASE_SECONDS`. Record old/new lease
generations and worker invocation identity. There must be one launch; an unknown
remote result must remain reconciliation-required.

With the provider endpoint unavailable, issue pause and cancel through the
authenticated command API/UI. Command application must not call the provider
probe. Cancellation may report `unknown`; it must never infer that an
unreachable worker stopped.

Never restart PostgreSQL with volume deletion. Never run `compose down -v`.

## 5. Automated fixture gate

The normal PostgreSQL/protocol gate provides deterministic, non-homelab evidence:

```sh
docker compose -f deploy/compose.dev.yml up -d --wait postgres
export TEST_DATABASE_URL=postgresql+psycopg://jarvis_v1_dev@127.0.0.1:55432/jarvis_v1_test
export TMPDIR=/short/path/on/windows
scripts/verify.sh
```

`tests/integration/test_real_entrypoint.py` is the executable forced-failure,
continuation, source-transfer, review and integration procedure. Recovery,
commands, receipts, approvals and isolation remain covered by their dedicated
integration suites. Shell HTTP behavior is exercised by
`tests/deploy/test_http_probe.py` on Linux/CI.

## 6. Evidence record

For each action record UTC time, expected outcome, observed outcome, run/effect
identities, source and integration SHAs, artifact hashes, model request identity,
observed provider response identity where available, wrapper version/path,
worker host-key fingerprint, verification image ID, and whether evidence is
FIXTURE, LOCAL, CI or LIVE. A short observation is not a soak test.
