# Controlled first Ollama test

The complete local verification gate and the exact-commit CI both pass, and a
live local Ollama has been exercised through the real planning and review
contracts. This is still not a deployment runbook: no homelab target has been
supplied or contacted, live paid-provider execution is untested, and GitHub
publication is excluded from this MVP.

## Authoritative configuration

1. Use Python 3.12, PostgreSQL 16 and Node 20.19 or later **within Node 20**.
2. Create immutable registry provider, model, route, retry, permission and worker
   revisions, then publish a workflow. The API's
   `JARVIS_PROVIDER_ALLOWED_ENDPOINTS` is a JSON array of exact provider base URLs.
3. Real startup requires `JARVIS_ORCHESTRATOR_RUNTIME_FILE`, a private JSON file
   validated by `RealRuntimeConfiguration`. Its `workflows` map keys are published
   workflow UUIDs; values bind the worker revision, actual WorkerProject and
   combined verification commands. Registry edits cannot change an enqueued run.
4. The manifest's `providers.allowed_endpoints` is the runtime's exact allowlist.
   `providers.credential_files` maps OpenAI provider revision UUIDs to private
   credential files. Ollama-only execution needs no OpenAI secret. `probe_seconds`
   and `reviewer_seconds` bound checks and review; provider revision timeouts and
   profile context/output limits still apply. No proxy environment or redirect
   may broaden this allowlist.
5. `workers` maps immutable worker revision UUIDs to `OpenHandsDeployment`;
   `credential_files` resolves its opaque SSH key and known-host references.
   Pin the expected host key through an independent authorized source. Never
   accept an unknown key automatically. `allowed_worker_hosts` must include the
   exact configured alias. Set both orchestrator concurrency settings to one.
6. `source_root`, `git_executable`, `ssh_executable`, executable-map paths and
   `executable_path` are absolute server/container paths. The worker workspace
   must equal its configured workspace root plus project slug. Legacy workers
   cannot select arbitrary worktrees or switch models per task. The declared
   worker-managed profile must match the actual worker model configuration.

`OLLAMA_BASE_URL`, `OPENAI_API_KEY_FILE`, `JARVIS_CONFIG_DIR` and `JARVIS_WEB_HOST`
were unconsumed examples and have been removed. Next.js host/port are CLI options.
An API environment file is not automatically inherited by the orchestrator;
export the documented process variables or supply them through Compose.

Loopback addresses refer to the process's own machine/network namespace. A Core
container cannot reach a different VM's Ollama at `127.0.0.1`. Choose an explicitly
authorized reachable URL, allowlist that exact URL and keep it server-side.
Model tags must be confirmed installed; no historical tag or homelab address is
assumed. A configuration-only registry check remains distinct from a live probe.

## Bounded provider check

With `DATABASE_URL` exported and a private ProviderRuntimeConfig JSON file:

```sh
python -m jarvis_orchestrator.providers.probe \
  --configuration /private/providers.json --profile-revision UUID
python -m jarvis_orchestrator.providers.probe \
  --configuration /private/providers.json --profile-revision UUID --inference
```

Expected: explicit `network_checked`, installed-model health and, for inference,
actual model/profile identity and usage provenance. A cold installed model can be
warming. Unknown tokens/cost remain unknown. A successful enum response proves
basic schema compatibility only, not planner/reviewer quality.

## Observed real-model behaviour (loopback Ollama, 2026-09-09)

These are measured results from an actually running local Ollama, not fixtures.

Model capability is not uniform across the three model contracts:

| Contract | `qwen3:0.6b` | `qwen3:1.7b` |
| --- | --- | --- |
| Connection/inventory validation | passes | passes |
| `OrganizerOutput` / `TaskPlan` planning | passes | passes |
| `ReviewDecision` review schema | intermittently fails | intermittently passes |

The reviewer schema is the strictest contract: six identifiers, a SHA, a digest
and a bounded findings list. Choose a larger tag for the reviewer node than for
planning if review keeps failing its contract.

Latency is substantial. A cold load plus one planning call took 55-69 seconds on
this hardware, and a full organizer-plus-architect pair took about three minutes.
Size `probe_seconds` (maximum 60) and `reviewer_seconds` accordingly, and expect
the service heartbeat, not a short lease, to keep a run alive during inference.

