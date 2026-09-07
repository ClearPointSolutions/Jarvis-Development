# M4 workflow system completion record

Date: 2026-09-07. Branch: `codex/m4-workflow-system`.

M4A and M4B are implemented and all local acceptance gates pass, including the
complete PostgreSQL `scripts/verify.sh` run. Publication is externally blocked:
native GitHub HTTPS push authentication is invalid and
the connected GitHub integration rejects repository writes with HTTP 403.
There is no M4 GitHub CI result. **NOT READY FOR M5. M5 is not started.**

## Provenance and integration order

The repository was fetched before changes. Main and origin/main were clean at
`940cd631d54ba4bcc976b9175dd42b1fedd7386f`, the supplied M3 commit; no newer main
descendant existed. M3's exact-commit verify run
[34167362184](https://github.com/ClearPointSolutions/Jarvis-Development/actions/runs/34167362184)
was confirmed successful. Stale M3 publication documentation was corrected first.
Existing M2 worktrees and legacy references were preserved.

| Order | Boundary | Commit SHA |
| --- | --- | --- |
| 1 | M3 reconciliation and M4 acceptance criteria | `8413620a749481963b44381422ab548c957f9596` |
| 2 | Shared Pydantic/config/API contract, generated JSON Schema/TypeScript, ADR-026 | `20dd880ccb724116a77af4055df2320f887fa215` |
| 3 | M4A compiler, validator, factories, reducers and PostgreSQL tests | `1e71dcbb8b7a6f4c9ea36f2c86ce6af2a58ce31b` |
| 4 | Durable API, migration, reference snapshots, events and generated OpenAPI | `0c07771f0740f5584c581c5988c996227d4ff6cb` |
| 5 | M4B typed Studio, canonical canvas, client and browser acceptance | `636869e1ae0b95b1c62b465135ee333ad509a061` |
| 6 | Integration review corrections: policy inheritance/idempotency and UTF-8 depth boundary | `943a1795ded53abb30e1a9e570381d5ebac34170` |

The code integration SHA is `943a1795ded53abb30e1a9e570381d5ebac34170`.
The documentation closure commit follows it; the final task report records that
HEAD. No main merge occurred. Parallel agents consumed the exact pinned contract
under separate path ownership in the shared integration checkout; the integration
owner alone committed their reviewed changes in the order above. Separate remote
compiler/editor branches were unnecessary and were not created.

## Canonical contract and compiler

Executable WorkflowSpec: **1.1**. Node version: **1.0**. Compiler: **1.0.0**.
State schema: `jarvis.workflow_state.v1`. Pydantic is authoritative; generated
JSON Schema, TypeScript and OpenAPI carry the wire contract. The old 1.0 envelope
is recognizable for historical data, but is rejected for executable compilation.
ADR-026 documents the refinement without rewriting earlier decisions.

The Studio edits the stored canonical nodes, edges, defaults and policy references.
Canvas objects are presentation adapters. JSON is canonicalized with sorted keys,
nodes ordered by ID and edges by source/priority/ID. SHA-256 excludes separate
layout metadata. Effective policies survive draft serialization; publication also
materializes typed config defaults. Explicit false overrides remain distinct from
omission in idempotency request digests.

All thirteen static node types have code-reviewed config models, policy schemas,
capability and channel contracts, validation and compilation factories:

`organizer`, `architect`, `task_dispatch`, `worker`, `verify`, `reviewer`,
`integrate`, `router`, `fanout`, `join`, `approval`, `github_publish`, `finalize`.

External node types accept injected deterministic test handlers and fail closed
without a handler. M4 does not bind real model, worker, approval or publication
services. Dispatch transforms graph task state; it does not claim durable work.
Timeout and protected-action/verification checks surround handler invocation.
Architect outputs respect their declared task limit. Handlers cannot mutate
snapshotted context or write channels outside their contract.

Edges: `always`, `on_result`, `on_failure`, `retry`, `iterate`. Conditional groups
require exactly one fallback and distinct non-fallback priorities. Classified
failure edges match their declared class. Retry budgets and exhaustion behavior
come from the immutable M3 retry revision. Iteration uses strictly increasing
`$.tasks.terminal_count` and an explicit hard bound; the Architect task bound
cannot exceed it. Graph step limits derive from these same immutable budgets,
so longer valid graphs work beyond LangGraph's default 25 steps.

Predicate operators: `eq`, `neq`, `in`, `exists`, `lt`, `lte`, `gt`, `gte`, `and`,
`or`, `not`. Paths are allowlisted observable node/outcome/task/verification/review/
approval/final/cancellation fields. Comparisons preserve JSON Boolean/number
semantics. No eval, imports, scripts, shell expressions or arbitrary state access
is available. See `workflows/predicates.py` for the exact path allowlist.

Validation returns stable issue codes, messages, node/edge IDs and field paths.
It rejects schema/ID/reference errors, unreachable or terminal-less graphs,
ambiguous routing, unsafe conditions, unbounded/non-progressing cycles,
inapplicable bounds, invalid reducers, malformed fanout/join regions, incompatible
or inactive registry revisions, missing policies, model purpose/capability and
worker capability/concurrency mismatches, denied actions, invalid verification/
approval policies, approval bypass/stale grants, and verification/review bypass.

Fanout uses LangGraph Send with native checkpointed child subgraphs, explicit
expected-child identities, deterministic reduced outputs and a parent barrier.
Reducers merge results by identity, union completion sets and take monotonic
counter maxima. Identical duplicates are harmless; conflicting duplicates fail.
Completion order does not lose results or rerun the join. Failed child results
cannot turn into final success. Nested/overlapping fanout, branch cycles and
unreduced concurrent writes are explicitly unsupported in V1.

Compilation identity includes canonical workflow hash, spec version, compiler
version and resolved snapshot hash. The optional scoped LRU cache is bounded
(default 32 entries; allowed 1–256), includes handler/checkpointer bindings, and
cannot be reused after closure. Stable run thread IDs are passed verbatim;
LangGraph owns native checkpoint namespaces. PostgreSQL tests cover update
streams, interruption, reconnection/reconstruction and resume without replaying
already completed first nodes.

## Resource bounds

| Resource | Maximum |
| --- | --- |
| Nodes / edges / acyclic graph depth | 500 / 2,000 / 500 |
| UTF-8 workflow command JSON | 1 MiB |
| JSON depth / traversed values | 24 / 100,000 |
| Node label or workflow name / description | 160 / 2,000 characters |
| Predicate AST depth / nodes per condition / membership values | 8 / 64 / 64 |
| Iterator / Architect task bound | 10,000 |
| Fanout children | 64 |
| Layout x/y / zoom | finite ±100,000 / 0.1–4 |
| Node timeout | 86,400 seconds |

Transport bounds apply both at the Next proxy and FastAPI body reader. FastAPI
checks UTF-8 and nesting before recursive JSON parsing; UTF-16/32 cannot bypass
the guard. Schema and semantic limits apply before graph processing. Brackets
and escaped quotes inside ordinary labels remain valid data.

## Database and API

Migration **0005_m4_workflows.py** adds owner and draft pointers, version snapshot
JSON/hash, immutable configuration-revision foreign-key bindings, supporting
indexes, pointer/identity/binding triggers and least-privilege grants. Existing
published-version immutability also protects layout and snapshot columns.
Migrations 0001–0004 are unchanged. Pre-M4 ownerless rows remain historical and
are not exposed as executable Studio templates. Upgrade, supported downgrade,
metadata drift and actual API-role constraints are exercised with PostgreSQL 16.

All routes below start `/api/v1/workflow-templates`. Owner identity scopes
templates and historical versions. Writes require CSRF and the configured origin,
actor/action/template idempotency and the current template optimistic version.

| Method | Suffix | Behavior |
| --- | --- | --- |
| GET / POST | root | Paginate templates / create durable initial draft |
| GET | `/node-types` | Typed static node palette |
| GET / PUT | `/{id}` | Inspect / archive or restore |
| POST / PUT | `/{id}/draft` | Create numbered draft / save canonical spec and layout |
| POST | `/{id}/validate` | Addressed validation of raw, including unsaved, input |
| POST | `/{id}/publish` | Revalidate, resolve, canonicalize and atomically publish |
| GET | `/{id}/versions` | Paginate history |
| GET | `/{id}/versions/{version_id}` | Inspect exact historical version |
| GET | `/{id}/published` | Retrieve current publication |

Semantic-invalid drafts remain editable. Publication resolves the full immutable
M3 worker/route/profile/provider/retry/permission closure in the transaction and
stores its public snapshot, hashes, compiler version and FK bindings. Publication
clears the draft pointer. Later revisions/retirement cannot mutate that snapshot,
version or a historical run reference. New publication rejects retired references.

Normalized owner-visible `workflow.created/revised/validated/published/archived/
restored` observations use the existing append-only writer and replay/SSE contract.
Validation records the observed unsaved content hash. No runtime activity is
fabricated, and event payloads contain no workflow labels or private references.

## Workflow Studio

Route: `/workflows`. Components: `workflow-studio.tsx`, `workflow-canvas.tsx`,
`workflow-fields.tsx`; generated-type client: `lib/api/workflows.ts`.

The real template list, create/open forms, draft canvas, typed palette, node and
edge inspectors, M3 revision selectors, policy defaults, safe AST controls,
addressed problem panel, version history, publish, new draft and archive/restore
controls call their backend behavior. Canvas add/remove/connect/disconnect,
selection, keyboard/pointer movement, pan/zoom/fit and positions/viewport persist.
Errors preserve edits; published spec and layout are read-only. Mobile navigation,
keyboard outline/inspector and graph controls remain operable. A read-only
projection input prepares future runtime display without advancing workflow state.

## Acceptance and verification evidence

| Gate | Result |
| --- | --- |
| WF-001 executable editor | PASS: real browser draft, typed nodes/policies/references, connections, validation, publication, reload with same version/hash |
| WF-002 validation | PASS: adversarial topology, predicates, references, capabilities, loops, bounds, fanout, approval and verification/review tests |
| WF-003 compilation | PASS: real LangGraph nodes/routes, conditional invocation, long graphs, bounded retry/iteration, identity, native PostgreSQL reconstruction |
| WF-004 isolation | PASS: new draft/version, exact old publication spec/layout/hash and historical run/snapshot reference preservation |
| WF-005 parallel reducers | PASS: varied ordering, identical duplicates, no lost child state, one join, explicit incomplete/conflicting failure |
| DATA-002 | PASS: immutable resolved snapshot/FKs survive configuration retirement and service/graph reconstruction |
| Complete Python and coverage | PASS: 524 tests; 88.68% combined line/branch coverage, above the unchanged 80% repository gate |
| Branch-only coverage | 1,314 / 1,670 branches = 78.68% repository-wide; workflow API/compiler 543 / 630 = 86.19% |
| Final inheritance/encoding regressions | 22 focused API/snapshot/input tests passed |
| Python format/lint/types and pip check | PASS; strict mypy covers 103 source files |
| Migration upgrade/downgrade/drift/roles | PASS in full PostgreSQL suite |
| Contract/OpenAPI/TypeScript drift | PASS: deterministic generated artifacts current |
| Clean npm install | PASS: 599 installed, 600 audited, zero vulnerabilities |
| Prettier / ESLint / TypeScript / Vitest | PASS: 41 tests in 11 files; format/lint/types clean |
| Next production build | PASS: optimized compilation, TypeScript and page generation succeed |
| Playwright | PASS: all 8 tests in 29.3 seconds in final full gate, no skips |
| Accessibility and console | PASS: desktop/mobile axe zero violations, zero serious errors |
| Secret scanner and browser/API canaries | PASS |
| scripts/verify.sh | PASS end to end with PostgreSQL, exit 0: All enabled verification gates passed |
| M4 GitHub exact-commit verify CI | BLOCKED: no authorized write authentication; branch not published |

Local logs/screenshots are ignored artifacts under `.worktrees`: final gate log
`m4-verify-final.log`, focused browser log `m4-browser-final.log`, desktop
`m4-workflow-published.png`, mobile `m4-workflow-mobile.png`. Both screenshots
were visually inspected. The tests use local PostgreSQL and deterministic handlers
or mock transports. Test/lint/security thresholds and lockfile pins were not weakened.
Coverage JSON is `m4-coverage-final.json`; branch-only and combined percentages are
reported separately rather than conflated. One upstream Starlette/AnyIO
deprecation warning remains non-blocking. Initial local gate attempts stopped on
an agent scratch-directory ACL and two test-file Prettier findings; the scratch
was removed and formatting corrected before the final complete run.

## Security, limitations and stop boundary

Reviewed owner/CSRF/origin and object isolation, foreign UUID injection, stale
versions and concurrent writes, idempotency, immutable published SQL rows/FKs,
inactive registry references, credential/private-locator rejection, inert label/
description XSS, malformed layout, finite numbers, JSON byte/depth/count bounds,
safe predicates and restricted node output channels. Secret scanner self-test
detects its canary; repository scanning and browser/API/bundle canaries are clean.
No secrets, private locators, credentials or hidden reasoning were added to Git,
workflow snapshots, events or UI output.

The remaining external blocker is GitHub publication: native dry-run push reports
`Invalid username or token` / `Authentication failed`; the connected GitHub
`create_blob` endpoint reports HTTP 403 `Resource not accessible by integration`.
The final native push attempt exited 128: `could not read Username for
'https://github.com': terminal prompts disabled`; no usable saved credential
remained for the noninteractive push. No code or local acceptance gate is blocked.
No remote ref or main branch was changed. After write authentication is restored,
push `codex/m4-workflow-system`, require green verify CI for its exact HEAD, and
update this record before declaring READY FOR M5. This is an authentication
capability failure, not an automatic approval-review rejection.

V1's intentionally unsupported parallel topologies fail closed. External service
handlers, production runtime lifecycle, crash/effect reconciliation and durable
approval execution retain their planned future milestone gates. Linux GitHub CI
has not run for M4 while publication is blocked.

No Jarvis-Core, Jarvis-Worker-01, real Ollama server or other homelab system was
contacted. No production OpenAI credentials were used. No deployment occurred;
`/opt/jarvis` and `/opt/jarvis-v1` were not modified. No worker SSH, GitHub runtime
publication, M9 approval execution, durable M5 queue, claim/lease/job loop or fake
runtime activity was introduced. Legacy reference files are unchanged.

**Stop at M4. M5 has not started. NOT READY FOR M5 until the remote gate passes.**
