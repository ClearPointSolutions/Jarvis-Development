"use client";

import { useEffect, useMemo, useState, type FormEvent } from "react";
import {
  useInfiniteQuery,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import type { Connection } from "@xyflow/react";
import type {
  NodeTypeDefinition,
  RegistryRecord,
  WorkflowDocument,
  WorkflowEdge,
  WorkflowLayout,
  WorkflowSpec,
  WorkflowValidationReport,
} from "@jarvis/contracts";
import {
  createWorkflowClient,
  WorkflowRequestError,
  type WorkflowClient,
} from "@/lib/api/workflows";
import { createRegistryClient } from "@/lib/api/registry";
import { useSession } from "@/lib/session";
import {
  ConfigFields,
  EdgeFields,
  PolicyFields,
  humanize,
} from "./workflow-fields";
import {
  WorkflowCanvas,
  nodePosition,
  type WorkflowSelection,
} from "./workflow-canvas";

const errorMessage = (error: unknown) =>
  error instanceof Error
    ? error.message
    : "The request failed. Please try again.";
const command = (document: WorkflowDocument) => ({
  expected_version: document.template.version,
  idempotency_key: crypto.randomUUID(),
});

export function WorkflowStudio({
  client: injectedClient,
}: {
  client?: WorkflowClient;
}) {
  const session = useSession();
  const client = useMemo(
    () => injectedClient ?? createWorkflowClient(session.data?.csrf_token),
    [injectedClient, session.data?.csrf_token],
  );
  const registry = useMemo(
    () => createRegistryClient(session.data?.csrf_token),
    [session.data?.csrf_token],
  );
  const cache = useQueryClient();
  const enabled = Boolean(session.data || injectedClient);
  const [document, setDocument] = useState<WorkflowDocument | null>(null);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const templates = useInfiniteQuery({
    queryKey: ["workflows"],
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) => client.list(pageParam),
    getNextPageParam: (page) => page.next_after ?? undefined,
    enabled,
  });
  const nodeTypes = useQuery({
    queryKey: ["workflow-node-types"],
    queryFn: () => client.nodeTypes(),
    enabled,
  });
  const references = useQuery({
    queryKey: ["workflow-registry-references"],
    enabled,
    queryFn: async () => {
      const pages = await Promise.all(
        (
          [
            "worker",
            "route_policy",
            "retry_policy",
            "permission_policy",
          ] as const
        ).map(async (kind) => {
          const records: RegistryRecord[] = [];
          let after: string | undefined;
          do {
            const page = await registry.list(kind, after);
            records.push(...page.items);
            after = page.next_after ?? undefined;
          } while (after);
          return records;
        }),
      );
      return pages.flat();
    },
  });
  useEffect(() => {
    if (!enabled) return;
    const params = new URLSearchParams(window.location.search);
    const id = params.get("template");
    const versionId = params.get("version");
    if (!id) return;
    let cancelled = false;
    const request = versionId ? client.version(id, versionId) : client.get(id);
    request
      .then((result) => {
        if (!cancelled) setDocument(result);
      })
      .catch((error: unknown) => {
        if (!cancelled) setError(errorMessage(error));
      });
    return () => {
      cancelled = true;
    };
  }, [client, enabled]);
  function show(result: WorkflowDocument) {
    setDocument(result);
    setCreating(false);
    setError("");
    window.history.replaceState(
      null,
      "",
      `/workflows?template=${encodeURIComponent(result.template.id)}${result.version.published ? `&version=${encodeURIComponent(result.version.id)}` : ""}`,
    );
  }
  async function open(id: string) {
    setBusy(true);
    setError("");
    try {
      show(await client.get(id));
    } catch (error) {
      setError(errorMessage(error));
    } finally {
      setBusy(false);
    }
  }
  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const data = new FormData(event.currentTarget);
    try {
      show(
        await client.create({
          key: String(data.get("key")),
          name: String(data.get("name")),
          description: String(data.get("description")),
          idempotency_key: crypto.randomUUID(),
        }),
      );
      await cache.invalidateQueries({ queryKey: ["workflows"] });
    } catch (error) {
      setError(errorMessage(error));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="page-stack workflow-studio">
      <header className="page-header">
        <p className="eyebrow">Versioned orchestration</p>
        <h1>Workflow Studio</h1>
        <p>
          Design, validate, and publish the workflow that LangGraph will
          execute.
        </p>
      </header>
      {error || templates.error || nodeTypes.error || references.error ? (
        <p className="inline-alert" role="alert">
          {error ||
            errorMessage(
              templates.error ?? nodeTypes.error ?? references.error,
            )}
        </p>
      ) : null}
      {document ? (
        <WorkflowEditor
          key={document.version.id}
          document={document}
          client={client}
          definitions={nodeTypes.data?.items ?? []}
          references={references.data ?? []}
          onClose={() => {
            setDocument(null);
            window.history.replaceState(null, "", "/workflows");
          }}
          onDocument={show}
          onSaved={() => {
            void cache.invalidateQueries({ queryKey: ["workflows"] });
          }}
        />
      ) : (
        <>
          <div className="registry-toolbar">
            <button
              className="button button-primary"
              onClick={() => setCreating(true)}
            >
              Create workflow
            </button>
            <button
              className="button button-secondary"
              disabled={templates.isFetching || busy}
              onClick={() => void templates.refetch()}
            >
              Refresh workflows
            </button>
            <span>
              {templates.data?.pages.flatMap((p) => p.items).length ?? 0}{" "}
              templates
            </span>
          </div>
          {creating ? (
            <form
              className="content-card registry-editor"
              onSubmit={(event) => void create(event)}
            >
              <h2>Create workflow</h2>
              <div className="registry-form-grid">
                <label className="field-group">
                  Workflow key
                  <input
                    name="key"
                    autoFocus
                    required
                    pattern="[a-z](?:[a-z0-9_]|-)*"
                    maxLength={100}
                  />
                </label>
                <label className="field-group">
                  Workflow name
                  <input name="name" required maxLength={160} />
                </label>
              </div>
              <label className="field-group">
                Workflow description
                <textarea name="description" maxLength={2000} />
              </label>
              <div className="registry-actions">
                <button className="button button-primary" disabled={busy}>
                  Create draft
                </button>
                <button
                  className="button button-secondary"
                  type="button"
                  disabled={busy}
                  onClick={() => setCreating(false)}
                >
                  Cancel
                </button>
              </div>
            </form>
          ) : null}
          {templates.isPending ? <p role="status">Loading workflows…</p> : null}
          <div className="workflow-template-grid">
            {templates.data?.pages
              .flatMap((page) => page.items)
              .map((item) => (
                <article key={item.id} className="content-card">
                  <p className="eyebrow">
                    {item.archived
                      ? "Archived"
                      : item.current_draft_version_id
                        ? "Draft available"
                        : "Published"}
                  </p>
                  <h2>{item.name}</h2>
                  <p>{item.description || "No description"}</p>
                  <p className="registry-key">{item.key}</p>
                  <button
                    className="button button-secondary"
                    disabled={busy}
                    onClick={() => void open(item.id)}
                  >
                    Open {item.name}
                  </button>
                </article>
              ))}
          </div>
          {templates.data?.pages[0]?.items.length === 0 ? (
            <section className="content-card">
              <h2>Build your first workflow</h2>
              <p>
                Start with a finalization node, then add the typed steps and
                policies your project needs.
              </p>
            </section>
          ) : null}
          {templates.hasNextPage ? (
            <button
              className="button button-secondary"
              disabled={templates.isFetchingNextPage}
              onClick={() => void templates.fetchNextPage()}
            >
              Load more workflows
            </button>
          ) : null}
        </>
      )}
    </div>
  );
}