Small models intermittently return structured output that does not satisfy the
requested schema. The adapter classifies that as `provider.contract_failure`.
An unmatched failure class gets no retries and a `block` exhaustion action, so
**a real-model retry policy must include rules for the provider and
infrastructure classes** or one malformed response blocks the whole run. Real
composition now refuses to start such a run, naming the missing classes:

```
provider.contract_failure  provider.transient  provider.rate_limited
infrastructure.timeout     infrastructure.service_unavailable
```

Free local profiles carry no pricing, so accounting records an unknown cost with
no amount rather than inventing one. Paid providers are separate: see the budget
gateway below.

## Paid providers and the budget gateway

A paid provider is refused unless the run's bound route policy authorizes it.
Before each billed call the gateway evaluates that immutable policy and records
a private immutable grant keyed by call identity, so a restart replays the
original decision instead of buying a second inference. It fails closed when
pricing is unknown, when no route policy is bound, when `allow_paid` is false,
when a per-call or per-run ceiling cannot be satisfied, and — for a policy that
sets `max_run_cost` — when the durable run total cannot be determined because an
earlier billed call has no recorded outcome. Set `allow_paid`, the token ceilings
and `max_call_cost`/`max_run_cost` on the route policy's `spend` block.

Live paid-provider execution has not been exercised: it needs a real OpenAI
credential, which was not available. Its acceptance is fixture-based.

## GitHub publication is excluded from this MVP

There is no real publication handler. Real composition refuses a workflow
containing a `github_publish` node before any inference or worker dispatch.
Do not publish a workflow with that node for real use.

## Running real acceptance on Windows: use a short temporary root

This is the single most expensive trap in local acceptance, and it looks exactly
like an application defect.

The real acceptance test derives its per-run `source_root` from `TMPDIR`. Core
then builds `<source_root>/<32 hex>/c/<key>` and runs `git worktree add` on it.
With the repository checkout's own path as `TMPDIR`, that source root is already
around 90 characters before Core adds roughly 40 more, and Git for Windows fails
on the resulting worktree path. The failure surfaces as a `WorkerBoundaryError`
from the candidate import, which defaults to `configuration.invalid`, is
therefore not retryable, and blocks the run with no useful detail.

Export a genuinely short root before the run:

```sh
mkdir -p /c/jv/t
export TMPDIR=C:/jv/t
```

Set `TMPDIR` only. Python's `tempfile` reads it first, so that is enough. Leave
`TEMP` and `TMP` at their Windows values: overriding them with a forward-slash
path, or unsetting them, leaves the Windows Playwright process without a usable
temp directory, and it writes a literal `web/undefined/` transform cache into the
repository that fails the Prettier gate on the next run.

The same class of failure is recorded in `V1_HARDENING_MATRIX.md` as Git for
Windows `fatal: '$GIT_DIR' too big` during the M8 work. CI is unaffected: it runs
on Linux under `/tmp`.

Two further conditions are worth setting up the same way. Provision a fresh
disposable worker rather than reusing a long-lived container:

```sh
python -m scripts.provision_runtime_fixture --directory .tmp/fresh-ssh \
  --name jarvis-v1-fresh-worker --port 22260
```

Point `JARVIS_TEST_SSH_DIRECTORY`, `JARVIS_TEST_SSH_CONTAINER` and
`JARVIS_TEST_SSH_PORT` at what that command creates. Use a database dedicated to
the run too: queued runs left behind by other suites compete with the service
under test.

## Reading a blocked run

A blocked run now names the boundary that refused it. The node log line carries
`code=<constant> node=<node id>`, and the run's `result_summary` reads
`Runtime requires reconciliation: <constant>`, for example
`source_import_tree_mismatch`. Only curated constants reach that channel; native
exception text never does. `code=unspecified` means the failure came from
somewhere with no boundary constant, not that the detail was withheld.

When a probe fails, its JSON also names the exception type alongside the generic
failure code. `ValidationError` means the private configuration file is wrong;
it is not a reachability problem.

## Opt-in live model acceptance

With a reachable allowlisted Ollama and an installed tag:

```sh
export JARVIS_LIVE_OLLAMA_URL=http://127.0.0.1:11439
export JARVIS_LIVE_OLLAMA_MODEL=qwen3:1.7b
export TEST_DATABASE_URL=postgresql+psycopg://user@127.0.0.1:5432/database
python -m pytest tests/integration/test_live_model.py -q
```

These are skipped without both variables, so CI never depends on a model server.

