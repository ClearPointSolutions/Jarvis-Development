# Jarvis V1 Acceptance Tests

Status: executable acceptance specification. IDs are stable and SHOULD map to automated test names/evidence.

## 1. Test environments

- **Unit/contract:** no network, disposable PostgreSQL, fake clock, deterministic adapters.
- **Local integration:** production-like containers, browser, disposable repositories, no homelab credentials.
- **Demo E2E:** deterministic demo adapters with outbound network denied.
- **Real staging E2E:** Jarvis-Core V1 services, real Jarvis-Worker-01, configured Ollama/optional OpenAI, and a disposable private GitHub repository in the allowed organization.

Tests never use, print, snapshot, or commit real secrets. Real staging begins with read-only compatibility checks and never mutates `/opt/jarvis`.

## 2. Authentication and browser security

- **AUTH-001 Login/logout:** anonymous protected requests return 401; valid owner login sets opaque Secure/HttpOnly/SameSite cookie; logout revokes it; old cookie fails.
- **AUTH-002 Brute-force behavior:** repeated invalid login is rate-limited/audited without account/password disclosure; valid access recovers according to policy.
- **AUTH-003 CSRF/origin:** state change without valid origin/CSRF fails; a valid same-origin request succeeds; SSE GET cannot mutate state.
- **AUTH-004 Object authorization:** a fabricated/unowned resource ID is indistinguishable from inaccessible and cannot expose events/artifacts/config.
- **AUTH-005 Session lifetime:** idle/absolute expiry and revocation work across API restart.
- **WEB-001 XSS/content:** hostile Markdown, ANSI output, filenames, event messages, and artifacts render inert under CSP; active content downloads safely.
- **WEB-002 Accessibility:** primary flow is keyboard usable, status is not color-only, approval focus/labels work, and automated accessibility checks have no serious violations.

## 3. Data, versions, and workflows

- **DATA-001 Migrations:** clean upgrade, rollback where supported, and upgrade from prior release produce expected schema/roles; application role cannot update/delete events.
- **DATA-002 Immutable snapshots:** editing worker/profile/policy/workflow after enqueue does not alter the run snapshot/hash or recovery behavior.
- **DATA-003 Idempotency:** repeated create/command/decision/effect request with the same key returns one logical record; mismatched payload with reused key rejects.
- **WF-001 Executable editor:** browser creates a draft with per-node worker/model/retry/verification/approval policy, connects nodes, validates, publishes, reloads, and starts that exact version.
- **WF-002 Validation:** duplicate/dangling IDs, unreachable node, missing fallback, unsafe predicate, capability mismatch, unbounded/non-progressing cycle, task bound above iterator bound, invalid fan-out/join, approval bypass, and publish path without verification reject with node/edge-specific errors.
- **WF-003 Compilation:** a known spec compiles to expected LangGraph nodes/routes; identical hash/config gives identical semantics after orchestrator restart.
- **WF-004 Version isolation:** editing a published workflow produces a new draft/version; active/historical run graph remains the prior version.
- **WF-005 Parallel reducers:** fan-out children finish in varied/duplicate delivery order; join emits once with deterministic result and no lost state.

## 4. Events and realtime

- **EVT-001 Normalization:** every required producer fixture maps to a schema-valid, human-readable event; hidden reasoning/native secret fields are absent.
- **EVT-002 Ordering:** pause one event transaction after cursor allocation while a second producer writes; the second cannot commit a higher position first. Concurrent producers yield unique positions and gap-free per-run sequences; timeline follows position/sequence, not producer clock. Mixed command/run/event mutation stress completes without a lock-order deadlock.
- **EVT-003 Append-only/dedup:** duplicate source sequence/idempotency creates one event; update/delete through API/application role fails.
- **EVT-004 Replay/reconnect:** disconnect after cursor N, commit events, reconnect using Last-Event-ID, and receive every authorized later event at least once with client dedup and no missing run sequence.
- **EVT-005 Lost notification:** suppress PostgreSQL notification while committing events; stream catches rows on next wake/keepalive/requery.
- **EVT-006 Snapshot boundary:** read projection/cursor then stream after cursor during concurrent update; resulting UI matches authoritative projection exactly once.
- **EVT-007 Large output:** oversized stdout/diff/trace becomes a redacted artifact; event stays bounded and useful.
- **EVT-008 Unknown type/version:** UI renders safe generic event for an allowed unknown minor type; unsupported major returns explicit reset/upgrade error, not a crash.