export function WorkflowEditor({
  document: initial,
  client,
  definitions,
  references,
  onClose,
  onDocument,
  onSaved,
}: {
  document: WorkflowDocument;
  client: WorkflowClient;
  definitions: NodeTypeDefinition[];
  references: RegistryRecord[];
  onClose: () => void;
  onDocument: (value: WorkflowDocument) => void;
  onSaved: () => void;
}) {
  const [document, setDocument] = useState(initial);
  const [spec, setSpec] = useState(initial.version.spec);
  const [layout, setLayout] = useState<WorkflowLayout>(() => ({
    ...initial.version.layout,
    nodes: Object.fromEntries(
      initial.version.spec.nodes.map((node, index) => [
        node.id,
        nodePosition(initial.version.layout, index, node.id),
      ]),
    ),
  }));
  const [selection, setSelection] = useState<WorkflowSelection>(null);
  const [report, setReport] = useState<WorkflowValidationReport | null>(null);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [history, setHistory] = useState(false);
  const [defaults, setDefaults] = useState(false);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const readOnly =
    document.version.published || document.template.archived || busy;
  const versions = useInfiniteQuery({
    queryKey: [
      "workflow-versions",
      document.template.id,
      document.template.version,
    ],
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) =>
      client.versions(document.template.id, pageParam),
    getNextPageParam: (page) => page.next_after ?? undefined,
    enabled: history,
  });
  const selectedNode =
    selection?.kind === "node"
      ? spec.nodes.find((n) => n.id === selection.id)
      : undefined;
  const selectedEdge =
    selection?.kind === "edge"
      ? spec.edges.find((e) => e.id === selection.id)
      : undefined;
  function changeSpec(value: WorkflowSpec) {
    if (readOnly) return;
    setSpec(value);
    setDirty(true);
    setReport(null);
    setNotice("");
  }
  function changeLayout(
    value: WorkflowLayout | ((current: WorkflowLayout) => WorkflowLayout),
  ) {
    if (readOnly) return;
    setLayout(value);
    setDirty(true);
    setNotice("");
  }
  function replaceNode(node: WorkflowSpec["nodes"][number]) {
    changeSpec({
      ...spec,
      nodes: spec.nodes.map((n) =>
        n.id === node.id ? node : n,
      ) as WorkflowSpec["nodes"],
    });
  }
  function replaceEdge(edge: WorkflowEdge) {
    changeSpec({
      ...spec,
      edges: spec.edges.map((e) => (e.id === edge.id ? edge : e)),
    });
  }
  function addNode(definition: NodeTypeDefinition) {
    let index = 1;
    let id = definition.type as string;
    while (spec.nodes.some((n) => n.id === id))
      id = `${definition.type}_${++index}`;
    changeSpec({
      ...spec,
      nodes: [
        ...spec.nodes,
        {
          id,
          type: definition.type,
          node_version: "1.0",
          label: humanize(definition.type),
          config: structuredClone(definition.default_config),
          policy: {},
        },
      ],
    });
    changeLayout({
      ...layout,
      nodes: {
        ...layout.nodes,
        [id]: {
          x: (spec.nodes.length % 3) * 240,
          y: Math.floor(spec.nodes.length / 3) * 150,
        },
      },
    });
    setSelection({ kind: "node", id });
    setDefaults(false);
  }
  function connect(connection: Pick<Connection, "source" | "target">) {
    if (readOnly || spec.edges.length >= 2000) return;
    let index = 1;
    let id = `edge_${index}`;
    while (spec.edges.some((e) => e.id === id)) id = `edge_${++index}`;
    changeSpec({
      ...spec,
      edges: [
        ...spec.edges,
        {
          id,
          from: connection.source,
          to: connection.target,
          kind: "always",
          priority: 0,
          fallback: false,
        },
      ],
    });
    setSelection({ kind: "edge", id });
    setDefaults(false);
  }
  function remove(nodeIds: string[], edgeIds: string[]) {
    if (readOnly) return;
    const nodes = spec.nodes.filter((n) => !nodeIds.includes(n.id));
    if (!nodes.length) {
      setError(
        "A workflow needs at least one node. Add a replacement before removing the last node.",
      );
      return;
    }
    changeSpec({
      ...spec,
      entrypoint: nodeIds.includes(spec.entrypoint)
        ? nodes[0].id
        : spec.entrypoint,
      nodes: nodes as WorkflowSpec["nodes"],
      edges: spec.edges.filter(
        (e) =>
          !edgeIds.includes(e.id) &&
          !nodeIds.includes(e.from) &&
          !nodeIds.includes(e.to),
      ),
    });
    changeLayout({
      ...layout,
      nodes: Object.fromEntries(
        Object.entries(layout.nodes ?? {}).filter(
          ([id]) => !nodeIds.includes(id),
        ),
      ),
    });
    setSelection(null);
  }
  async function perform(action: () => Promise<void>) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await action();
    } catch (error) {
      setError(errorMessage(error));
      if (error instanceof WorkflowRequestError && error.validation)
        setReport(error.validation);
    } finally {
      setBusy(false);
    }
  }
  function accepted(result: WorkflowDocument) {
    setDocument(result);
    setSpec(result.version.spec);
    setLayout(result.version.layout);
    setDirty(false);
    onSaved();
  }
  async function save() {
    const result = await client.save(document.template.id, {
      ...command(document),
      spec,
      layout,
    });
    accepted(result);
    setNotice(`Saved draft version ${result.version.version}.`);
    return result;
  }
  async function validate() {
    const result = await client.validate(document.template.id, {
      ...command(document),
      spec: { ...spec },
      layout: { ...layout },
    });
    setReport(result);
    setNotice(
      result.valid
        ? "Workflow valid. The server resolved all required references."
        : "Validation found problems. Select a problem to inspect its node or edge.",
    );
    return result;
  }
  async function publish() {
    const validation = await validate();
    if (!validation.valid) return;
    const current = dirty ? await save() : document;
    const result = await client.publish(current.template.id, command(current));
    accepted(result);
    onDocument(result);
    setNotice(`Published version ${result.version.version}.`);
  }
  return (
    <section className="workflow-editor" aria-label="Workflow editor">
      <div className="registry-toolbar">
        <button className="text-button" disabled={busy} onClick={onClose}>
          All workflows
        </button>
        <span className="workflow-version-badge">
          {document.template.archived
            ? "Archived"
            : document.version.published
              ? "Published · read only"
              : "Draft"}{" "}
          · version {document.version.version}
        </span>
        <span>{dirty ? "Unsaved changes" : "All changes saved"}</span>
      </div>
      <div className="workflow-toolbar">
        <div>
          <h2>{spec.name}</h2>
          <p className="registry-key">
            {spec.key} · spec {spec.spec_version} · compiler{" "}
            {document.version.compiler_version}
          </p>
        </div>
        <div className="registry-actions">
          {!document.version.published && !document.template.archived ? (
            <>
              <button
                className="button button-secondary"
                disabled={busy || !dirty}
                onClick={() =>
                  void perform(async () => {
                    await save();
                  })
                }
              >
                Save draft
              </button>
              <button
                className="button button-secondary"
                disabled={busy}
                onClick={() =>
                  void perform(async () => {
                    await validate();
                  })
                }
              >
                Validate workflow
              </button>
              <button
                className="button button-primary"
                disabled={busy}
                onClick={() => void perform(publish)}
              >
                Publish version
              </button>
            </>
          ) : !document.template.archived ? (
            <button
              className="button button-primary"
              disabled={busy}
              onClick={() =>
                void perform(async () => {
                  onDocument(
                    await client.newDraft(document.template.id, {
                      ...command(document),
                      source_version_id: document.version.id,
                    }),
                  );
                  onSaved();
                })
              }
            >
              Create new draft
            </button>
          ) : null}
          <button
            className="button button-secondary"
            disabled={busy}
            onClick={() => setHistory(!history)}
          >
            {history ? "Close version history" : "Version history"}
          </button>
          <button
            className="text-button"
            disabled={busy || dirty}
            onClick={() =>
              void perform(async () => {
                const template = await client.archive(document.template.id, {
                  ...command(document),
                  archived: !document.template.archived,
                });
                setDocument({ ...document, template });
                onSaved();
              })
            }
          >
            {document.template.archived
              ? "Restore template"
              : "Archive template"}
          </button>
        </div>
      </div>
      {notice ? (
        <p role="status" className="registry-notice">
          {notice}
        </p>
      ) : null}
      {error ? (
        <p role="alert" className="inline-alert">
          {error}
        </p>
      ) : null}
      {history ? (
        <section className="content-card" aria-label="Version history">
          <h3>Version history</h3>
          {versions.isPending ? <p role="status">Loading versions…</p> : null}
          {versions.error ? (
            <p role="alert">{errorMessage(versions.error)}</p>
          ) : null}
          {versions.data?.pages
            .flatMap((p) => p.items)
            .map((version) => (
              <div className="workflow-history-row" key={version.id}>
                <div>
                  <strong>Version {version.version}</strong> ·{" "}
                  {version.published ? "Published" : "Draft"}
                  <p className="registry-key">{version.id}</p>
                  <p className="registry-key">SHA-256 {version.content_hash}</p>
                </div>
                <button
                  className="button button-secondary"
                  disabled={busy || dirty}
                  onClick={() =>
                    void perform(async () => {
                      onDocument(
                        await client.version(document.template.id, version.id),
                      );
                    })
                  }
                >
                  View version {version.version}
                </button>
              </div>
            ))}
          {dirty ? (
            <p>Save your draft before opening another version.</p>
          ) : null}
          {versions.hasNextPage ? (
            <button
              className="button button-secondary"
              onClick={() => void versions.fetchNextPage()}
            >
              Load more versions
            </button>
          ) : null}
        </section>
      ) : null}
      <details className="workflow-settings">
        <summary>Workflow settings and default policies</summary>
        <fieldset disabled={readOnly}>
          <div className="registry-form-grid">
            <label className="field-group">
              Workflow name
              <input
                maxLength={160}
                value={spec.name}
                onChange={(e) => changeSpec({ ...spec, name: e.target.value })}
              />
            </label>
            <label className="field-group">
              Entry node
              <select
                value={spec.entrypoint}
                onChange={(e) =>
                  changeSpec({ ...spec, entrypoint: e.target.value })
                }
              >
                {spec.nodes.map((n) => (
                  <option key={n.id} value={n.id}>
                    {n.label} ({n.id})
                  </option>
                ))}
              </select>
            </label>
          </div>
          <label className="field-group">
            Workflow description
            <textarea
              maxLength={2000}
              value={spec.description ?? ""}
              onChange={(e) =>
                changeSpec({ ...spec, description: e.target.value })
              }
            />
          </label>
        </fieldset>
        <button
          className="button button-secondary"
          onClick={() => {
            setDefaults(true);
            setSelection(null);
          }}
        >
          Inspect default policies
        </button>
      </details>
      <div className="workflow-workspace">
        <aside className="workflow-palette" aria-label="Node palette">
          <h3>Node palette</h3>
          <p>{spec.nodes.length} / 500 nodes</p>
          {definitions.map((definition) => (
            <button
              key={definition.type}
              className="workflow-palette-button"
              aria-label={`Add ${humanize(definition.type)}`}
              disabled={readOnly || spec.nodes.length >= 500}
              onClick={() => addNode(definition)}
            >
              <strong>Add {humanize(definition.type)}</strong>
              <small>
                {definition.required_capabilities.length
                  ? definition.required_capabilities.join(" · ")
                  : definition.external_behavior
                    ? "Service contract"
                    : "Graph control"}
              </small>
            </button>
          ))}
        </aside>
        <div className="workflow-graph-column">
          <WorkflowCanvas
            spec={spec}
            layout={layout}
            readOnly={readOnly}
            selection={selection}
            issues={report?.issues}
            onSelect={(value) => {
              setSelection(value);
              setDefaults(false);
            }}
            onLayout={changeLayout}
            onConnect={connect}
            onRemove={remove}
          />
          <p className="workflow-help">
            Drag to arrange · Connect handles · Scroll to zoom · Tab to select ·
            Arrow keys to move · Delete to remove
          </p>
          <details className="workflow-outline">
            <summary>Keyboard outline and connections</summary>
            <div className="workflow-outline-list">
              {spec.nodes.map((node) => (
                <button
                  className="button button-secondary"
                  key={node.id}
                  onClick={() => {
                    setSelection({ kind: "node", id: node.id });
                    setDefaults(false);
                  }}
                >
                  Inspect {node.label} ({node.id})
                </button>
              ))}
              {spec.edges.map((edge) => (
                <button
                  className="text-button"
                  key={edge.id}
                  onClick={() => {
                    setSelection({ kind: "edge", id: edge.id });
                    setDefaults(false);
                  }}
                >
                  Inspect edge {edge.id}: {edge.from} → {edge.to}
                </button>
              ))}
            </div>
            <fieldset disabled={readOnly} className="registry-form-grid">
              <label className="field-group">
                Connect from
                <select value={from} onChange={(e) => setFrom(e.target.value)}>
                  <option value="">Choose source</option>
                  {spec.nodes.map((node) => (
                    <option key={node.id} value={node.id}>
                      {node.label} ({node.id})
                    </option>
                  ))}
                </select>
              </label>
              <label className="field-group">
                Connect to
                <select value={to} onChange={(e) => setTo(e.target.value)}>
                  <option value="">Choose target</option>
                  {spec.nodes.map((node) => (
                    <option key={node.id} value={node.id}>
                      {node.label} ({node.id})
                    </option>
                  ))}
                </select>
              </label>
              <button
                className="button button-secondary"
                disabled={
                  readOnly ||
                  !spec.nodes.some((n) => n.id === from) ||
                  !spec.nodes.some((n) => n.id === to)
                }
                onClick={() => connect({ source: from, target: to })}
              >
                Connect nodes
              </button>
            </fieldset>
          </details>
        </div>
        <aside
          className="workflow-inspector"
          aria-label="Workflow inspector"
          tabIndex={0}
        >
          <h3>
            {defaults
              ? "Default policies"
              : selectedNode
                ? "Node inspector"
                : selectedEdge
                  ? "Edge inspector"
                  : "Inspector"}
          </h3>
          {defaults ? (
            <fieldset disabled={readOnly}>
              <PolicyFields
                policy={spec.defaults ?? {}}
                references={references}
                nodes={spec.nodes}
                onChange={(policy) => changeSpec({ ...spec, defaults: policy })}
              />
            </fieldset>
          ) : selectedNode ? (
            <>
              <p className="registry-key">
                {selectedNode.id} · {selectedNode.type}
              </p>
              <fieldset disabled={readOnly}>
                <label className="field-group">
                  Node label
                  <input
                    maxLength={160}
                    value={selectedNode.label}
                    onChange={(e) =>
                      replaceNode({ ...selectedNode, label: e.target.value })
                    }
                  />
                </label>
                {definitions.find((d) => d.type === selectedNode.type) ? (
                  <ConfigFields
                    key={`config-${selectedNode.id}`}
                    definition={definitions.find(
                      (d) => d.type === selectedNode.type,
                    )!}
                    config={selectedNode.config}
                    onChange={(config) =>
                      replaceNode({ ...selectedNode, config })
                    }
                  />
                ) : null}
                <PolicyFields
                  key={selectedNode.id}
                  policy={selectedNode.policy ?? {}}
                  references={references}
                  nodes={spec.nodes}
                  onChange={(policy) =>
                    replaceNode({ ...selectedNode, policy })
                  }
                />
                <fieldset>
                  <legend>Position</legend>
                  {(["x", "y"] as const).map((axis) => (
                    <label className="field-group" key={axis}>
                      Position {axis}
                      <input
                        type="number"
                        min={-100000}
                        max={100000}
                        value={
                          nodePosition(
                            layout,
                            spec.nodes.indexOf(selectedNode),
                            selectedNode.id,
                          )[axis]
                        }
                        onChange={(e) =>
                          changeLayout({
                            ...layout,
                            nodes: {
                              ...layout.nodes,
                              [selectedNode.id]: {
                                ...nodePosition(
                                  layout,
                                  spec.nodes.indexOf(selectedNode),
                                  selectedNode.id,
                                ),
                                [axis]: Number(e.target.value),
                              },
                            },
                          })
                        }
                      />
                    </label>
                  ))}
                </fieldset>
                <button
                  className="button button-secondary"
                  onClick={() => remove([selectedNode.id], [])}
                >
                  Remove node
                </button>
              </fieldset>
            </>
          ) : selectedEdge ? (
            <>
              <p className="registry-key">{selectedEdge.id}</p>
              <fieldset disabled={readOnly}>
                <EdgeFields
                  edge={selectedEdge}
                  nodes={spec.nodes}
                  onChange={replaceEdge}
                />
                <button
                  className="button button-secondary"
                  onClick={() => remove([], [selectedEdge.id])}
                >
                  Disconnect edge
                </button>
              </fieldset>
            </>
          ) : (
            <p>
              Select a node or edge to inspect its configuration. Published
              versions preserve their exact specification and layout.
            </p>
          )}
        </aside>
      </div>
      {report ? (
        <section
          className={`content-card workflow-problems${report.valid ? " workflow-valid" : ""}`}
          aria-label="Workflow validation"
          role="status"
        >
          <h3>
            {report.valid
              ? "Workflow valid"
              : `${report.issues?.length ?? 0} validation problems`}
          </h3>
          {report.issues?.map((issue, index) => (
            <div className="workflow-problem" key={`${issue.code}-${index}`}>
              <button
                className="text-button"
                onClick={() => {
                  setDefaults(false);
                  setSelection(
                    issue.node_id
                      ? { kind: "node", id: issue.node_id }
                      : issue.edge_id
                        ? { kind: "edge", id: issue.edge_id }
                        : null,
                  );
                }}
              >
                {issue.message}
              </button>
              <p className="registry-key">
                {issue.code}
                {issue.path ? ` · ${issue.path}` : ""}
              </p>
            </div>
          ))}
        </section>
      ) : null}
      {document.version.published ? (
        <div className="content-card">
          <h3>Immutable publication</h3>
          <p className="registry-key">Version {document.version.id}</p>
          <p className="registry-key">
            Content SHA-256 {document.version.content_hash}
          </p>
          <p className="registry-key">
            Snapshot SHA-256 {document.version.snapshot_hash}
          </p>
        </div>
      ) : null}
    </section>
  );
}
