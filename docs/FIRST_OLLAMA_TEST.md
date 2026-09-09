# Controlled first Ollama test (implementation acceptance in progress)

This is not yet a passing deployment runbook. The normal-entrypoint protocol
acceptance and complete local verification gate must pass before target use.
No exact homelab target has been supplied or contacted in this session.

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