## Supported initial project profile

Use a disposable, small committed UTF-8 Python project with no secrets. Existing
review seals reject binary/NUL content, LFS, symlinks and submodules, and bound
complete source to 1,000 files/4 MiB. Git transfer additionally bounds the complete
reachable bundle to 16 MiB. The complete review prompt must also fit its provider
context and 262,144-character request bound. Common binary-asset projects are not
currently supported. Evidence is never silently omitted to fit a passing seal.
Verification executes project code: this first profile assumes a trusted owner
and a disposable execution environment, not arbitrary hostile repositories.

Core imports an integrity-checked bundle into a per-run local repository. Its
request/invocation, commit and tree identities must match the authoritative SSH
result. It never treats a remote filesystem path as a Core checkout. Candidate
refs and prior Core integration objects survive subsequent transfers.

## Startup and acceptance

Run migrations/checkpoint bootstrap with a separate migration identity. Start API,
web and `python -m jarvis_orchestrator.main` with real mode and the private manifest.
Log in, create a project/objective through Runs and enqueue its published workflow.
Expected sequence: live dependency preflight, Organizer, Architect, durable tasks,
worker invocation, exact-source tests, bounded classified retry, independent review,
serialized combined integration gates and durable final history. Production
approval nodes interrupt the same LangGraph thread and resume only after a
version/digest-bound authenticated decision. Publication configuration is still
under implementation; do not expect a push or PR from the current local graph.

For the fixture acceptance, explicitly start the documented disposable Docker SSH
fixture, pin its host key and set `JARVIS_TEST_SSH_DIRECTORY` to its generated key,
known_hosts and base-sha directory, then run:

```sh
python -m pytest tests/integration/test_real_entrypoint.py -q
python -m pytest tests/integration/test_real_approvals.py -q
TEST_DATABASE_URL=... scripts/verify.sh
```

The entrypoint fixture uses actual HTTP/SSH/process transports and a deterministic
runner/model protocol server. It is not an OpenHands or real-model quality test.
Use a separate disposable database so queued fixtures from other suites do not
compete with the normal service. The test retains prior candidates and invocations.

## Side-by-side preparation

`deploy/compose.production.yml` separates bootstrap, migration and runtime logins;
web/API have no Docker socket. Set immutable image references, private secret and
configuration directories, an HTTPS public origin and a separately reviewed TLS
proxy (example included). Ports bind only to host loopback. All volumes/networks
belong to Compose project `jarvis-v1`. Runtime credentials cannot perform DDL.

First install is scripted (M12A): `scripts/install-homelab.sh` (add
`--mode production` for the reverse-proxy path) provisions directories, secrets,
the deployment env file, images, PostgreSQL, roles, migrations, checkpoint
storage, the API and web, then verifies readiness; `scripts/owner-bootstrap.sh`
creates the owner through the migrator-identity Compose service;
`scripts/preflight.sh` validates a configuration. The trusted private-LAN
overlay `deploy/compose.homelab.yml` publishes the web port on the LAN and runs
the API in development mode with non-Secure cookies — nothing else is relaxed,
and production defaults are unchanged. Full procedures are in
[docs/DEPLOYMENT_RUNBOOK.md](DEPLOYMENT_RUNBOOK.md). The orchestrator still needs
its private `runtime.json` and is started separately.

`scripts/deploy-core.sh check` performs local preflight without contacting a host.
Actual `deploy` requires explicit target/key/pin variables and the target-owned
`/opt/jarvis-v1/shared/deployment.env`. It transfers only a committed Git archive,
checks its digest and switches V1 release links after Compose startup. `rollback`
refuses an implicit migration downgrade. No command promotes over `/opt/jarvis`.
`backup-v1.sh` stops API/orchestrator writes before capturing database (including
checkpoints), artifacts and source together, then restarts services. Restore and
deployment acceptance are still pending; do not treat this preparation as proven.

## Remaining target prerequisites

After local gates pass: exact Worker-01 SSH alias/port/user and pinned host key,
authorized key reference, installed wrapper/runner paths and model identity;
reachable allowlisted Ollama URL and confirmed tag; disposable project/base commit;
explicit disposable GitHub repository and least-privilege credential reference if
publication is tested; separately authorized V1 deployment host/TLS details.
Stop and remove only the named disposable test containers/volumes during cleanup.
Retain desired evidence first. Never clean or reset the legacy installation.
