# Local MVP requirements and evidence

Baseline: main `c701fcb397b4469ee115b509d8d026f3b26bb356`; fetched origin main
matched the September review. Working branch: `codex/local-mvp-runtime`.
CI run 34297493184/job 102297159696 was independently inspected: exact baseline
SHA, 714 Python/49 frontend/10 browser tests and full script success (85.88%
coverage). It is not validation of current changes. No live host or disposable
GitHub publication is authorized.

| Requirement | Implementation | Evidence / remaining work |
| --- | --- | --- |
| A normal real startup | Private manifest, RealComposition, planning, worker, verification and review bindings | Normal-entrypoint authenticated enqueue + HTTP/SSH fixture passed in 193.32s: task, failing test, retry, PASS review, combined integration and completed history. Restart cases remain |
| B Ollama | Exact endpoint config, live adapter checks, configurable review timeout, identity/usage checks | Real local Ollama 0.13.1 qwen3:0.6b structured enum call passed; model planning/review NOT RUN |
| C separate hosts | Bounded integrity-checked Git bundle transport; local exact candidate verification | 53 source-transfer/M7 unit tests passed; loopback SSH process fixture prepared, acceptance remaining |
| C source limits | Existing UTF-8 snapshot policy retained, bounded full-history transfer | Binary/LFS/symlink/submodule projects unsupported; preflight/runbook remaining |
| D M9 approvals | Durable interrupt handler, authenticated decision API, event-bound protected effect and real run UI | Seven PostgreSQL request/decision/expiry/tampering/same-thread reconstruction tests passed. Protected-effect and browser acceptance remain |
| E M10A interface | Existing M8 evidence panels retained | Remaining: conversations, selected-run graph, history, truthful mode and required UI routes |
| E M10B publication | Existing fail-closed graph guards retained | Remaining: configured GitHub adapter and approval-bound publication/reconciliation |
| E M10C operations | Event-backed provider accounting/preflight | Remaining: aggregation, staleness, retention and incident export |
| F M11 packaging | Python/web images; Compose bootstrap/migration/runtime identities; V1 deployment and backup scripts | Both images built; isolated production Compose migrations passed, API health and web login returned 200. Health checks, restore, deployment/rollback and security gates remain |
| Full local gate | Existing verification script and coverage threshold unchanged | Interim PostgreSQL suite 724 passed/1 failed, 79.31% coverage; focused demo renewal-race regression subsequently passed. Full current gate pending |
| M12/M13 | Not executed | Exact Worker-01/model access, authorized disposable publication repository and explicit deployment target required after local implementation |

Local evidence is intentionally distinct: protocol fixtures do not prove real model
quality or OpenHands compatibility. No homelab test or deployment has occurred.
No readiness verdict is complete while the rows above remain open.

## Acceptance inventory

Every normative acceptance case remains open until exact-revision evidence is recorded.

