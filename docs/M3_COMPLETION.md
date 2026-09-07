# M3 configuration and provider routing evidence

Date: 2026-09-07. Base: fetched `origin/main` at
`ac6206b3b1bfb8e4adca1f414f81807e0a92ebcc` (merged M2). Dedicated branch:
`codex/m3-config-routing`. Shared API/database contracts were pinned in `d31bb53`
before parallel registry, adapter and frontend work. Integration owner owns all
migrations, generated artifacts, dependencies, policy services and final gates.
No reset, legacy modification, homelab contact, production keys or deployment.

## Persistent registries

Six typed kinds reuse M1 `control.configurations` identities and immutable
`configuration_revisions`: worker, provider_connection, model_profile,
route_policy, retry_policy, permission_policy. Revisions include the display,
description, enabled/archive state and typed specification in an M1-compatible
canonical content hash. Reads preserve historical values. Mutations acquire the
global event counter before aggregate locks, enforce expected version and
actor/action-scoped idempotency, and atomically append normalized config events.

Workers describe adapter, safe host label, capabilities, concurrency, labels,
timeouts and exact model binding. Legacy OpenHands SSH declarations require one
worker-managed model and concurrency one. `OpenHandsDeployment` is a server-only
typed manifest with bounded host/user/port, pinned host-key policy, opaque key
references, and canonical absolute POSIX paths. No SSH execution or manifest-file
resolution is introduced. `DemoWorker` validates through the same configuration.

Provider connections have distinct OpenAI/Ollama/DEMO types, endpoint/locality,
egress/data/paid-use policy, timeout/retry revision and circuit settings. Model
profiles pin provider revisions and model identifiers, purposes/capabilities,
context/output limits, structured/tool/stream support, bounded typed parameters,
usage capability and decimal pricing metadata. No product/model names select code
paths. Route candidates pin exact profile revisions.

Private references live separately in immutable
`configuration_private_refs`, never in public specs/events/client output. The
browser writes only opaque locators; ordinary configuration rejects credential-like
strings and arbitrary parameter objects. Provider references can be carried forward,
replaced or cleared without revealing them. Configured status means a reference
exists, not that a production credential was tested. Pre-M3 untyped placeholder
revisions remain immutable; typed listings exclude them before pagination, and
explicit reads return a safe unsupported-revision error.

## Routing and policies

Routing sorts declared candidates by priority then stable revision UUID. Eligibility
checks exact revision identity, enabled/archive status, capability, purpose,
context/output requirement, locality/data policy, missing reference, health and
circuit state. Health never reprioritizes candidates. Failover can skip only
declared candidates for explicitly permitted failure classes. Paid selection never
silently changes to a cheaper model. Disabled/archived current identities veto new
previews without rewriting historical specifications.

The preview reads under the global mutation lock and persists a normalized route
event. The event retains request constraints, result/hash and observed eligibility
state, allowing reconstruction from immutable revision records. Routes are bounded
to 32 candidates so audit remains bounded. No workflow engine or compiler is added.

Retry rules remain class-specific, with finite additional retries, bounded
exponential/constant delays, optional deterministic jitter, exhaustion disposition
and explicit failover permission. Infrastructure/provider failures never consume
semantic code attempts. Configuration/security/cancellation cannot be retried into
success. Permission evaluation combines capability/scope/action/sensitive/
destructive decisions conservatively: deny dominates approval, which dominates
allow. Unknown actions default deny.

Spend policy evaluates input/output ceilings, optional call/run cost ceilings and
paid-use permission. Missing cost or run-spend information cannot satisfy a
configured monetary ceiling. Denial or approval-needed is a durable typed event
outcome. Real LangGraph approval interruption/resume remains M9.

## Adapters, health and accounting

`ProviderAdapter` defines validation/health, invocation, normalized async stream,
failure normalization and usage estimation. OpenAI uses pinned SDK 3.8.0 Responses
API with injected httpx2 transport and SDK retries disabled; Ollama uses native
HTTP chat/tags semantics via httpx. Both bound response bytes/deadlines, disable
redirects/proxy environment, require exact server endpoint authorization and prevent
ambient OpenAI headers from injecting credentials. JSON Schema validation cannot
resolve external references. Native errors/response objects never cross the boundary.

Native streams are consumed with bounds, then validated/redacted before normalized
chunks are emitted; this prevents secrets split across deltas escaping. M3 provides
the streaming protocol but does not claim low-latency token-by-token UI delivery.
DEMO uses the same result/chunk types, deterministic configured outcomes/chunks/
usage/failure sequence and controlled latency, with no secret/network construction.

`HealthService` persists revision-scoped health and circuit state. Failure windows
and thresholds open the circuit, cooldown gates a single fenced half-open probe,
and valid successful probes recover it. Stale/expired completions cannot close an
open circuit. Transitions emit normalized events; DEMO health is marked DEMO.
There is no background health polling service in M3. GUI validation checks
configuration and honestly reports unprobed state; adapter probes are local fake
contract tests only.

`AccountingService` persists immutable idempotent call records and usage events.
It validates provider/profile/route references, correlation scope, the exact
profile pricing snapshot, computed decimal cost and DEMO identity. Exact, estimated,
unknown and not-applicable remain distinct; unknown amount is null, not zero.
Uncertain billed-call outcomes can be retained as unknown. Request IDs and metadata
are credential checked. Runtime scheduling and exactly-once billing are not claimed.

