# Implementation checkpoint — unfinished local MVP

Branch: `codex/local-mvp-runtime`, based on `c701fcb397b4469ee115b509d8d026f3b26bb356`.
No full V1, controlled real-model workflow, deployment or rollback acceptance claim.

Verified locally during implementation:

- Normal real entrypoint/authenticated enqueue with disposable HTTP/SSH protocols:
  1 passed in 193.32s, including one failing deterministic test, bounded retry,
  valid independent review, combined integration and final history.
- Production approval PostgreSQL tests: 7 passed (same-thread reconstruction,
  owner/CSRF boundary, idempotency, expiry and tampered projections).
- Worker/source/provider configuration focused suite: 64 passed.
- Usage aggregation: 5 passed; started/result receipts count once and unknown cost
  is not zero. Worker-managed usage remains explicitly unavailable.
- Ruff, mypy (202 source files), frontend type check and secret scan passed.
- Earlier frontend suite: 49 passed; local production web build passed.
- Python and web Docker images built. Isolated production Compose bootstrap and
  migrations passed with separate identities; API /health and web /login returned 200.
- Actual local Ollama 0.13.1, qwen3:0.6b returned schema-valid enum output with exact
  reported usage. This is not planner/reviewer quality or OpenHands evidence.

Full suite remains pending on the final revision. The interim suite was
724 passed/1 failed and 79.31% coverage; the demo renewal-race regression was
subsequently fixed and passed. Do not waive the unchanged 80% gate.

## Next work (current authorization continues through all local requirements)

1. Add meaningful coverage for real composition/RuntimeModel/reviewer by exercising
   normal `serve()` against the same local transports, alongside subprocess acceptance.
   The existing subprocess scenario alone does not collect child Python coverage.
2. Complete pre-dispatch source-profile rejection and explicit wrapper transfer-version
   checking. Current snapshots fail closed on binary/LFS/symlink/submodule/size limits.
3. Exercise protected effects, invalidation, cancellation and restart boundaries end to
   end. Approval request/API reconstruction tests alone are not the complete M9 gate.
4. Implement GitHub publication, allowlisting, digest-bound push/PR reconciliation and
   exact-SHA CI projection. It is currently absent; fail-closed missing-handler guards remain.
5. Complete health/staleness/retention/redacted incident export, full history and node
   inspection, mobile/browser/a11y tests, and remaining required-route placeholders.
6. Implement and verify restore, service health checks, reproducible deployment/rollback,
   dependency/image/security/performance gates. Deploy/backup preparation is unverified.
7. Recheck paid-provider spend/permission gateway: RuntimeModel currently rejects paid
   calls. Ollama-only works without OpenAI credentials. Health circuit integration remains.
8. Run full unchanged verify.sh, PostgreSQL suite, generated contract checks, builds,
   browser checks and canonical DEMO acceptance. Reconcile every matrix row with evidence.
9. Publish reviewable branch/draft PR, inspect exact-commit CI. Do not merge.

## Disposable local environment

Docker fixtures: `jarvis-v1-mvp-test-postgres` (loopback 55439),
`jarvis-v1-mvp-test-ollama` (11439), `jarvis-v1-mvp-test-worker` (22239).
Separate packaging Compose project: `jarvis-v1-mvp-packaging` (API18039/web13039).
These are local fixtures, not homelab targets. Existing unrelated containers remain untouched.
Database `jarvis_v1_mvp_test` contains full-suite leftovers; normal startup uses
`jarvis_v1_entrypoint_test` to avoid claiming other tests' queued runs.
Evidence logs and generated fixture credentials remain under ignored `.tmp`.
Host-owned SSH fixture directory: `.tmp/runtime-ssh-host-empty`; earlier sandbox keys
are not usable from the host account. Native Windows SSH requires PROGRAMDATA/COMSPEC
in its bounded process environment. Use short temporary source roots for Windows Git.

Use `.venv/Scripts/python` (3.12.14) and the verified downloaded Node20.19 runtime in
`.tmp/toolchains/node-v20.19.0-win-x64`. Node/Docker/SSH host tests need the permitted
host execution context and their own `--basetemp` to avoid sandbox ACL conflicts.
Private values must never be committed or printed. No target-specific details are
needed to continue the unfinished local work above.