| Acceptance requirement | Status | Implementation/test evidence |
| --- | --- | --- |
| AUTH-001: Login/logout: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| AUTH-002: Brute-force behavior: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| AUTH-003: CSRF/origin: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| AUTH-004: Object authorization: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| AUTH-005: Session lifetime: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| WEB-001: XSS/content: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| WEB-002: Accessibility: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| DATA-001: Migrations: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| DATA-002: Immutable snapshots: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| DATA-003: Idempotency: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| WF-001: Executable editor: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| WF-002: Validation: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| WF-003: Compilation: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| WF-004: Version isolation: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| WF-005: Parallel reducers: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| EVT-001: Normalization: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| EVT-002: Ordering: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| EVT-003: Append-only/dedup: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| EVT-004: Replay/reconnect: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| EVT-005: Lost notification: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| EVT-006: Snapshot boundary: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| EVT-007: Large output: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| EVT-008: Unknown type/version: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| RUN-001: Queue claims: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| RUN-002: Stale fencing: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| RUN-003: API lifetime: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| RUN-004: Pause/resume: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| RUN-005: Cancel race: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| RUN-006: Restart recovery: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| RUN-007: Unknown outcome: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| RUN-008: API/SSE restart: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| RUN-009: Whole-run retry: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| FAIL-001: Test failure: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| FAIL-002: Worker transport: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| FAIL-003: Provider failures: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| FAIL-004: Review failure: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| FAIL-005: Budget exhaustion: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| FAIL-006: Configuration/security: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| FAIL-007: Git conflict: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| WRK-001: Registry/editor: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| WRK-002: Capability/capacity: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| WRK-003: Legacy contract: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| WRK-004: Duplicate/reconnect: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| WRK-005: Cancellation: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| WRK-006: Traversal/host key: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| REP-001: Actual root: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| REP-002: Authoritative review: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| REP-003: Snapshot binding: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| REP-004: Parallel integration: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| ART-001: Artifact integrity: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| PROV-001: OpenAI contract: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| PROV-002: Ollama contract: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| PROV-003: Deterministic route: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| PROV-004: Optional provider: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| PROV-005: Circuit: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| PROV-006: Accounting: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| PROV-007: Spend controls: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| APR-001: Interrupt: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| APR-002: Resume after restart: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| APR-003: Reject: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| APR-004: Binding: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| APR-005: Node re-entry: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| APR-006: Policy defaults: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| GH-001: Not configured: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| GH-002: Approved publication: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| GH-003: Scope: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| GH-004: CI: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| HLT-001: Health: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| HLT-002: Stall: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| SEC-001: Secret canary: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| SEC-002: No shell/SSRF: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| SEC-003: Container privilege: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| SEC-004: Legacy boundary: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| PERF-001: Control responsiveness: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| PERF-002: Stream capacity: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| DUR-001: Backup restore: | Remaining | Baseline implementation where present; current full-gate revalidation pending |
| DEP-001: Side-by-side rollback: | Remaining | Baseline implementation where present; current full-gate revalidation pending |

## Product requirement inventory

| Product section | Status | Evidence |
| --- | --- | --- |
| 6.1 Mission dashboard | Remaining | Trace to acceptance inventory; current implementation/revalidation in progress |
| 6.2 Projects and jobs | Remaining | Trace to acceptance inventory; current implementation/revalidation in progress |
| 6.3 Workflow studio | Remaining | Trace to acceptance inventory; current implementation/revalidation in progress |
| 6.4 Configuration | Remaining | Trace to acceptance inventory; current implementation/revalidation in progress |
| 6.5 Operations and history | Remaining | Trace to acceptance inventory; current implementation/revalidation in progress |
| 7.1 Configure and run real work | Remaining | Trace to acceptance inventory; current implementation/revalidation in progress |
| 7.2 Intervene safely | Remaining | Trace to acceptance inventory; current implementation/revalidation in progress |
| 7.3 Diagnose a run | Remaining | Trace to acceptance inventory; current implementation/revalidation in progress |
| 7.4 Deterministic demonstration | Remaining | Trace to acceptance inventory; current implementation/revalidation in progress |
| 8.1 Authentication and authorization | Remaining | Trace to acceptance inventory; current implementation/revalidation in progress |
| 8.2 Conversation and objectives | Remaining | Trace to acceptance inventory; current implementation/revalidation in progress |
| 8.3 Runtime control | Remaining | Trace to acceptance inventory; current implementation/revalidation in progress |
| 8.4 Observation | Remaining | Trace to acceptance inventory; current implementation/revalidation in progress |
| 8.5 Workflow configuration | Remaining | Trace to acceptance inventory; current implementation/revalidation in progress |
| 8.6 Worker execution and source control | Remaining | Trace to acceptance inventory; current implementation/revalidation in progress |
| 8.7 Provider routing and accounting | Remaining | Trace to acceptance inventory; current implementation/revalidation in progress |
