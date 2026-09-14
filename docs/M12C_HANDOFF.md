# M12B live-run handoff (needs a shell on Jarvis-Core)

M12B landed the parts that do not need interactive access to the homelab hosts
(the boundary failure-class fix, `jarvis-admin runtime build`, and real
homelab-Ollama acceptance — see `docs/STATUS.md`). This document is the
step-by-step for the remaining live run, to be executed **from a session with a
shell on Jarvis-Core `192.168.40.105`** (which holds the worker SSH key at
`/home/jarvis/.ssh/jarvis_worker` and the V1 tree at `/opt/jarvis-v1`).

Do not modify `/opt/jarvis`. Keep `StrictHostKeyChecking=yes`. Never print keys
or secrets. `github_publish` stays fail-closed. Worker `max_concurrency = 1`.

## 0. Baseline

```sh
cd /opt/jarvis-v1/src
git fetch origin
git checkout codex/m12b-real-homelab
git log --oneline -5    # boundary fix, jarvis-admin, docs
```

## 1. V1 worker wrapper on Jarvis-Worker `192.168.40.106`

The legacy OpenHands env `/opt/jarvis-worker/venv` must stay untouched. Build the
wheel from the exact checked-out revision and install it into a **separate**
wrapper venv.

```sh
# on Core, from /opt/jarvis-v1/src
python -m build --wheel        # or: pip wheel . --no-deps -w dist/
SHA=$(git rev-parse --short HEAD)
scp -i /home/jarvis/.ssh/jarvis_worker -o StrictHostKeyChecking=yes \
    dist/jarvis_v1-*.whl jarvis@192.168.40.106:/tmp/

ssh -i /home/jarvis/.ssh/jarvis_worker -o StrictHostKeyChecking=yes jarvis@192.168.40.106 '
  set -eu
  test ! -e /opt/jarvis-worker/v1-wrapper || echo "wrapper dir exists; reconcile"
  python3 -m venv /opt/jarvis-worker/v1-wrapper/venv
  /opt/jarvis-worker/v1-wrapper/venv/bin/pip install --no-cache-dir /tmp/jarvis_v1-*.whl
  test -x /opt/jarvis-worker/v1-wrapper/venv/bin/jarvis-worker-wrapper-v1
  mkdir -p /opt/jarvis-worker/persistence/v1-invocations
  chmod 0750 /opt/jarvis-worker/persistence/v1-invocations
  rm -f /tmp/jarvis_v1-*.whl
'
```

The wrapper's `OpenHandsDeployment` must set:

* `python_path = /opt/jarvis-worker/v1-wrapper/venv/bin/python` (the wrapper's own env)
* `runner_python_path = /opt/jarvis-worker/venv/bin/python` (the **legacy** runner Python — the wrapper invokes `developer_task.py` with this, never its own)
* `runner_path = /opt/jarvis-worker/developer_task.py`
* `wrapper_path = /opt/jarvis-worker/v1-wrapper/venv/bin/jarvis-worker-wrapper-v1`
* `invocation_root = /opt/jarvis-worker/persistence/v1-invocations`
* `workspace_root = /opt/jarvis-worker/workspaces`
* `venv_activate = /opt/jarvis-worker/v1-wrapper/venv/bin/activate`
* `strict_host_key_checking = yes`

Validate over SSH (health, repository inspection, start, inspect, collect,
cancel, malformed request, duplicate/idempotent invocation) with the M7
adapter's `validate()` plus the existing `tests/integration/test_m7_workers.py`
scenarios pointed at the real host, or a scripted RPC loop. Confirm the wrapper
reports its Jarvis V1 package version.

## 2. SSH worker boundary

Using `/home/jarvis/.ssh/jarvis_worker` and a pinned `known_hosts` (the Core
already trusts `192.168.40.106`), verify: hostname, Python, Git, OpenHands
runner present, workspace root writable, capacity 1, wrapper version, V1 package
revision. Keep `max_concurrency = 1`.

## 3. Ollama registry configuration

Real homelab Ollama is already accepted (see `docs/FIRST_OLLAMA_TEST.md` and
`docs/STATUS.md`). Endpoint `http://192.168.40.94:11434`. Use the model tag
selected there for organizer / architect / reviewer. Create, through the
Mission Control API (not raw SQL):

* a provider connection (`ollama`, base URL above), allowlisted in the API's
  `JARVIS_PROVIDER_ALLOWED_ENDPOINTS` **and** the runtime manifest;
* one model profile per role (or one shared profile if the selected tag meets
  the reviewer schema reliably), `structured_json = true`;
* a retry policy covering, with `max_retries > 0`,
  `provider.contract_failure`, `provider.transient`, `provider.rate_limited`,
  `infrastructure.timeout`, `infrastructure.service_unavailable`;
* a permission policy allowing `code`, `git`, `tests`;
* a route policy over the profile(s);
* a worker revision (`openhands_ssh_v1`, `max_concurrency = 1`);
* a software-development workflow (organizer → architect → worker → verify →
  reviewer → integrate → finalize, **no `github_publish` node**), published.

## 4. Runtime manifest

Assemble it with the new command instead of hand-editing:

```sh
export DATABASE_URL=<migrator or readonly URL for the V1 database>
jarvis-admin runtime build \
  --infra /opt/jarvis-v1/config/infra.json \
  --binding /opt/jarvis-v1/config/binding-acceptance.json \
  --check-registry \
  --out /opt/jarvis-v1/config/runtime.json
```

`infra.json` holds the provider config, the worker `OpenHandsDeployment` from
step 1, credential-file paths (SSH key + pinned known_hosts, both absolute),
`allowed_worker_hosts`, `source_root`, `verification_isolation`
(`broker_argv` + `image_id` from step 5), executables and git author.
`binding-acceptance.json` holds `{project_id, workflow_version_id,
worker_revision_id, worker_project, base_policy: "current", combined_commands}`.
`--check-registry` fails the build if the published workflow's worker selector,
retry classes or structured-JSON profile disagree with the manifest.

## 5. Verification executor

Use the candidate-bound isolated architecture: orchestrator → restricted broker
transport → Docker verification container from the **immutable image id** of the
exact `deploy/verification.Dockerfile` build (`docker image inspect ... .Id`),
candidate mounted read-only through the isolation contract, no network. Do not
give the orchestrator a raw Docker socket if the design separates that boundary
— set up the restricted broker account / fixed-command SSH key / `known_hosts` /
receipt directory as the current `verification/isolation_*` code requires, and
put `broker_argv` + `image_id` in the manifest. Run the denial canaries
(network attempt, authority escalation, path escape).

## 6. Disposable project + real run

Create a fresh small local repo (NOT the Jarvis repo) as the coding target, e.g.
a FastAPI app with `GET /health`, `GET /version`, pytest tests, config, README,
deterministic `python -m pytest` verification. Commit it; register it as the
project/repository with a base SHA.

Start the real stack (`compose.production.yml` + `compose.homelab.yml` per M12A;
add the orchestrator with `JARVIS_ORCHESTRATOR_RUNTIME_FILE=/etc/jarvis-v1/runtime.json`).
Log in, submit the objective through Runs in Real mode against the published
workflow. Prove the 16-step observable sequence in the M12B prompt with durable
evidence (events, artifacts, Mission Control history).

## 7. Forced retry

Word the objective so the first implementation is likely to miss one test (e.g.
"reject a negative `id` in `GET /item/{id}` with 422"), or use supported fault
injection. Capture: attempt → verification failure → classified feedback →
retry → corrected candidate → verification PASS → review PASS → integration.
The M12B boundary fix means an escaped worker/infra boundary now retries per
policy instead of hard-blocking; confirm that path if it occurs.

## 8. Restart recovery

Between/within stages, restart `api`, `web`, and `orchestrator` (never Postgres,
never `-v`). After each: no duplicate billed/model effect, no duplicate worker
launch, lease fencing intact, history correct, SSE/UI reconnects, run resumes or
is truthfully blocked/recoverable.

## 9. Record

Update `docs/STATUS.md`, `docs/V1_HARDENING_MATRIX.md`,
`docs/LOCAL_MVP_MATRIX.md`, `docs/FIRST_OLLAMA_TEST.md`, `docs/WORKER_PROTOCOL.md`,
`docs/VERIFICATION_EXECUTOR.md` with: model tag, wrapper version/paths,
verification image id, objective, real run id, final result, retry evidence,
restart evidence. Run the full unchanged `scripts/verify.sh`. Commit, push,
check exact-commit CI.
