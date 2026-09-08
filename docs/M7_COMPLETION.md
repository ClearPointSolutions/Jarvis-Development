# M7 worker adapter completion evidence

Status: **M7 COMPLETE — READY FOR M8** (local adapter/protocol scope).

## Formal merge closure (2026-09-08)

PR #4 merged as `e62b7e8a44a6af99d54c6e6c760eaaf2657f2250`, confirmed
as current origin/main after fetch. Exact final branch commit
`01f64fe360e1055824f4fa08dcdface82b18961f` passed
[verify 34232277520](https://github.com/ClearPointSolutions/Jarvis-Development/actions/runs/34232277520).
The exact post-merge main commit passed
[verify 34232309196](https://github.com/ClearPointSolutions/Jarvis-Development/actions/runs/34232309196).
M7 COMPLETE / READY FOR M8. This supersedes the historical unmerged scope
statement below.

Branch: `codex/m7-worker-adapter`.
Base: `bb6646210e9f6a96f0d165aa3b13ac96fc0f60ed`.
Validated implementation: `8fbd99acc202ca81873e097dd169338d9f2064ea`.
Its exact Linux [verify run 34227977202](https://github.com/ClearPointSolutions/Jarvis-Development/actions/runs/34227977202)
passed every enabled gate. The final completion-record commit is verified separately
before handoff; its exact SHA and run are included in the task's final response.

## Prerequisite

M6 PR #3 is merged. Its branch commit
`c10fdd281e4fcbfe5e971d11ab8c468f7ca739ea` passed
[run 34218524317](https://github.com/ClearPointSolutions/Jarvis-Development/actions/runs/34218524317).
The exact post-merge main base passed
[run 34218540048](https://github.com/ClearPointSolutions/Jarvis-Development/actions/runs/34218540048).
M6 COMPLETE / READY FOR M7.

## Implemented scope

| Area | Implementation and acceptance evidence |
| --- | --- |
| Generic contracts | `jarvis_contracts.workers` defines versioned request, task/project identity, limits, slot fence, prepared invocation, handle/status/events, result, repository snapshot, artifact manifest, health, validation, cancellation and reconciliation. Generated JSON Schema and TypeScript remain current. |
| Generic lifecycle | `workers/base.py` exposes validate/health/prepare/start/inspect/events/cancel/collect/reconcile with deadline/correlation context. Graph nodes use the M5 effect bridge and know no SSH commands. |
| Registry | `WorkerRuntimeRegistry` selects immutable worker revisions for both M6 DEMO and OpenHands. Mode gates reject cross-mode workers. `configured_worker_registry` binds server-only deployments, injectable transports, task requests, authorized artifact readers and immutable log publication. |
| SSH transport | `OpenSSHTransport` uses argv, bounded concurrent stream drains, explicit host allowlists, dedicated key/known-host files, strict checking, and no ambient SSH config, agent, proxy, password prompts or forwarding. Typed failures preserve infrastructure taxonomy. |
| Command safety | Fixed validated executable paths plus one bounded base64 JSON argument. No objective or task text is concatenated into a remote shell command. Slug/path/branch/argument injection tests fail closed. |
| Worker capacity | Migration 0007 adds numbered slots and durable leases per worker identity. Acquisition uses M5 lock ordering; active slots remain reserved after expiry until reconciliation. Generation fencing and current run ownership guard result/attempt commits. API roles cannot read lease-token hashes or invocation requests/results. |
| Invocation identity | M5 effect identity derives a stable UUID. Requests/digests are persisted before dispatch. Duplicate same-digest starts reuse the invocation; conflicting digests and incomplete reservations block. Restart reattaches to the existing remote identity. |
| Wrapper package | Protocol 1.0 Python module, versioned entrypoint and wheel console script. Atomic UUID reservation, detached supervisor claim, atomic status, independent runner process group, bounded redacted output, timeout and cancellation intent. Locally built wheel contains the implementation and entrypoint. |
| Workspace | Strict contained roots, deterministic task branches and local Git worktrees. Base/root/branch/HEAD are independently verified. Result inspection records HEAD, tree, status, index manifest and bounded diff digests with truncation facts. No merge/push/reviewer logic. |
| Legacy compatibility | Unchanged legacy payload and runner. Shared workspace is exclusive and concurrency one. Worker-managed model binding has exactly one compatible profile. Arbitrary worktree execution is not advertised by the legacy adapter. |
| Results | Last bounded schema-valid sentinel, task identity, explicit execution status, exit code, request identity, generation, timestamps and independent repository identity are checked. Missing/malformed/forged/nonzero results cannot imply success. |
| Artifacts | Private bounded memory staging handles split secrets and oversized output; an independent sentinel channel survives log truncation. Redacted stdout/stderr are content-addressed and linked through existing authorized artifacts/events. Context artifacts are bounded, digest checked and run scoped. |
| Health/activity | Transport and wrapper validation checks required paths, Git, roots, protocol and capabilities. Cached health and validation facts feed the API. Run heartbeat, slot renewal and output activity remain separate. Silence sets possibly-stalled rather than automatic failure. |
| Cancellation/recovery | Durable intent precedes targeted cancellation. Unknown outcomes block duplicate execution. Confirmed cancellation releases capacity. Late/stale results remain diagnostic and cannot advance task attempts. |
| UI | Existing worker cards show adapter, capabilities, configured state, health, concurrency, slot usage, last heartbeat, validation and workspace facts. No connection credentials are returned. Existing browser acceptance now asserts the new facts. |

## Local acceptance

The focused M7 suite covers 57 tests: 46 adapter/contract/security/transport tests,
five actual local wrapper/worktree tests and six PostgreSQL integration cases.
The latter exercise the real queue claim, compiled workflow and M5 orchestrator
through the configured worker registry and fake SSH, including restart, stale
results, late cancellation, unknown outcome and slot reassignment.

Transport tests never open a socket. Wrapper tests run synthetic local child
processes and temporary Git repositories. The cancellation test preserves an
unrelated local process. M7 integration tests use loopback PostgreSQL only.

The complete local Python suite passes **650 tests with 86.44% combined coverage**.
Migration round-trip and schema drift, Python formatting/lint, 154-file type checks
(including a Linux-targeted check), secret scanning and generated contract drift
pass. Linux CI passes the same 650 tests at **86.37% coverage**.

| Final gate | Result |
| --- | --- |
| `npm ci` and dependency audit | Passed; zero vulnerabilities reported |
| Frontend formatting, lint and type checking | Passed |
| Frontend unit/component tests | 49 passed |
| Production Next.js build | Passed |
| Foundation Chromium acceptance | 9 passed; M6 is intentionally handled by its dedicated command |
| M6 Chromium acceptance | 1 test covering four runs passed, including restart and durable decision |
| Accessibility and serious console checks | Passed in the browser suite; no serious findings |
| Log/browser bundle secret canaries | Absent |
| PostgreSQL-enabled `scripts/verify.sh` | All enabled gates passed locally and in Linux CI |
| Worker wrapper wheel | Built locally; implementation and console entrypoint verified |

The worker mobile view was visually reviewed. An obsolete M3-only helper sentence
was removed after that review. No real host connection was used for any M7 test.

## Security review and bounded limitations

- Secrets never belong in the worker/browser contract. Native transport errors
  are mapped to fixed codes; logs and context artifacts are redacted before use.
- Strict host-key verification is enforced in SSH arguments. Real Worker-01
  connectivity, its actual host key and its installed OpenHands environment have
  deliberately not been tested in M7.
- The existing M5 run fence remains authoritative. A worker lease's random-token
  hash is an audit commitment; generation checks and the current owner transaction
  authorize mutations. Expiry alone does not free a remote workspace.
- The POSIX wrapper owns a process group; Linux CI verifies targeted cancellation
  with actual local child processes. Windows local cancellation reports unknown
  when whole-tree termination cannot be proved. The actual Worker-01 environment
  still requires later authorized staging validation.
- The legacy worker remains exclusive; it cannot honor arbitrary worktree roots
  or cosmetic per-task model changes. The independent worktree manager is ready
  for a future compatible worker without pretending the legacy runner supports it.
- Repository facts are M7 identity evidence, not M8 verification/review seals.
  Truncation is explicit. A trusted worker OS/account is still part of the boundary.
- Real-worker binding is explicit server-side dependency injection. The default
  orchestrator entrypoint has no implicit host or credential configuration.

## Scope confirmation

No real Worker-01 or homelab service was contacted. The wrapper was not deployed.
No deployment occurred, `/opt/jarvis` and legacy references were preserved, no merge
to main occurred, and M8 was not started. Later authorized staging steps are in
[the wrapper package](../worker-wrapper/v1/README.md).

Recommendation: **READY FOR M8**. M8 has not been started. Real Worker-01 staging
and deployment remain separate future authorization gates, not claimed M7 evidence.
