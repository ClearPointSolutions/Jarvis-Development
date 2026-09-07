# M4 shared contract

The integration-owner contract commit pins Pydantic workflow spec **1.1**, node
version **1.0**, state schema `jarvis.workflow_state.v1`, compiler **1.0.0**.
M1's incomplete 1.0 envelope remains recognizable, but the executable M4 compiler
must explicitly reject it. Historical database rows are never rewritten.

`workflow.py`, `workflow_nodes.py`, and `workflow_api.py` are authoritative.
Generated JSON Schema and TypeScript are consumed directly. Configs remain under
each canonical node's `config` field; static `NODE_DEFINITIONS` supplies the typed
model, defaults, required capabilities, input/output channels and policy schema.
Draft persistence materializes effective policies before serialization can lose
omitted-versus-explicit overrides. Publication additionally normalizes typed
config defaults before hashing. Idempotency distinguishes omitted policy fields
from explicit false overrides. Workflow command JSON is UTF-8 with byte and
pre-parse depth guards; other encodings are rejected.
No user executable code is accepted. External node handlers are injected in
compiler tests; missing real services fail explicitly. M5–M10 effects are deferred.

Policy references are exact immutable M3 revision UUIDs. `worker_selector` contains
`revision_id` and `requires`. Model/retry/permission refs retain their documented
field names. Verification is typed (`source=task`, `required`); approval names a
typed action and granting node. Snapshot revisions contain public immutable M3
envelopes and hashes, never private locators, credentials or live health state.

Edges use `from`, `to`, kind (`always`, `on_result`, `on_failure`, `retry`,
`iterate`), priority, fallback, and the existing safe predicate AST. Exactly one
fallback is required for conditional groups. Retry limits come from resolved M3
rules. Iterators enforce strictly increasing `$.tasks.terminal_count` and a hard
bound; Architect task count cannot exceed it. Removing retry/iterate back edges
must leave an acyclic graph. A bounded edge cannot conceal an unbounded subcycle.

Explicit fanout config names unique child entry node IDs, matching `join_id`,
`max_fanout` and `wait_all` cancellation. Join config names `fanout_id` and requires
all expected children. Child identities include fanout identity and child ID;
reducers merge by stable identity, reject conflicting duplicates, and preserve
every result independent of completion ordering. Parallel children cannot write
unreduced scalar channels. Nested/overlapping fanouts and cycles inside parallel
branches may fail explicitly if unsupported in V1; never compile unsafe semantics.

Resource ceilings: 500 nodes, 2,000 edges, graph depth 500, 1 MiB JSON, JSON depth
24, 160-character labels, 2,000-character descriptions, predicate depth 8 and 64
AST nodes per condition, iterator 10,000, fanout 64. Layout has finite bounded x/y
and zoom only, keyed by existing node IDs. It is stored separately, excluded from
the executable hash, and immutable on a published version.

## API integration surface

All paths start `/api/v1/workflow-templates`, require owner access, and writes
require CSRF/origin. `expected_version` is the **template** optimistic version.
Mutations are actor/action/template scoped idempotent and increment that version.
Validation only audits an observation and leaves the template version unchanged.

| Method/path | Body | Response |
| --- | --- | --- |
| GET root | after/limit query | WorkflowTemplatePage |
| POST root | WorkflowCreateRequest | WorkflowDocument (initial finalize draft) |
| GET `/node-types` | — | NodeTypePage |
| GET `/{id}` | — | WorkflowDocument (current draft else published) |
| PUT `/{id}` | WorkflowArchiveRequest | WorkflowTemplateRecord |
| POST `/{id}/draft` | WorkflowNewDraft | WorkflowDocument |
| PUT `/{id}/draft` | WorkflowDraftWrite | WorkflowDocument |
| POST `/{id}/validate` | WorkflowValidateRequest | WorkflowValidationReport |
| POST `/{id}/publish` | WorkflowCommand | WorkflowDocument |
| GET `/{id}/versions` | after/limit query | WorkflowVersionPage |
| GET `/{id}/versions/{version_id}` | — | WorkflowDocument |
| GET `/{id}/published` | — | WorkflowDocument |

Validation accepts raw canonical-spec input so schema errors can address original
node/edge IDs. Reports use stable issue `code`, `message`, `node_id`, `edge_id`,
and `path`. Saving does not require semantic validity; publication repeats all
validation and resolves an immutable snapshot in the mutation transaction.
Publishing clears the current draft pointer. Editing a published version creates
a new numbered draft. Archive affects new editing/publication, never history.

Integration owner owns contracts, migrations, schema generation, API/service,
snapshot resolution and docs/status. M4A owns compiler/validation/factories/tests;
M4B owns web studio/inspectors/client/browser tests. Both consume this commit.
