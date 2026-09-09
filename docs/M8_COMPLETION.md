# M8 verification, review, artifacts and Git integration

Status: M8 baseline implementation verified on main at
`c701fcb397b4469ee115b509d8d026f3b26bb356`. The closure text below previously lagged
the implementation. GitHub job 102297159696 in
[34297493184](https://github.com/ClearPointSolutions/Jarvis-Development/actions/runs/34297493184)
was independently inspected: checkout matches this SHA, 714 Python tests passed,
85.88% coverage, 49 frontend tests, 10 browser tests and the full verification
script passed. This closes the baseline M8 local scope, not real V1 acceptance.

Current real runtime/M9-M11 extensions are tracked in
[LOCAL_MVP_MATRIX.md](LOCAL_MVP_MATRIX.md) and require their own exact-revision gates.

## Historical M8 development baseline

Fetched clean main: `e62b7e8a44a6af99d54c6e6c760eaaf2657f2250`.
Branch: `codex/m8-verification-review-git`.
M7 exact branch `01f64fe360e1055824f4fa08dcdface82b18961f` passed
[34232277520](https://github.com/ClearPointSolutions/Jarvis-Development/actions/runs/34232277520).
The exact post-merge main passed
[34232309196](https://github.com/ClearPointSolutions/Jarvis-Development/actions/runs/34232309196).
M7 closure was committed as `4bf0ec2` before M8 implementation.

## Protocol and source authority

`jarvis_contracts.verification` defines argv commands, timeout, expected exit
codes, allowlisted environment overlay, parser, fixed root policy and output
limit. M7 WorkerVerification shares this contract. Executables resolve through a
server-owned absolute executable map. Shell/batch/PowerShell executable targets
are rejected. Windows npm uses Node plus its configured CLI JavaScript entrypoint.

The executor confirms actual worktree root, branch, clean complete metadata and
SHA before and after execution. No caller cwd field exists. Tracked symlinks,
submodules, local executable Git filters/merge drivers and configuration includes
fail closed. Global Git configuration, hooks and remote protocols are disabled.
Explicit recognized legacy leading-cd corrections produce `command.normalized`
and a correction artifact; additional shell manipulation is rejected.
The only imported prefixes are `cd /app && `, `cd /workspace && `,
`cd /project && ` and `cd /repo && `. The original command digest, removed
prefix and resulting argv are retained. New structured commands have no cwd field.

Minimal process environments exclude provider/orchestration secrets by default.
Concurrent readers bound both output streams. POSIX cancellation kills the
controlled process group. Windows uses a kill-on-close Job Object and trusted
launch gate: child code starts only after job assignment.

Parsers support pytest, Vitest, TypeScript, Next, ESLint, Ruff, mypy and generic
exit-code evidence. Exit status/timeout remain authoritative even when parsing
fails. Execution artifacts retain identity, command, cwd, environment keys,
timestamps, status, parsed summary, truncation flags and log references.

## Artifacts, snapshots and review

Evidence reuses digest-bound, owner-authorized immutable artifacts and append-only
events. Graph state/events contain IDs and bounded summaries. Snapshots bind Git
blob IDs/content hashes and separate manifest, source, cumulative-diff and
latest-diff artifacts. The current bounded policy admits complete UTF-8 text
repositories up to 1,000 files and 4 MiB of source. Binary, LFS and submodule
snapshots fail explicitly rather than silently omitting authoritative source.

Reviewer evidence includes objective, immutable workflow/config IDs, current task
criteria, sealed snapshot, cumulative source/diff, separate latest diff,
deterministic reports, prior feedback and failure history. PASS binds exact
snapshot ID, SHA and digest. Reinspection invalidates changed state, retains the
decision diagnostically and emits `review.snapshot_invalidated`. Failed reviews
retain findings/feedback; M7 request preparation carries persisted current-task
feedback into subsequent attempts.

M5 remains the workflow engine. The M8 effect adapter returns existing bounded
channels. Verification failure is `code.test_failure`; current-task review failure
uses the existing canonical M3 `code.review_failure` class. Existing M3/M5 policies own retry budgets. Only completed
integration marks the task/attempt succeeded.

## Integration and persistence

Migration 0008 adds `control.integration_heads`: run/repository HEAD selection
and lease owner/generation/acquisition/renewal/expiry/release. API/readonly roles
have SELECT only. Migrations 0001–0007 are unchanged; evidence uses existing stores.

ADR-027 defines isolated integration generations. Each generation branches from
current authoritative HEAD and merges the reviewed candidate with
`--no-ff --no-edit`. Candidates are never rebased, deleted, force-pushed or
automatically conflict-resolved. Conflict aborts only the temporary merge and
persists `code.git_conflict` evidence. Combined gates use the same executor.
After sealing, a fenced transaction atomically selects branch/SHA/snapshot and
stores the integration receipt. Failed gates/stale leases cannot advance HEAD.

The authenticated integration HEAD API is read-only and paginated. Existing
task/event/artifact APIs expose evidence. Mission Control displays verification,
review, invalidation, snapshot/integration events, artifact downloads, selected
branch/base/HEAD and lease generation.

## Validation so far

- Real local Git/PostgreSQL: unrelated divergent branches integrate both changes;
  conflicts preserve both candidates and HEAD; failed combined gates preserve HEAD.
- Reviewer: cumulative state/latest diff separation, durable PASS/FAIL, recovered
  result reuse, subsequent HEAD invalidation.
- Published workflow/M5/M7 local transport reaches sealed integration/task success.
- Eight crash boundaries and lease fencing passed. Persisted results recover;
  uncertain started verification/Reviewer dispatch blocks for reconciliation.
- Locked frontend install: zero vulnerabilities.
- Ten foundation/M8 Chromium tests passed, including actual authenticated artifact
  retrieval, reload, axe accessibility and serious-console checks. M6's browser
  test runs separately under its dedicated demo harness.
- All 42 verification unit/security cases passed, including a filename containing
  shell metacharacters that is passed literally through argv.
- The first complete Python run passed 713 tests at 86.39% coverage. Contract
  drift then caught a missing generated API path update; that file was regenerated
  from the authoritative OpenAPI and drift now passes. A complete rerun includes
  the additional filename security case (714 collected tests).
- Final Python/frontend/browser/migration/security totals, coverage,
  scripts/verify.sh and exact-commit GitHub CI: pending.

## Behavioral acceptance evidence

The focused local suite passed **78 tests** (M8 plus affected M6/M7 regressions).
The following evidence is executable, using disposable Git repositories and
PostgreSQL rather than browser mocks for runtime facts.

| Required behavior | Executable evidence |
| --- | --- |
| 1–3: actual root, invented cwd rejection, evented legacy correction (REP-001) | `test_m8_verification.py`: cwd/legacy/executor cases; `test_m8_review.py`: persisted correction and actual execution |
| 4: failed verification bypasses Reviewer; correct retry budget (FAIL-001) | `test_m8_runtime.py`, `verification_failure` rework case |
| 5–6: immutable evidence and bounded artifact-backed large logs (ART-001, EVT-007) | `test_m8_evidence.py`; existing artifact integrity/authorization/tamper tests; process output-bound tests |
| 7–8: cumulative source and separate latest diff (REP-002) | `test_m8_review.py`, two committed attempts and inspection of both source files |
| 9–10: exact snapshot/SHA PASS and mutation invalidation (REP-003) | `test_m8_review.py`; integration reinspection and fenced advancement |
| 11: durable current-task feedback and next-attempt delivery (FAIL-004) | `test_m8_runtime.py`, `review_failure` rework case |
| 12: isolated task branches/worktrees | `test_m8_evidence.py`, `test_m8_runtime.py`, retained M7 workspace tests |
| 13–15: divergent unrelated branches, serialized queue, lease expiry and stale fencing (REP-004) | `test_m8_evidence.py`, `test_m8_leases.py` |
| 16–17: post-merge combined gates; failed gates cannot advance HEAD | `test_m8_evidence.py`, `combined_failure` case |
| 18–20: conflict classification and preserved candidate/authoritative branches (FAIL-007) | `test_m8_evidence.py`, `conflict` case |
| 21: cumulative final repository contains both successful tasks | `test_m8_evidence.py`, `unrelated` case |
| 22: durable review/test/artifact history and recovery (RUN-006/007) | `test_m8_runtime.py` crash matrix; `test_m8_review.py` persisted decision reuse |
| 23: M6/M7 safety regression | full existing demo/worker suites plus focused regression run |
| Authenticated read-only API, real UI, accessibility (AUTH-004, WEB-002) | `test_m8_api.py`, `m8-evidence.spec.ts`; full browser gate pending |
| Command/environment/process security (SEC-001/002, WRK-005/006) | `test_m8_verification.py`; existing M7 traversal and artifact redaction tests |

## Restart and crash matrix

| Injected boundary | Expected and tested recovery |
| --- | --- |
| After verification started | Preserve started evidence; block ambiguous execution rather than rerun blindly |
| After verification result persisted | Reuse immutable report and continue without duplicate command |
| After Reviewer dispatched | Block uncertain Reviewer outcome for reconciliation |
| After review result persisted | Reuse decision, revalidate candidate SHA/digest, continue |
| After integration lease acquired | Expired generation is fenced; replacement generation integrates safely |
| During local Git integration | Preserve old generation and branches; replacement uses isolated worktree |
| After combined gates | Revalidate and complete in a fresh fenced generation |
| Before authoritative HEAD advancement | No partial selection; replacement advances once after gates |

All eight crash cases passed in the focused PostgreSQL suite. The integration
receipt and HEAD selection commit in the same fenced transaction. Recovery never
claims exactly-once external execution where the outcome is unknown.

## Explicit limits

- Local verification is wired through the existing M5 server-side adapter factory
  and a workflow-pinned `LocalVerificationBinding`; the browser cannot configure
  executables, cwd, credentials, or passing results.
- Source sealing fails closed beyond 1,000 UTF-8 text files / 4 MiB source, or for
  binary/LFS/submodule/symlink state. These formats need a later explicit snapshot
  policy; they are not silently omitted from review.
- Per-stream command output is capped at 1 MiB; JSON evidence artifacts at 8 MiB.
  Truncation is recorded. Parsers are advisory summaries, never success authority.
- Ambiguous dispatched verification/review blocks for reconciliation. Automatic
  model conflict resolution and production Reviewer transport are outside M8.
- Git integration remains entirely local. Production approval, remote publication,
  deployment and the full Mission dashboard remain later milestone work.

## Gate corrections

The direct M6 test harness now renews its run lease just as the real service's
`serve`/`tick` path does; the TTL and production fencing checks remain unchanged.
Browser acceptance exposed empty capability groups missing their ARIA role, which
was corrected. M8 browser downloads use Chromium's authenticated fetch so the
test exercises its Secure/HttpOnly loopback cookie behavior, rather than the
separate Node HTTP client's different Secure-cookie rules. No assertion or gate
was weakened.
The M6 browser also explicitly waits for the API's durable `approval_required`
state after task completion, before asserting that its decision button is enabled.
This removes an assumption that task completion and approval checkpointing happen
within the same five-second UI assertion window. The complete four-run scenario
passes with this additional authoritative-state assertion.
Cold demo adapter imports are now loaded off the event loop before the service
claims runs. This removes measured startup work from the five-second demo lease
window. The lease duration and complete canonical event-sequence comparison are
unchanged; the four-run browser scenario passes after this runtime correction.

The live npm advisory feed subsequently reported
[GHSA-2883-xcg3-v3hh](https://github.com/advisories/GHSA-2883-xcg3-v3hh)
and [GHSA-82fw-gwwq-j7x9](https://github.com/advisories/GHSA-82fw-gwwq-j7x9).
Vitest is now pinned to 4.1.11. A scoped OpenAPI-tooling override selects
`js-yaml` 4.3.2 because its parent pins the vulnerable version exactly. The stale
nested lock entry was aligned with the patched registry integrity metadata;
clean `npm ci`, `npm ls js-yaml` and audit verify the installed resolution.
The clean install reports zero vulnerabilities. The audit threshold is unchanged.

## Scope

No homelab/Worker-01 contact, production provider/runtime GitHub credentials,
deployment, M9 authorization, remote publication or M10 dashboard work occurred.
Final commit, complete acceptance matrix, exact branch CI and clean-tree
confirmation are pending. NOT READY FOR M9.
