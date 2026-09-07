# Jarvis V1 Provider and Model Routing

Status: normative provider abstraction

## 1. Principles

OpenAI and Ollama are first-class providers behind one typed interface. Provider choice is configuration, not an agent-name branch. Routing is deterministic from a run's immutable snapshot, required capabilities, health/circuit state, and declared policy. Missing optional providers degrade visibly.

Secrets remain in the orchestrator process boundary. Model input/output is treated as untrusted content. Observable metadata and approved final content are available; hidden reasoning is neither requested for display nor persisted as an observability feature.

## 2. Provider interface

```text
validate_connection(connection) -> ValidationReport
list_models(connection) -> ModelCatalog             # optional/discovery only
health(connection) -> ProviderHealth
invoke(request, profile, idempotency_context) -> ModelResult
stream(request, profile, idempotency_context) -> async ModelChunk + ModelResult
normalize_error(native_error) -> ProviderFailure
estimate_usage(request_or_result, profile) -> UsageEstimate
```

The runtime supplies deadlines, cancellation, correlation IDs, and a redacted event sink. Provider-native exceptions and response objects never cross the adapter boundary.

### 2.1 Normalized model request

Contains purpose (`organizer`, `architect`, `developer`, `reviewer`, etc.), validated message/tool/structured-output input, required capabilities, model profile revision, sampling/output limits, deadline, run/node IDs, and data-handling classification. It contains resolved credentials only in transient adapter memory.

### 2.2 Normalized result

Contains final text or structured object, normalized tool calls if enabled, finish status, provider request ID, timing, usage with provenance, selected provider/profile/model, retry/failover history, and a redacted raw-response artifact only when debug policy explicitly permits it.

## 3. Connection, profile, and route separation

- **Provider connection:** how to reach/authenticate to a service (`kind`, base URL, secret reference, TLS/egress policy).
- **Model profile:** immutable behavior for a named model on one connection (model identifier, capabilities, context/output limits, parameters, tokenizer/pricing metadata).
- **Route policy:** ordered candidate profiles plus constraints, health/circuit behavior, retry/failover rules, and remote-data policy.
- **Node policy:** references a route policy and may tighten capabilities/data rules but cannot weaken global security policy.

Editing a connection/profile/route creates a new revision where execution semantics change. Run creation resolves exact revision IDs and effective non-secret settings. Later edits do not alter an active or historical run.

## 4. Capabilities

V1 capability flags include:

- `chat`, `streaming`, `structured_json`, `tool_calls`;
- `max_context_tokens`, `max_output_tokens`;
- supported input media if later enabled;
- `usage_reporting` (`exact`, `partial`, `none`);
- `locality` (`local_lan`, `remote`);
- data classification ceiling and allowed task purposes.

A route is rejected before invocation when a candidate cannot meet a required capability. The UI shows the unmet requirement and candidate rejection reasons without credentials.

## 5. Deterministic routing algorithm

For each model call:

1. Load the snapshotted route and candidate order.
2. Filter candidates disabled in the snapshot or incompatible with required capability, context/output size, purpose, or data classification.
3. Consult current connection health and circuit state. Health changes availability, not candidate order.
4. Select the first eligible candidate by declared priority, then stable profile ID as a tie-breaker.
5. Persist `model.route_selected` and a `model_calls` attempt before sending.
6. Invoke with provider-specific bounded transient retries. Persist each retry/failure.
7. Fail over only for failure classes allowed by route policy and only before a result has been committed to graph state. A failed structured-output validation may retry/repair or route to a compatible candidate as configured.
8. On success, normalize result/usage, persist accounting, close the effect, and return the small result/state reference.
9. If candidates exhaust, emit one classified failure and follow the node's failure route.

No random or silent cheapest/fastest selection occurs in V1. A future dynamic optimizer would require a versioned policy and event-visible decision inputs.

Paid remote routes also enforce snapshotted per-call and per-run request/token/cost limits. Use within an owner-configured budget may be pre-authorized by policy; crossing a limit denies or requests durable approval. When a provider cannot report cost before/after a call, conservative request/token ceilings still apply.

## 6. OpenAI adapter

- Uses the supported OpenAI SDK/API selected during implementation and pins tested versions.
- `base_url` normally uses the official endpoint and remains configurable for testing.
- API key is obtained from a server-side secret reference for each adapter lifecycle and never stored in request/event tables.
- Supports the API features demonstrated by the chosen models; the adapter maps normalized structured-output/tool/stream semantics explicitly rather than assuming every model behaves identically.
- Records provider request IDs, rate-limit/retry guidance where supplied, usage, latency, and finish/error classifications.
- Remote-provider use can be denied by data classification or project policy even when healthy.