## 5. Queue, leases, controls, and restart

- **RUN-001 Queue claims:** two orchestrators claim a batch via `SKIP LOCKED`; each run has one current lease/generation and deterministic priority ordering.
- **RUN-002 Stale fencing:** expire/reassign a run/worker lease, then deliver old result; it is retained diagnostically but cannot advance node/task/run.
- **RUN-003 API lifetime:** starting/control request returns after durable enqueue and remains below target while a multi-minute fake worker executes independently.
- **RUN-004 Pause/resume:** pause during safe work shows `pause_requested`, reaches checkpointed `paused`, survives restart, resumes same LangGraph thread once.
- **RUN-005 Cancel race:** concurrent pause/resume/cancel commands are sequenced; cancel dominates; terminal run cannot resume; adapter receives at most one logical cancel.
- **RUN-006 Restart recovery:** kill orchestrator after effect dispatch and before checkpoint; replacement reattaches/reuses the effect and completes without duplicate side effect.
- **RUN-007 Unknown outcome:** simulate non-idempotent ambiguous effect; recovery blocks/reconciles and never blindly retries.
- **RUN-008 API/SSE restart:** restart API with run active; execution continues, browser reconnects, and no event/history is lost.
- **RUN-009 Whole-run retry:** retry terminal failed run creates linked run with new LangGraph thread/snapshot according to request and preserves the first run.

## 6. Failure and retry policy

- **FAIL-001 Test failure:** deterministic failing test classifies `code.test_failure`, increments only that counter, supplies evidence to the next developer attempt, and displays retry `n/max`.
- **FAIL-002 Worker transport:** SSH/connectivity failure increments only infrastructure transport budget, preserves semantic code attempt where no coding began, and backs off durably.
- **FAIL-003 Provider failures:** rate limit honors retry timing; transient error follows provider budget/failover; invalid JSON uses contract budget; none spend developer budget.
- **FAIL-004 Review failure:** concrete reviewer failure increments review/code policy as configured and next attempt receives authoritative current snapshot plus feedback.
- **FAIL-005 Budget exhaustion:** each class routes to configured fail/block/approval outcome exactly once and emits consumed/exhausted events.
- **FAIL-006 Configuration/security:** invalid config and policy denial are non-transient and cannot be retried into an unsafe action.
- **FAIL-007 Git conflict:** stale parallel branch conflict is `code.git_conflict`; integrated work remains intact and no infrastructure budget changes.

## 7. Workers, repositories, verification, and review

- **WRK-001 Registry/editor:** owner creates/edits/validates/retires a worker revision in GUI; response has capabilities/health but no credential/path-secret leakage; existing run keeps old revision.
- **WRK-002 Capability/capacity:** incompatible worker is not selected; max slots cannot be exceeded under concurrent dispatch.
- **WRK-002A Model binding:** selecting a model profile the legacy worker cannot honor rejects validation; selecting its declared worker-managed profile records the actual binding and never transmits a provider secret.
- **WRK-003 Legacy contract:** adapter sends valid bounded base64 payload, parses matching sentinel, independently verifies HEAD/status/root, and classifies malformed/missing sentinel/nonzero exit.
- **WRK-004 Duplicate/reconnect:** repeated start by invocation ID does not start a second runner; disconnect inspects and reattaches or marks explicit unknown.
- **WRK-005 Cancellation:** cancellation targets recorded process group only; late stale output cannot commit; workspace evidence remains.
- **WRK-006 Traversal/host key:** malicious slug/path/symlink escapes reject; SSH host-key mismatch rejects without accept-new fallback.
- **REP-001 Actual root:** verification runs in adapter-confirmed project worktree root. A model command beginning with invented `/app` path rejects or legacy-normalizes with visible event, then tests actual root.
- **REP-002 Authoritative review:** create correct file in attempt 1 and modify another in attempt 2; Reviewer sees both current files and cumulative state, not only latest diff.
- **REP-003 Snapshot binding:** mutate HEAD after snapshot; review result is invalidated and cannot authorize integration/publish.
- **REP-004 Parallel integration:** independent task worktrees execute concurrently; integration lease serializes merges, checks base SHA, runs combined gates, and advances once.
- **ART-001 Artifact integrity:** upload/read checks digest, scope authorization, safe filename/media handling, and missing/tampered content error.

