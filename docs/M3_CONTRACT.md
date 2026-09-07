# M3 integration contract

Authority: `jarvis_contracts.registry`, existing immutable configuration models and
the new `ConfigurationPrivateRefModel`, `ProviderHealthModel`, `ModelCallModel`.
No prior migration changes. Integration owner reserves migration 0004.

## Storage

Six kinds reuse control.configurations and configuration_revisions. Revision
spec_json is an envelope containing spec (validated discriminated RegistrySpec),
display_name, description, enabled, archived. Hash includes this whole envelope.
Each semantics/state edit creates a revision under global-event-counter then
configuration-row locking. Current identity version increments once. Expected
version rejects stale updates. Historical reads use revision envelope, not latest
identity fields. Private refs are stored separately per revision and never returned.
Idempotency records use existing repository primitives, scoped to actor/action.
All visible string fields reject credential-like input before ordinary persistence.

## API

- GET `/api/v1/registry/{kind}` -> RegistryPage, query after UUID and limit 1–100.
- POST `/api/v1/registry/{kind}` RegistryWrite -> RegistryRecord.
- GET `/api/v1/registry/{kind}/{id}` -> RegistryRecord.
- PUT `/api/v1/registry/{kind}/{id}` RegistryWrite -> RegistryRecord.
- GET `/api/v1/registry/{kind}/{id}/revisions` -> RegistryPage.
- POST `/api/v1/registry/{kind}/{id}/validate` -> ValidationReport (configuration
  validation only; no network). JSON body with idempotency key required.
- POST `/api/v1/routing/preview` RoutePreviewRequest -> RouteResolution.
- GET `/api/v1/accounting` -> AccountingPage.

All owner-only; mutations and preview require CSRF and exact origin. Preview is
server-side deterministic evaluation and emits a normalized event. Validation
reports configured/missing references without reading secret files in API.
Endpoint creation must meet a server-managed exact allowlist, independent of
browser-supplied egress policy; redirects, credentialed/unsafe URLs reject.

## Provider service boundary

Adapters live in jarvis_orchestrator.providers, accept ProviderSpec,
ModelProfileSpec and their exact revision UUIDs plus injected local/mock HTTP
client and secret resolver. No network call from API routes. No production
credentials read in tests. Common protocol has validate_connection, health,
invoke(ProviderRequest), stream(ProviderRequest), normalize_error, estimate_usage.
Return ValidationReport, ProviderResult, ProviderChunk, ProviderFailure, Usage.
Streaming ends with a normalized result chunk. Cancellation is explicit; native
exceptions/objects never escape. Network clients disable redirects and ambient
proxy credentials. Demo constructor cannot use network or resolve secrets.

## Ownership

Integration owner: contracts, models, migration, generated artifacts, routing,
retry/permission/spend evaluators, durable health/accounting, event registry,
root configuration and documentation, final acceptance runner and CI.
Backend agent: registry API/repository and focused integration/security tests.
Provider agent: adapters and focused contract tests.
Frontend agent: real registry/forms/routes and frontend/browser tests.