Model names/defaults are configuration. Architecture does not bake in a current OpenAI model name.

## 7. Ollama adapter

- Uses the configured LAN endpoint and validates scheme/host against egress policy.
- Ollama remains a distinct adapter even if an OpenAI-compatible endpoint is used, so health, model inventory, keep-alive/options, usage gaps, and errors remain accurate.
- Validates the selected local model exists before a real run where practical; an unloaded but available model may report degraded/warming state.
- Supports native or compatible chat/streaming/structured output only when the deployed Ollama/model combination passes capability probes.
- Missing exact token/cost data is recorded as `unknown` or a labeled tokenizer estimate, never zero-as-fact. Local monetary API cost may be `not_applicable`, while compute/token metrics remain useful.

The AI server URL and model names are runtime configuration, never the observed LAN address hard-coded into source.

## 8. Structured output

Architect, router-supporting model nodes, and Reviewer use explicit versioned JSON schemas. The adapter:

1. uses provider-native schema features when supported;
2. parses without executing content;
3. validates types, sizes, enums, path/command constraints, and task graph invariants;
4. may make a bounded repair retry with validation errors;
5. classifies exhaustion as `provider.contract_failure`.

Malformed output never becomes workflow config, a shell command, a route destination, or reviewer verdict without validation.

### 8.1 Worker-managed model bindings

Some worker frameworks own their model client. A worker revision must declare whether it supports a control-plane-selected profile or only a fixed `worker_managed` profile. The initial legacy OpenHands runner reads model configuration from Worker-01's local environment, so V1 snapshots an opaque declared profile binding and records usage as reported/estimated/unknown. The provider router does not claim to have rerouted that invocation. A GUI model selection is accepted only when the selected worker can actually honor it.

## 9. Retry, failover, and circuit breakers

Failure mappings:

- authentication/permission/invalid model: `configuration.invalid` or provider configuration, no transient retry;
- rate limit: `provider.rate_limited`, honor bounded `Retry-After`;
- timeout, connection reset, provider 5xx: `provider.transient`;
- invalid structured output: `provider.contract_failure`;
- content/policy refusal: explicit `provider.policy_refusal`, route only if policy allows and doing so respects data policy;
- cancelled deadline: cancellation, not provider failure.

Retries use persisted exponential backoff with jitter and configured maxima. Circuit state is connection-scoped with a failure window, open interval, and one/few half-open probes. Circuit changes emit events. Model/provider failures do not consume developer code/test/review budgets.

Failover events identify from/to profiles and reason. The user can determine which model served every call. Calls are side-effect-free relative to repositories, but duplicate user-visible messages/results are prevented through the effect ledger.

A provider timeout can leave a billed-call outcome unknown when the provider offers no query/idempotency facility. The attempt remains `unknown` for accounting, and a policy-authorized retry is a distinct model-call row that may incur additional cost; Jarvis does not claim exactly-once billing.

## 10. Token and cost accounting

Each attempt records:

- prompt, cached, reasoning (when explicitly reported as usage metadata), completion, and total token counts supported by the provider;
- source: `provider`, `tokenizer_estimate`, or `unknown`;
- request queue/connect/first-token/total latency where measurable;
- model profile and price-table snapshot;
- input/output unit prices and currency, or explicit unknown/not-applicable;
- calculated amount using decimal arithmetic;
- retry/failover relationship.

Usage metadata does not expose reasoning content. Aggregations by run, task, node, purpose, provider, and model are derived from call rows. Estimated and exact values are never summed without retaining their provenance/status.

## 11. Health and observability

Health has `healthy`, `degraded`, `unavailable`, `misconfigured`, or `unknown`, measured independently for the connection and individual model capability. Probes are rate-limited and avoid billable generation unless an explicit test is requested. Status transitions emit normalized events; high-frequency samples follow retention policy.

The UI displays provider/locality, configured model, route/failover, current health, call duration, usage/cost status, validation errors, and retries. It does not display raw authorization headers, full prompts by default, secret-bearing native errors, or chain-of-thought.

## 12. Demo adapters

Demo mode registers deterministic provider profiles that return fixture-driven schema-valid outputs, usage, controlled delay, and configured failures. They cannot resolve real secret refs or network endpoints. Adapter construction fails closed if `mode=demo` attempts to instantiate a real provider. Demo events/profile labels are unmistakable.

## 13. Configuration validation tests

Publication/start gates verify connection URL policy, secret reference configured status, model/profile compatibility, route non-emptiness, structured-output support, context limits, disabled candidates, local/remote data policy, retry bounds, and a deterministic no-secret API representation. Live connectivity validation is explicit and reports degradation rather than mutating a published profile.