## 8. Providers and accounting

- **PROV-001 OpenAI contract:** fake official-compatible endpoint validates auth handling, structured output, stream, usage, error mapping, timeouts, and redaction.
- **PROV-002 Ollama contract:** fake/native configured endpoint validates health/model capability, stream/JSON behavior, warming/unavailable states, and unknown/estimated usage.
- **PROV-003 Deterministic route:** ordered candidates filter by capability/data/health and pick the expected profile; failover is event-visible and snapshot-bound.
- **PROV-004 Optional provider:** absent OpenAI leaves Ollama route functional and shows OpenAI `misconfigured`; absent Ollama behaves conversely where route permits.
- **PROV-005 Circuit:** failures open, expiry half-opens, successful probe closes; concurrent callers respect limits.
- **PROV-006 Accounting:** exact vs estimated vs unknown tokens/cost retain provenance and decimal price snapshot; aggregate does not present unknown as zero.
- **PROV-007 Spend controls:** a paid call inside an enabled snapshotted ceiling runs; a call crossing request/token/cost limits is denied or durably interrupts as configured. An ambiguous timed-out billed call remains an `unknown` accounting attempt rather than disappearing or being claimed exactly once.

## 9. Approvals and protected effects

- **APR-001 Interrupt:** approval node persists request/event and LangGraph checkpoint, releases active execution capacity where appropriate, and waits indefinitely/configured expiry without polling a browser.
- **APR-002 Resume after restart:** restart services while waiting, decide approval, and resume the same thread at the intended node.
- **APR-003 Reject:** rejection follows declared edge, performs no protected effect, and remains in audit/history.
- **APR-004 Binding:** changed effect parameters/digest, another run/node, expired request, stale session, duplicate or post-cancel decision cannot use a grant.
- **APR-005 Node re-entry:** code before interrupt runs safely/idempotently on resume; protected push/restart effect happens at most once after approval.
- **APR-006 Policy defaults:** unrecognized, privileged, destructive, deploy, remote push/merge, and external communication actions deny or require configured approval—never silently allow.

## 10. GitHub, health, and security

- **GH-001 Not configured:** GitHub UI/route clearly reports unavailable; local completion remains possible under workflow policy.
- **GH-002 Approved publication:** configured disposable private repository receives one branch/commit/PR after approval; retry returns same publication; PR URL and CI state appear.
- **GH-003 Scope:** adapter cannot address repository outside allowlist or use credentialed URL; denial is audited.
- **GH-004 CI:** pending/success/failure transitions normalize; required failure routes by policy and cannot be reported as completion.
- **HLT-001 Health:** Core/API/database/orchestrator/worker/provider transitions display healthy/degraded/unavailable/unknown with staleness; raw high-rate samples do not flood events.
- **HLT-002 Stall:** missing activity flags possibly stalled; it does not falsely assert failure or kill unrelated processes.
- **SEC-001 Secret canary:** inject synthetic password, bearer token, API key, private key, connection URL, cookie, `.env` value through errors/commands/models/workers. Scan API/SSE, DB events, artifacts, logs, traces, screenshots, bundles, and Git; none contain originals.
- **SEC-002 No shell/SSRF:** route inventory and adversarial requests prove no arbitrary shell endpoint; provider/repo/artifact URLs cannot access disallowed host/file/metadata targets.
- **SEC-003 Container privilege:** production Compose has non-root services, no Docker socket, expected mounts/ports, and web/API lack SSH/provider secrets.
- **SEC-004 Legacy boundary:** pre/post hashes/status/read-only checks prove `/opt/jarvis` and legacy service/data were not changed by install/test/rollback.

## 11. Deterministic demo E2E

**DEMO-E2E-001** runs in a fresh local environment with outbound network denied:

