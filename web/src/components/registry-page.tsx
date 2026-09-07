"use client";

import {
  useInfiniteQuery,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import type {
  RegistryRecord,
  RegistryWrite,
  RouteResolution,
  ValidationReport,
} from "@jarvis/contracts";
import { useMemo, useRef, useState, type FormEvent } from "react";
import {
  createRegistryClient,
  type RegistryClient,
  type RegistryKind,
} from "@/lib/api/registry";
import { useSession } from "@/lib/session";
import {
  RegistryFields,
  defaultSpec,
  registryTitles,
  type Spec,
} from "./registry-fields";

function message(error: unknown) {
  return error instanceof Error
    ? error.message
    : "The request failed. Please try again.";
}

export function RegistryPage({
  kind,
  client: injectedClient,
}: {
  kind: RegistryKind;
  client?: RegistryClient;
}) {
  const session = useSession();
  const client = useMemo(
    () => injectedClient ?? createRegistryClient(session.data?.csrf_token),
    [injectedClient, session.data?.csrf_token],
  );
  const cache = useQueryClient();
  const [editor, setEditor] = useState<RegistryRecord | "new" | null>(null);
  const [history, setHistory] = useState<RegistryRecord | null>(null);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [validation, setValidation] = useState<{
    name: string;
    report: ValidationReport;
  } | null>(null);
  const createButton = useRef<HTMLButtonElement>(null);
  const records = useInfiniteQuery({
    queryKey: ["registry", kind],
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) => client.list(kind, pageParam),
    getNextPageParam: (page) => page.next_after ?? undefined,
    enabled: Boolean(session.data || injectedClient),
  });
  const revisions = useInfiniteQuery({
    queryKey: ["registry-history", kind, history?.id],
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) => client.revisions(kind, history!.id, pageParam),
    getNextPageParam: (page) => page.next_after ?? undefined,
    enabled: Boolean(history),
  });
  const items = records.data?.pages.flatMap((page) => page.items) ?? [];
  function closeEditor() {
    setEditor(null);
    createButton.current?.focus();
  }
  async function validate(record: RegistryRecord) {
    setBusy(true);
    setError("");
    try {
      setValidation({
        name: record.display_name,
        report: await client.validate(kind, record.id),
      });
    } catch (error) {
      setError(message(error));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="page-stack registry-page">
      <header className="page-header">
        <p className="eyebrow">Versioned configuration</p>
        <h1>{registryTitles[kind]}</h1>
        <p>
          Configure, validate, and inspect immutable revisions. Health reflects
          recorded server state; validation does not make a live connection.
        </p>
      </header>
      <div className="registry-toolbar">
        <button
          ref={createButton}
          className="button button-primary"
          type="button"
          onClick={() => {
            setEditor("new");
            setNotice("");
          }}
        >
          Create {kind.replaceAll("_", " ")}
        </button>
        <button
          className="button button-secondary"
          type="button"
          disabled={records.isFetching}
          onClick={() => void records.refetch()}
        >
          Refresh
        </button>
        <span>{items.length} loaded</span>
      </div>
      {notice ? (
        <p className="registry-notice" role="status">
          {notice}
        </p>
      ) : null}
      {records.isPending ? <p role="status">Loading configuration…</p> : null}
      {error || records.error ? (
        <p className="inline-alert" role="alert">
          {error || message(records.error)}
        </p>
      ) : null}
      {validation ? (
        <section
          className="content-card"
          aria-label="Validation result"
          role="status"
        >
          <h2>
            {validation.name}:{" "}
            {validation.report.valid
              ? "Configuration valid"
              : "Configuration needs attention"}
          </h2>
          <p>
            Health: {validation.report.health}.{" "}
            {validation.report.network_checked
              ? "Connection checked."
              : "No live network probe performed."}
            {validation.report.demo ? " DEMO." : ""}
          </p>
          <ul>
            {validation.report.issues?.map((issue, index) => (
              <li key={index}>{issue}</li>
            ))}
          </ul>
        </section>
      ) : null}
      {editor ? (
        <RegistryEditor
          key={editor === "new" ? "new" : `${editor.id}-${editor.version}`}
          kind={kind}
          record={editor === "new" ? undefined : editor}
          client={client}
          onCancel={closeEditor}
          onSaved={async (record) => {
            setEditor(null);
            setNotice(
              `Saved ${record.display_name}, revision ${record.revision}.`,
            );
            await cache.invalidateQueries({ queryKey: ["registry"] });
            await cache.invalidateQueries({ queryKey: ["registry-history"] });
            createButton.current?.focus();
          }}
        />
      ) : null}
      <section
        className="registry-cards"
        aria-label={`${registryTitles[kind]} registry`}
      >
        {!records.isPending && !items.length && !records.error ? (
          <div className="content-card">
            <h2>No configurations yet</h2>
            <p>
              Create the first {kind.replaceAll("_", " ")} to begin. All changes
              are stored by the server.
            </p>
          </div>
        ) : null}
        {items.map((record) => (
          <article className="content-card registry-record" key={record.id}>
            <div className="section-heading">
              <div>
                <h2>{record.display_name}</h2>
                <p className="registry-key">
                  {record.key} · revision {record.revision}
                </p>
              </div>
              <span className="status-label">
                {record.archived
                  ? "Archived"
                  : record.enabled
                    ? "Enabled"
                    : "Disabled"}
              </span>
            </div>
            {record.description ? <p>{record.description}</p> : null}
            <RecordDetails record={record} />
            <div className="registry-actions">
              <button
                className="button button-secondary"
                type="button"
                onClick={() => {
                  setEditor(record);
                  setNotice("");
                }}
              >
                Edit {record.display_name}
              </button>
              <button
                className="text-button"
                type="button"
                disabled={busy}
                onClick={() => void validate(record)}
              >
                Validate {record.display_name}
              </button>
              <button
                className="text-button"
                type="button"
                onClick={() => setHistory(record)}
              >
                History {record.display_name}
              </button>
            </div>
            {kind === "route_policy" ? (
              <RoutePreview record={record} client={client} />
            ) : null}
          </article>
        ))}
      </section>
      {records.hasNextPage ? (
        <button
          className="button button-secondary"
          type="button"
          disabled={records.isFetchingNextPage}
          onClick={() => void records.fetchNextPage()}
        >
          Load more
        </button>
      ) : null}
      {history ? (
        <section className="content-card" aria-label="Revision history">
          <div className="section-heading">
            <h2>History: {history.display_name}</h2>
            <button
              className="text-button"
              type="button"
              onClick={() => setHistory(null)}
            >
              Close history
            </button>
          </div>
          {revisions.isPending ? (
            <p role="status">Loading revisions…</p>
          ) : revisions.error ? (
            <p role="alert">{message(revisions.error)}</p>
          ) : (
            revisions.data?.pages
              .flatMap((page) => page.items)
              .map((record) => (
                <details key={record.revision_id}>
                  <summary>
                    Revision {record.revision} · {record.display_name} ·{" "}
                    {record.enabled ? "Enabled" : "Disabled"}
                    {record.archived ? " · Archived" : ""}
                  </summary>
                  <p>{record.description}</p>
                  <RecordDetails record={record} />
                  <p className="registry-key">
                    Revision ID: {record.revision_id}
                    <br />
                    Content hash: {record.content_hash}
                    <br />
                    Created: {record.created_at}
                  </p>
                  <pre className="registry-json">
                    {JSON.stringify(record.spec, null, 2)}
                  </pre>
                </details>
              ))
          )}
          {revisions.hasNextPage ? (
            <button
              className="button button-secondary"
              type="button"
              disabled={revisions.isFetchingNextPage}
              onClick={() => void revisions.fetchNextPage()}
            >
              Load more revisions
            </button>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}

function RecordDetails({ record }: { record: RegistryRecord }) {
  const spec = record.spec;
  return (
    <>
      <dl className="registry-facts">
        <div>
          <dt>Health</dt>
          <dd>{record.health ?? "unknown"}</dd>
        </div>
        <div>
          <dt>Updated</dt>
          <dd>{new Date(record.updated_at).toLocaleString()}</dd>
        </div>
        {spec.kind === "worker" ? (
          <>
            <div>
              <dt>Adapter</dt>
              <dd>
                {spec.adapter_kind === "demo"
                  ? "DEMO"
                  : "Legacy SSH (configuration only)"}
              </dd>
            </div>
            <div>
              <dt>Concurrency</dt>
              <dd>{spec.max_concurrency}</dd>
            </div>
            <div>
              <dt>Model binding</dt>
              <dd>{spec.model_binding?.mode}</dd>
            </div>
            <div>
              <dt>Deployment</dt>
              <dd>
                {spec.deployment_configured ? "Configured" : "Not configured"}
              </dd>
            </div>
          </>
        ) : null}
        {spec.kind === "provider_connection" ? (
          <>
            <div>
              <dt>Provider</dt>
              <dd>{spec.provider_kind.toUpperCase()}</dd>
            </div>
            <div>
              <dt>Secret</dt>
              <dd>
                {record.secret_status === "configured"
                  ? "Configured · masked"
                  : record.secret_status === "missing"
                    ? "Not configured"
                    : "Not required"}
              </dd>
            </div>
            <div>
              <dt>Endpoint</dt>
              <dd>{spec.base_url ?? "No network · DEMO"}</dd>
            </div>
            <div>
              <dt>Circuit</dt>
              <dd>{record.circuit_state ?? "unknown"}</dd>
            </div>
          </>
        ) : null}
        {spec.kind === "model_profile" ? (
          <>
            <div>
              <dt>Model</dt>
              <dd>{spec.model_identifier}</dd>
            </div>
            <div>
              <dt>Provider revision</dt>
              <dd>{spec.provider_revision_id}</dd>
            </div>
            <div>
              <dt>Context / output</dt>
              <dd>
                {spec.context_limit.toLocaleString()} /{" "}
                {spec.output_limit.toLocaleString()}
              </dd>
            </div>
            <div>
              <dt>Locality</dt>
              <dd>{spec.locality}</dd>
            </div>
            <div>
              <dt>Usage</dt>
              <dd>{spec.usage_reporting}</dd>
            </div>
            <div>
              <dt>Pricing per million tokens</dt>
              <dd>
                {spec.pricing?.status === "known"
                  ? `${spec.pricing.currency} ${spec.pricing.input_per_million} input / ${spec.pricing.output_per_million} output`
                  : spec.pricing?.status === "not_applicable"
                    ? "Not applicable"
                    : "Unknown"}
              </dd>
            </div>
          </>
        ) : null}
        {spec.kind === "route_policy" ? (
          <>
            <div>
              <dt>Candidates</dt>
              <dd>{spec.candidates.length}</dd>
            </div>
            <div>
              <dt>Paid use</dt>
              <dd>
                {spec.spend?.allow_paid ? "Allowed within limits" : "Denied"}
              </dd>
            </div>
          </>
        ) : null}
        {spec.kind === "retry_policy" ? (
          <div>
            <dt>Independent rules</dt>
            <dd>{spec.rules.length}</dd>
          </div>
        ) : null}
        {spec.kind === "permission_policy" ? (
          <>
            <div>
              <dt>Unknown actions</dt>
              <dd>{spec.unknown_action}</dd>
            </div>
            <div>
              <dt>Destructive actions</dt>
              <dd>{spec.destructive_action}</dd>
            </div>
          </>
        ) : null}
      </dl>
      {"capabilities" in spec ? (
        <div className="capability-list" aria-label="Capabilities">
          {spec.capabilities?.length ? (
            spec.capabilities.map((capability) => (
              <span className="status-label" key={capability}>
                {capability}
              </span>
            ))
          ) : (
            <span>No capabilities declared</span>
          )}
        </div>
      ) : null}
      {spec.kind === "route_policy" ? (
        <div className="capability-list" aria-label="Required capabilities">
          {spec.required_capabilities?.map((capability) => (
            <span className="status-label" key={capability}>
              {capability}
            </span>
          ))}
        </div>
      ) : null}
    </>
  );
}

export function RegistryEditor({
  kind,
  record,
  client,
  onCancel,
  onSaved,
}: {
  kind: RegistryKind;
  record?: RegistryRecord;
  client: RegistryClient;
  onCancel: () => void;
  onSaved: (record: RegistryRecord) => void | Promise<void>;
}) {
  const [spec, setSpec] = useState<Spec>(
    record ? ({ ...record.spec, kind } as Spec) : defaultSpec(kind),
  );
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const secretRef = useRef<HTMLInputElement>(null);
  const deploymentRef = useRef<HTMLInputElement>(null);
  const references = useQuery({
    queryKey: ["registry", "references"],
    queryFn: async () => {
      const result: RegistryRecord[] = [];
      for (const referenceKind of [
        "provider_connection",
        "model_profile",
        "retry_policy",
      ] as const) {
        let after: string | undefined;
        do {
          const page = await client.list(referenceKind, after);
          result.push(...page.items);
          after = page.next_after ?? undefined;
        } while (after);
      }
      return result;
    },
  });
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    if (spec.kind === "route_policy" && !spec.candidates.length) {
      setError("Add at least one candidate profile.");
      return;
    }
    if (
      spec.kind === "model_profile" &&
      spec.output_limit > spec.context_limit
    ) {
      setError("Output token limit must not exceed the context token limit.");
      return;
    }
    if (
      spec.kind === "worker" &&
      spec.adapter_kind === "openhands_ssh_v1" &&
      (spec.max_concurrency !== 1 ||
        spec.model_binding?.mode !== "worker_managed" ||
        spec.model_binding.allowed_profile_revision_ids?.length !== 1)
    ) {
      setError(
        "Legacy SSH requires concurrency one and exactly one worker-managed profile.",
      );
      return;
    }
    const values = new FormData(event.currentTarget);
    const write: RegistryWrite = {
      key: String(values.get("key")),
      display_name: String(values.get("display_name")),
      description: String(values.get("description")),
      enabled: values.has("enabled"),
      archived: values.has("archived"),
      expected_version: record?.version ?? 0,
      idempotency_key: crypto.randomUUID(),
      spec: spec as RegistryWrite["spec"],
      clear_secret: values.has("clear_secret"),
    };
    if (secretRef.current?.value) write.secret_ref = secretRef.current.value;
    if (deploymentRef.current?.value)
      write.deployment_ref = deploymentRef.current.value;
    // References are write-only and cleared even when the server rejects a save.
    if (secretRef.current) secretRef.current.value = "";
    if (deploymentRef.current) deploymentRef.current.value = "";
    setSaving(true);
    try {
      await onSaved(await client.save(kind, write, record?.id));
    } catch (error) {
      setError(message(error));
    } finally {
      setSaving(false);
    }
  }
  return (
    <section
      className="content-card registry-editor"
      aria-label="Configuration editor"
    >
      <h2>
        {record
          ? `Edit ${record.display_name}`
          : `New ${kind.replaceAll("_", " ")}`}
      </h2>
      <p>
        {record
          ? `Saving creates revision ${record.revision + 1}. Existing references keep their pinned revision.`
          : "Create a persistent, versioned configuration."}
      </p>
      <form onSubmit={(event) => void save(event)}>
        <fieldset disabled={saving}>
          <legend className="sr-only">Configuration fields</legend>
          <div className="registry-form-grid">
            <label className="field-group">
              Stable key
              <input
                name="key"
                pattern="[a-z]([a-z0-9_]|-)*"
                maxLength={120}
                required
                defaultValue={record?.key}
                readOnly={Boolean(record)}
                autoFocus
              />
            </label>
            <label className="field-group">
              Display name
              <input
                name="display_name"
                maxLength={160}
                required
                defaultValue={record?.display_name}
              />
            </label>
            <label className="field-group">
              Description
              <textarea
                name="description"
                maxLength={2000}
                defaultValue={record?.description}
              />
            </label>
            <div>
              <label className="check-field">
                <input
                  type="checkbox"
                  name="enabled"
                  defaultChecked={record?.enabled ?? true}
                />
                Enabled
              </label>
              <label className="check-field">
                <input
                  type="checkbox"
                  name="archived"
                  defaultChecked={record?.archived ?? false}
                />
                Archived
              </label>
            </div>
          </div>
          {references.error ? (
            <p role="alert">
              Reference choices could not load. {message(references.error)}
            </p>
          ) : null}
          <RegistryFields
            spec={spec}
            onChange={setSpec}
            references={references.data ?? []}
          />
          {kind === "provider_connection" || kind === "worker" ? (
            <fieldset>
              <legend>Server-managed references</legend>
              <p>
                Enter an opaque reference only, such as secret:provider-name.
                Raw credentials and filesystem contents are never accepted.
                Leave blank to retain the current reference.
              </p>
              {kind === "provider_connection" ? (
                <>
                  <label className="field-group">
                    Replace secret reference
                    <input
                      ref={secretRef}
                      type="password"
                      autoComplete="new-password"
                      maxLength={220}
                      pattern="(secret:(?:[a-zA-Z0-9_]|-){1,100}|file:(?:[a-zA-Z0-9_]|-)+\.env#[A-Z][A-Z0-9_]{0,99})"
                    />
                  </label>
                  <p>
                    Secret status: {record?.secret_status ?? "Not configured"}
                  </p>
                  <label className="check-field">
                    <input type="checkbox" name="clear_secret" />
                    Clear stored secret reference
                  </label>
                </>
              ) : (
                <label className="field-group">
                  Deployment reference
                  <input
                    ref={deploymentRef}
                    type="password"
                    autoComplete="new-password"
                    maxLength={220}
                    pattern="(secret:(?:[a-zA-Z0-9_]|-){1,100}|file:(?:[a-zA-Z0-9_]|-)+\.env#[A-Z][A-Z0-9_]{0,99})"
                  />
                </label>
              )}
            </fieldset>
          ) : null}
          {error ? (
            <p className="form-error" role="alert">
              {error}
            </p>
          ) : null}
          <div className="registry-actions">
            <button className="button button-primary" type="submit">
              {saving ? "Saving…" : "Save revision"}
            </button>
            <button
              className="button button-secondary"
              type="button"
              onClick={onCancel}
            >
              Cancel
            </button>
          </div>
        </fieldset>
      </form>
    </section>
  );
}

function RoutePreview({
  record,
  client,
}: {
  record: RegistryRecord;
  client: RegistryClient;
}) {
  const [result, setResult] = useState<RouteResolution | null>(null);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  async function preview(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    setPending(true);
    setError("");
    setResult(null);
    try {
      setResult(
        await client.preview({
          route_revision_id: record.revision_id,
          requirements: {
            purpose: String(values.get("purpose")),
            capabilities: String(values.get("capabilities"))
              .split(",")
              .map((v) => v.trim())
              .filter(Boolean),
            input_tokens: Number(values.get("input")),
            output_tokens: Number(values.get("output")),
            data_classification: String(values.get("data")) as
              "public" | "internal" | "confidential" | "restricted",
            run_spend: values.get("spend") ? String(values.get("spend")) : null,
          },
        }),
      );
    } catch (error) {
      setError(message(error));
    } finally {
      setPending(false);
    }
  }
  return (
    <details>
      <summary>Deterministic resolution preview</summary>
      <p>
        Evaluate this exact revision on the server. No model invocation or
        approval execution occurs.
      </p>
      <form onSubmit={(event) => void preview(event)}>
        <fieldset disabled={pending}>
          <legend className="sr-only">Preview requirements</legend>
          <div className="registry-form-grid">
            <label className="field-group">
              Task purpose
              <input name="purpose" required defaultValue="utility" />
            </label>
            <label className="field-group">
              Required capabilities
              <input name="capabilities" defaultValue="chat" />
            </label>
            <label className="field-group">
              Input tokens
              <input
                name="input"
                type="number"
                min={0}
                max={10000000}
                defaultValue={100}
                required
              />
            </label>
            <label className="field-group">
              Output tokens
              <input
                name="output"
                type="number"
                min={1}
                max={1000000}
                defaultValue={100}
                required
              />
            </label>
            <label className="field-group">
              Data classification
              <select name="data">
                {["public", "internal", "confidential", "restricted"].map(
                  (value) => (
                    <option key={value}>{value}</option>
                  ),
                )}
              </select>
            </label>
            <label className="field-group">
              Existing run spend
              <input name="spend" type="number" min={0} step="any" />
            </label>
          </div>
          <button className="button button-secondary" type="submit">
            {pending ? "Resolving…" : "Resolve route"}
          </button>
        </fieldset>
      </form>
      {error ? (
        <p className="form-error" role="alert">
          {error}
        </p>
      ) : null}
      {result ? (
        <div role="status">
          <h3>
            {result.demo ? "DEMO · " : ""}Decision: {result.decision}
          </h3>
          <p>
            Selected profile: {result.selected_profile_revision_id ?? "None"}
          </p>
          <ul>
            {result.reasons?.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
          <ol>
            {result.candidates?.map((candidate) => (
              <li key={candidate.profile_revision_id}>
                {candidate.profile_revision_id}:{" "}
                {candidate.eligible ? "Eligible" : "Ineligible"}
                {candidate.reasons?.length
                  ? ` — ${candidate.reasons.join("; ")}`
                  : ""}
              </li>
            ))}
          </ol>
          <p className="registry-key">Snapshot: {result.snapshot_hash}</p>
        </div>
      ) : null}
    </details>
  );
}