## API and GUI

All API paths below are owner-only; mutations/preview require CSRF and exact origin.
Lists use bounded UUID keyset pagination. Generated OpenAPI and Pydantic JSON Schema
are consumed by the TypeScript client, with byte-for-byte drift gates.

| Method | Route | Behavior |
| --- | --- | --- |
| GET / POST | `/api/v1/registry/{kind}` | List/create typed configuration |
| GET / PUT | `/api/v1/registry/{kind}/{id}` | Inspect/create next immutable revision |
| GET | `/api/v1/registry/{kind}/{id}/revisions` | Historical revision pages |
| POST | `/api/v1/registry/{kind}/{id}/validate` | Idempotent configuration-only validation |
| POST | `/api/v1/routing/preview` | Deterministic audited eligibility/spend decision |
| GET | `/api/v1/accounting` | Immutable usage/cost record pages |

Real GUI routes: `/workers`, `/providers`, `/models`, `/routing`, `/policies`,
and `/registry` hub. Forms provide creation/editing, enabled/archive state,
validation and revision history; masked private reference status, capabilities,
model limits/pricing and ordered route selection; retry and permission editors.
Historical model bindings remain inspectable/removable. The Next same-origin proxy
now forwards PUT with method/body/CSRF intact; real browser testing found and fixed
the missing M2 method export.

## Migration and dependencies

Migration **0004** adds configuration descriptions, immutable private-reference
rows, provider health/circuit storage and immutable indexed model-call accounting.
It grants only required API/orchestrator operations; diagnostics cannot read private
references. All previous migrations remain unchanged. Clean/M1-to-head upgrade,
downgrade/upgrade and metadata drift are covered using PostgreSQL 16. API readiness
expects revision 0004. JSON Schema validator 4.26.0 and matching type stubs were
added with locked transitive dependencies; existing pins were retained.

## Verification and security evidence

Supported local runtimes: Python 3.12.14, Node 20.19.0, PostgreSQL 16.10.
Full final `scripts/verify.sh` and GitHub CI evidence is recorded below. A clean
npm install completed before verification. The gate includes pip check, Ruff, strict mypy,
complete pytest/PostgreSQL/coverage, deterministic schemas, frontend formatting,
lint/type/unit checks, standard production build, audit and real Chromium tests.

The final Python run passed **383 tests in 83.75 seconds**, with **88.05% branch
coverage** (required 80%). This includes OpenAI/Ollama/DEMO contract and server-only
worker manifest cases, deterministic routing/policy matrices, and real PostgreSQL
role/concurrency/immutability/accounting tests. The isolated provider suite passed
121 tests at 89.34% coverage; the registry/API/routing slice passed 24 tests.
Python formatting, lint, strict mypy (85 files), migration gates and generated
schema/OpenAPI/TypeScript drift checks passed. The single pytest warning is a
Starlette TestClient/AnyIO deprecated BlockingPortal alias, not an M3 test failure.

Security review corrected explicit-deny precedence, combined sensitive/destructive
decisions, stale circuit recovery, mismatched revision IDs, cost/pricing/route
accounting integrity, idempotency-key canaries, parameter type injection and web PUT
forwarding. Browser test uses a fresh loopback DB, real least-privilege API role and
production Next server. It tests successful opaque reference writes without
round-trip, raw canary rejection, immutable history, preview allow/deny, keyboard
focus, desktop/mobile axe and console output. Logs/bundles/DOM are canary scanned;
desktop and mobile screenshots were visually reviewed.

## Final gate

`scripts/verify.sh` passed every gate with local PostgreSQL enabled and no
Playwright skip: 383 Python tests, 88.05% branch coverage; 32 frontend tests across
nine files; seven Chromium tests in 27.0 seconds. Prettier, ESLint, TypeScript,
production Next build, migration up/down/drift, generated contract drift and
secret scans passed. `npm audit --audit-level=high` reported zero vulnerabilities.
Desktop/mobile M3 axe checks found zero violations; serious console/page errors
were absent. API logs and browser bundles passed secret canary checks.

All local M3-owned blockers are resolved. Native Git rejects the saved GitHub
credential with “Invalid username or token”; publication and remote GitHub CI
remain blocked pending user credential refresh. No CI success or main merge is
claimed. The implementation and this evidence are committed together on
`codex/m3-config-routing`; use `git rev-parse HEAD` for the final commit identity.
Recommendation: **NOT READY FOR M4** until publication and final GitHub CI pass.
No homelab system was contacted, no deployment occurred, and M4 is unstarted.

Final adapter review added normalized tool definitions and calls for OpenAI,
Ollama and DEMO, including streaming terminal results. Names, IDs, counts and
argument schemas are checked before release; sensitive or undeclared calls fail
closed. No tool execution is implemented. Provider-specific parameter sets are
validated before persistence and invocation; unsupported settings are rejected
instead of discarded. Native connection timeouts honor the configured connect
deadline separately from the total request deadline.

Publication review: the final push was rejected before Git executed by automatic
approval review. It requires explicit approval to export the private M3 source
and history to `https://github.com/ClearPointSolutions/Jarvis-Development.git`.
No workaround was attempted. Earlier dry-run authentication also failed; that
credential issue has not been verified as resolved. GitHub CI remains unrun.