1. Bootstrap and log in.
2. Create/edit a demo worker and model route through the UI.
3. Create/edit/publish an executable workflow through React Flow.
4. Create project/objective in Organizer chat and start run.
5. Assert API returned after queueing, then real orchestrator/LangGraph events update graph/feed.
6. Deterministic Architect creates a dependency task set; task-based progress appears.
7. Demo Developer emits bounded command/file events and an artifact.
8. First deterministic verification fails; exact failure class/counter routes back to Developer without infrastructure budget change.
9. Second verification passes; Reviewer uses sealed current repository fixture and passes.
10. Publication approval interrupts. Restart orchestrator and API, reconnect browser, and verify waiting history.
11. Approve; demo GitHub adapter emits one publication result and completion.
12. Restart all services; reload history/playback, task attempts, logs/artifacts, usage, approval, and final graph.
13. Run a second fixture that rejects approval and a third that injects worker infrastructure failure; verify correct branches/budgets.
14. Repeat with fixed seed/clock and compare normalized event-type/order/outcome fixture, excluding generated IDs/timestamps.

Demo labels are visible throughout; no real network adapter or production secret reference can be constructed.

## 12. Required real Worker-01 E2E

**REAL-E2E-001** is the release-blocking harmless staging scenario. Record run/job/workflow/worker revision IDs, commits, test results, event cursor range, restart point, approval decision, PR URL, and post-test legacy-boundary evidence.

1. **Login:** authenticate to the V1 LAN UI; anonymous access remains denied.
2. **Create/edit worker:** configure/validate a versioned Jarvis-Worker-01 OpenHands SSH worker without exposing its SSH key.
3. **Create/edit executable workflow:** publish a graph with Organizer/Architect/Developer/Verify/Reviewer/Approval/GitHub/final routes and per-node policy.
4. **Create project/objective:** bind a disposable repository and submit a harmless small software objective.
5. **Start real LangGraph run:** receive queued response; dedicated orchestrator claims and checkpoints the published workflow.
6. **Graph/events update from real runtime:** React Flow and feed change only from persisted real events; reconnect from cursor succeeds.
7. **Organizer/Architect creates tasks:** schema-valid dependency-ordered tasks/criteria/commands appear.
8. **Developer executes on Worker-01:** adapter leases the real worker, invokes existing OpenHands runner from the configured real workspace, and returns matching invocation/repository state.
9. **Command/test/file events appear:** actual bounded redacted commands, file changes, test outcomes, and artifacts are visible.
10. **Verifier runs:** commands execute at authoritative repository root and evidence is sealed.
11. **Failure routes correctly without losing state:** use a safely designed first failure or controlled fixture within the disposable repo; it increments only correct budget, retries, and preserves prior repository/checkpoint/task state.
12. **Reviewer uses authoritative current repo state:** reviewer evidence includes full current snapshot/cumulative work and passing verification, not only latest diff.
13. **Approval interrupts/resumes:** harmless protected publication pauses via real LangGraph interrupt; restart orchestrator while waiting; authenticated approval resumes same thread once.
14. **GitHub publishing/PR works when configured/approved:** create one branch/PR in the disposable private allowed repository; configured CI state appears. If GitHub is deliberately not configured, this release-blocking step is not waived—it remains not passed.
15. **History survives service restart:** restart API/orchestrator (and V1 containers as planned), reload and verify complete event/task/attempt/approval/artifact/usage/PR history and terminal status. Confirm legacy remains untouched.

## 13. Whole-project release gate

- **PERF-001 Control responsiveness:** with 100 queued runs and configured worker capacity saturated, enqueue/control API p95 remains below 500 ms on the target LAN test profile; handlers do not wait for worker/model completion.
- **PERF-002 Stream capacity:** 20 authenticated SSE clients reconnect/read while events commit; committed events normally reach connected clients within 2 seconds, all clients recover by cursor, and queue/orchestrator correctness is unchanged.
- **DUR-001 Backup restore:** restore a V1 database and matching artifact snapshot into an isolated root; authentication reset procedure, configuration hashes, event/checkpoint linkage, artifact digests, and historical playback validate.
- **DEP-001 Side-by-side rollback:** start/stop/rollback only the named `jarvis-v1-*` Compose project using the printed command; legacy service/path hashes/status remain unchanged and V1 data remains recoverable.

- `scripts/verify.sh` succeeds from a fresh checkout.
- Backend tests, frontend unit/component tests, Playwright, Python/TypeScript type checks, linting, production builds, migrations, secret/dependency scans, and Compose validation succeed.
- Demo E2E and all non-homelab tests pass locally.
- REAL-E2E-001 passes before deployment readiness.
- Side-by-side deployment smoke/restart/rollback and backup-restore evidence pass before promotion readiness.
- Serious browser console/server log errors are absent and exact commands/results are recorded in `docs/STATUS.md`.
