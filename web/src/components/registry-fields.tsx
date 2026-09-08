import { useState } from "react";
import type {
  RegistryWrite,
  RegistryRecord,
  RoutePolicySpec,
  RouteCandidate,
} from "@jarvis/contracts";
import type { RegistryKind } from "@/lib/api/registry";

type WithKind<T> = T extends { kind?: infer K }
  ? Omit<T, "kind"> & { kind: NonNullable<K> }
  : never;
export type Spec =
  | Exclude<WithKind<RegistryWrite["spec"]>, { kind: "route_policy" }>
  | (Omit<RoutePolicySpec, "kind" | "candidates"> & {
      kind: "route_policy";
      candidates: RouteCandidate[];
    });

function ListInput({
  id,
  value,
  onChange,
}: {
  id: string;
  value: unknown;
  onChange: (value: string) => void;
}) {
  const [text, setText] = useState(
    Array.isArray(value) ? value.join(", ") : "",
  );
  return (
    <input
      id={id}
      value={text}
      onChange={(event) => {
        setText(event.target.value);
        onChange(event.target.value);
      }}
    />
  );
}
export const registryTitles: Record<RegistryKind, string> = {
  worker: "Workers",
  provider_connection: "Providers",
  model_profile: "Models",
  route_policy: "Routing",
  retry_policy: "Retry policies",
  permission_policy: "Permission policies",
};
const timeout = {
  connect_seconds: 10,
  run_seconds: 300,
  heartbeat_seconds: 10,
};
export function defaultSpec(kind: RegistryKind): Spec {
  switch (kind) {
    case "worker":
      return {
        kind,
        adapter_kind: "demo",
        execution_host_label: "Local demo",
        capabilities: [],
        max_concurrency: 1,
        labels: {},
        timeouts: timeout,
        model_binding: { mode: "none", allowed_profile_revision_ids: [] },
        deployment_configured: false,
      };
    case "provider_connection":
      return {
        kind,
        provider_kind: "demo",
        base_url: null,
        locality: "local",
        egress: {
          allowed_data: ["public"],
          remote_allowed: false,
          paid: false,
        },
        timeouts: timeout,
        circuit: {
          failure_threshold: 3,
          cooldown_seconds: 30,
          failure_window_seconds: 60,
        },
      };
    case "model_profile":
      return {
        kind,
        provider_revision_id: "",
        model_identifier: "",
        purposes: ["utility"],
        capabilities: ["chat"],
        context_limit: 32000,
        output_limit: 4096,
        structured_json: false,
        tool_calls: false,
        streaming: false,
        locality: "local",
        parameters: {},
        usage_reporting: "none",
        pricing: { status: "unknown", currency: "USD", source: "Unspecified" },
      };
    case "route_policy":
      return {
        kind,
        candidates: [],
        required_capabilities: [],
        purposes: ["utility"],
        allowed_data: ["public"],
        allow_remote: false,
        allow_unknown_health: false,
        failover_classes: [],
        spend: {
          allow_paid: false,
          max_input_tokens: 32000,
          max_output_tokens: 4096,
          on_exceeded: "deny",
        },
      };
    case "retry_policy":
      return { kind, schema_version: "1.0", rules: [] };
    case "permission_policy":
      return {
        kind,
        allowed_capabilities: [],
        denied_capabilities: [],
        approval_required_actions: [],
        filesystem_scopes: [],
        shell: "deny",
        git: "deny",
        docker: "deny",
        browser: "deny",
        network: "deny",
        remote_provider: "deny",
        sensitive_action: "require_approval",
        destructive_action: "deny",
        unknown_action: "deny",
      };
  }
}
type Field = {
  path: string;
  label: string;
  type?: "number" | "check" | "list" | "json";
  options?: readonly string[];
  reference?: RegistryKind;
  min?: number;
  max?: number;
  required?: boolean;
};
const locality = ["local", "local_lan", "remote"];
const timeouts: Field[] = [
  {
    path: "timeouts.connect_seconds",
    label: "Connect timeout (seconds)",
    type: "number",
    min: 1,
    max: 120,
  },
  {
    path: "timeouts.run_seconds",
    label: "Run timeout (seconds)",
    type: "number",
    min: 1,
    max: 86400,
  },
  {
    path: "timeouts.heartbeat_seconds",
    label: "Heartbeat (seconds)",
    type: "number",
    min: 1,
    max: 300,
  },
];
const fields: Record<RegistryKind, Field[]> = {
  worker: [
    {
      path: "adapter_kind",
      label: "Adapter",
      options: ["demo", "openhands_ssh_v1"],
    },
    {
      path: "execution_host_label",
      label: "Execution host label",
      required: true,
    },
    {
      path: "capabilities",
      label: "Capabilities (comma separated)",
      type: "list",
    },
    {
      path: "max_concurrency",
      label: "Maximum concurrency",
      type: "number",
      min: 1,
      max: 128,
    },
    { path: "labels", label: "Labels (JSON object)", type: "json" },
    {
      path: "model_binding.mode",
      label: "Model binding",
      options: ["none", "control_plane", "worker_managed"],
    },
    ...timeouts,
  ],
  provider_connection: [
    {
      path: "provider_kind",
      label: "Provider type",
      options: ["demo", "openai", "ollama"],
    },
    { path: "base_url", label: "Endpoint" },
    { path: "locality", label: "Locality", options: locality },
    {
      path: "egress.allowed_data",
      label: "Allowed data (comma separated)",
      type: "list",
    },
    {
      path: "egress.remote_allowed",
      label: "Allow remote egress",
      type: "check",
    },
    { path: "egress.paid", label: "Paid provider", type: "check" },
    {
      path: "retry_policy_revision_id",
      label: "Retry policy revision",
      reference: "retry_policy",
    },
    ...timeouts,
    {
      path: "circuit.failure_threshold",
      label: "Circuit failure threshold",
      type: "number",
      min: 1,
      max: 100,
    },
    {
      path: "circuit.cooldown_seconds",
      label: "Circuit cooldown (seconds)",
      type: "number",
      min: 1,
      max: 3600,
    },
    {
      path: "circuit.failure_window_seconds",
      label: "Circuit failure window (seconds)",
      type: "number",
      min: 1,
      max: 3600,
    },
  ],
  model_profile: [
    {
      path: "provider_revision_id",
      label: "Provider revision",
      reference: "provider_connection",
      required: true,
    },
    { path: "model_identifier", label: "Model identifier", required: true },
    { path: "purposes", label: "Purposes (comma separated)", type: "list" },
    {
      path: "capabilities",
      label: "Capabilities (comma separated)",
      type: "list",
    },
    {
      path: "context_limit",
      label: "Context token limit",
      type: "number",
      min: 1,
      max: 10000000,
    },
    {
      path: "output_limit",
      label: "Output token limit",
      type: "number",
      min: 1,
      max: 1000000,
    },
    { path: "structured_json", label: "Structured JSON", type: "check" },
    { path: "tool_calls", label: "Tool calls", type: "check" },
    { path: "streaming", label: "Streaming", type: "check" },
    { path: "locality", label: "Locality", options: locality },
    {
      path: "parameters",
      label: "Model parameters (JSON object)",
      type: "json",
    },
    {
      path: "usage_reporting",
      label: "Usage reporting",
      options: ["exact", "partial", "none"],
    },
    {
      path: "pricing.status",
      label: "Pricing status",
      options: ["unknown", "known", "not_applicable"],
    },
    { path: "pricing.currency", label: "Currency" },
    {
      path: "pricing.input_per_million",
      label: "Input price per million",
      type: "number",
      min: 0,
    },
    {
      path: "pricing.cached_per_million",
      label: "Cached price per million",
      type: "number",
      min: 0,
    },
    {
      path: "pricing.output_per_million",
      label: "Output price per million",
      type: "number",
      min: 0,
    },
    { path: "pricing.source", label: "Pricing source" },
    {
      path: "pricing.effective_at",
      label: "Pricing effective date (ISO 8601)",
    },
  ],
  route_policy: [
    { path: "purposes", label: "Purposes (comma separated)", type: "list" },
    {
      path: "required_capabilities",
      label: "Required capabilities (comma separated)",
      type: "list",
    },
    {
      path: "allowed_data",
      label: "Allowed data (comma separated)",
      type: "list",
    },
    { path: "allow_remote", label: "Allow remote providers", type: "check" },
    {
      path: "allow_unknown_health",
      label: "Allow unknown health",
      type: "check",
    },
    {
      path: "failover_classes",
      label: "Failover failure classes (comma separated)",
      type: "list",
    },
    { path: "spend.allow_paid", label: "Allow paid providers", type: "check" },
    {
      path: "spend.max_input_tokens",
      label: "Per-call input ceiling",
      type: "number",
      min: 1,
      max: 10000000,
    },
    {
      path: "spend.max_output_tokens",
      label: "Per-call output ceiling",
      type: "number",
      min: 1,
      max: 1000000,
    },
    {
      path: "spend.max_call_cost",
      label: "Per-call cost ceiling",
      type: "number",
      min: 0,
    },
    {
      path: "spend.max_run_cost",
      label: "Run cost ceiling",
      type: "number",
      min: 0,
    },
    {
      path: "spend.on_exceeded",
      label: "When spend is exceeded",
      options: ["deny", "require_approval"],
    },
  ],
  retry_policy: [],
  permission_policy: [
    {
      path: "allowed_capabilities",
      label: "Allowed capabilities (comma separated)",
      type: "list",
    },
    {
      path: "denied_capabilities",
      label: "Denied capabilities (comma separated)",
      type: "list",
    },
    {
      path: "approval_required_actions",
      label: "Approval-required actions (comma separated)",
      type: "list",
    },
    {
      path: "filesystem_scopes",
      label: "Filesystem scopes (comma separated)",
      type: "list",
    },
    ...[
      "shell",
      "git",
      "docker",
      "browser",
      "network",
      "remote_provider",
      "sensitive_action",
      "destructive_action",
      "unknown_action",
    ].map((path) => ({
      path,
      label: path.replaceAll("_", " "),
      options: [
        "deny",
        "require_approval",
        ...([
          "sensitive_action",
          "destructive_action",
          "unknown_action",
        ].includes(path)
          ? []
          : ["allow"]),
      ],
    })),
  ],
};
function getValue(object: unknown, path: string): unknown {
  return path
    .split(".")
    .reduce<unknown>(
      (value, key) =>
        value && typeof value === "object"
          ? (value as Record<string, unknown>)[key]
          : undefined,
      object,
    );
}
function setValue(spec: Spec, path: string, value: unknown): Spec {
  const next = structuredClone(spec);
  const keys = path.split(".");
  let cursor = next as unknown as Record<string, unknown>;
  for (const key of keys.slice(0, -1))
    cursor = cursor[key] as Record<string, unknown>;
  cursor[keys.at(-1)!] = value;
  return next;
}
export function RegistryFields({
  spec,
  onChange,
  references,
}: {
  spec: Spec;
  onChange: (spec: Spec) => void;
  references: RegistryRecord[];
}) {
  const profiles = references.filter((r) => r.spec.kind === "model_profile");
  return (
    <>
      <div className="registry-form-grid">
        {fields[spec.kind].map((field) => {
          const value = getValue(spec, field.path);
          const id = `spec-${field.path}`;
          const change = (raw: string) =>
            onChange(
              setValue(
                spec,
                field.path,
                field.type === "number"
                  ? raw === ""
                    ? null
                    : Number(raw)
                  : field.type === "list"
                    ? raw
                        .split(",")
                        .map((x) => x.trim())
                        .filter(Boolean)
                    : raw || null,
              ),
            );
          if (field.type === "check")
            return (
              <label className="check-field" key={id}>
                <input
                  type="checkbox"
                  checked={Boolean(value)}
                  onChange={(event) =>
                    onChange(setValue(spec, field.path, event.target.checked))
                  }
                />
                {field.label}
              </label>
            );
          return (
            <div className="field-group" key={id}>
              <label htmlFor={id}>{field.label}</label>
              {field.options || field.reference ? (
                <select
                  id={id}
                  value={String(value ?? "")}
                  required={field.required}
                  onChange={(event) => change(event.target.value)}
                >
                  {field.reference ? (
                    <>
                      <option value="">Select a revision</option>
                      {references
                        .filter((r) => r.spec.kind === field.reference)
                        .map((r) => (
                          <option key={r.revision_id} value={r.revision_id}>
                            {r.display_name} · revision {r.revision}
                            {r.archived
                              ? " · archived"
                              : !r.enabled
                                ? " · disabled"
                                : ""}
                          </option>
                        ))}
                      {value &&
                      !references.some((r) => r.revision_id === value) ? (
                        <option value={String(value)}>
                          Pinned revision {String(value)}
                        </option>
                      ) : null}
                    </>
                  ) : (
                    field.options?.map((option) => (
                      <option key={option} value={option}>
                        {option}
                      </option>
                    ))
                  )}
                </select>
              ) : field.type === "json" ? (
                <textarea
                  id={id}
                  defaultValue={JSON.stringify(value, null, 2)}
                  rows={3}
                  onChange={(event) => {
                    try {
                      const parsed: unknown = JSON.parse(event.target.value);
                      if (
                        !parsed ||
                        Array.isArray(parsed) ||
                        typeof parsed !== "object"
                      )
                        throw new Error();
                      onChange(setValue(spec, field.path, parsed));
                      event.target.setCustomValidity("");
                    } catch {
                      event.target.setCustomValidity("Enter a JSON object.");
                    }
                  }}
                />
              ) : field.type === "list" ? (
                <ListInput id={id} value={value} onChange={change} />
              ) : (
                <input
                  id={id}
                  type={field.type === "number" ? "number" : "text"}
                  min={field.min}
                  max={field.max}
                  step={field.type === "number" ? "any" : undefined}
                  required={field.required}
                  value={
                    Array.isArray(value)
                      ? value.join(", ")
                      : String(value ?? "")
                  }
                  onChange={(event) => change(event.target.value)}
                />
              )}
            </div>
          );
        })}
      </div>
      {spec.kind === "worker" ? (
        <fieldset>
          <legend>Allowed model profile revisions</legend>
          {profiles.length ? (
            profiles.map((profile) => (
              <label className="check-field" key={profile.revision_id}>
                <input
                  type="checkbox"
                  checked={
                    spec.model_binding?.allowed_profile_revision_ids?.includes(
                      profile.revision_id,
                    ) ?? false
                  }
                  onChange={(event) =>
                    onChange({
                      ...spec,
                      model_binding: {
                        ...spec.model_binding,
                        allowed_profile_revision_ids: event.target.checked
                          ? [
                              ...(spec.model_binding
                                ?.allowed_profile_revision_ids ?? []),
                              profile.revision_id,
                            ]
                          : spec.model_binding?.allowed_profile_revision_ids?.filter(
                              (id) => id !== profile.revision_id,
                            ),
                      },
                    })
                  }
                />
                {profile.display_name} · revision {profile.revision}
              </label>
            ))
          ) : (
            <p>Create a model profile to configure a model binding.</p>
          )}
          {spec.model_binding?.allowed_profile_revision_ids
            ?.filter(
              (id) => !profiles.some((profile) => profile.revision_id === id),
            )
            .map((id) => (
              <label className="check-field" key={id}>
                <input
                  type="checkbox"
                  checked
                  onChange={() =>
                    onChange({
                      ...spec,
                      model_binding: {
                        ...spec.model_binding,
                        allowed_profile_revision_ids:
                          spec.model_binding?.allowed_profile_revision_ids?.filter(
                            (candidate) => candidate !== id,
                          ),
                      },
                    })
                  }
                />
                Pinned model revision {id}
              </label>
            ))}
          <p>
            OpenHands SSH requires one worker-managed profile and concurrency
            one.
          </p>
        </fieldset>
      ) : null}
      {spec.kind === "route_policy" ? (
        <fieldset>
          <legend>Ordered candidates</legend>
          <p>
            Lower priority numbers are preferred. Equal priorities use the
            server’s stable revision-ID tie breaker.
          </p>
          {spec.candidates.map((candidate, index) => (
            <div className="candidate-row" key={candidate.profile_revision_id}>
              <span>
                {profiles.find(
                  (p) => p.revision_id === candidate.profile_revision_id,
                )?.display_name ?? candidate.profile_revision_id}
              </span>
              <label>
                Priority {index + 1}
                <input
                  type="number"
                  min={0}
                  max={10000}
                  value={candidate.priority ?? 0}
                  onChange={(event) =>
                    onChange({
                      ...spec,
                      candidates: spec.candidates.map((item, i) =>
                        i === index
                          ? { ...item, priority: Number(event.target.value) }
                          : item,
                      ),
                    })
                  }
                />
              </label>
              <button
                className="text-button"
                type="button"
                aria-label={`Remove candidate ${index + 1}`}
                onClick={() =>
                  onChange({
                    ...spec,
                    candidates: spec.candidates.filter((_, i) => i !== index),
                  })
                }
              >
                Remove
              </button>
            </div>
          ))}
          <label className="field-group">
            Add candidate
            <select
              value=""
              onChange={(event) => {
                if (event.target.value)
                  onChange({
                    ...spec,
                    candidates: [
                      ...spec.candidates,
                      {
                        profile_revision_id: event.target.value,
                        priority: spec.candidates.length * 10,
                      },
                    ],
                  });
              }}
            >
              <option value="">Select a model profile revision</option>
              {profiles
                .filter(
                  (p) =>
                    !spec.candidates.some(
                      (c) => c.profile_revision_id === p.revision_id,
                    ),
                )
                .map((p) => (
                  <option key={p.revision_id} value={p.revision_id}>
                    {p.display_name} · revision {p.revision}
                  </option>
                ))}
            </select>
          </label>
        </fieldset>
      ) : null}
      {spec.kind === "retry_policy" ? (
        <fieldset>
          <legend>Independent failure budgets</legend>
          <p>
            Each failure class has its own retry budget. Provider failures do
            not consume code attempts.
          </p>
          {spec.rules.map((rule, index) => (
            <div className="retry-rule" key={index}>
              <div className="registry-form-grid">
                <label className="field-group">
                  Failure class
                  <input
                    required
                    value={rule.failure_class}
                    onChange={(event) =>
                      onChange({
                        ...spec,
                        rules: spec.rules.map((r, i) =>
                          i === index
                            ? {
                                ...r,
                                failure_class: event.target
                                  .value as typeof rule.failure_class,
                              }
                            : r,
                        ),
                      })
                    }
                  />
                </label>
                {(
                  [
                    "max_retries",
                    "initial_delay_ms",
                    "max_delay_ms",
                    "multiplier",
                  ] as const
                ).map((key) => (
                  <label className="field-group" key={key}>
                    {key.replaceAll("_", " ")}
                    <input
                      type="number"
                      min={key === "multiplier" ? 1 : 0}
                      max={
                        key === "max_retries" || key === "multiplier"
                          ? 100
                          : 86400000
                      }
                      value={rule[key] ?? 0}
                      onChange={(event) =>
                        onChange({
                          ...spec,
                          rules: spec.rules.map((r, i) =>
                            i === index
                              ? { ...r, [key]: Number(event.target.value) }
                              : r,
                          ),
                        })
                      }
                    />
                  </label>
                ))}
                <label className="field-group">
                  Exhaustion action
                  <select
                    value={rule.exhaustion_action}
                    onChange={(event) =>
                      onChange({
                        ...spec,
                        rules: spec.rules.map((r, i) =>
                          i === index
                            ? {
                                ...r,
                                exhaustion_action: event.target
                                  .value as typeof rule.exhaustion_action,
                              }
                            : r,
                        ),
                      })
                    }
                  >
                    {["fail", "block", "approval"].map((x) => (
                      <option key={x}>{x}</option>
                    ))}
                  </select>
                </label>
                <label className="field-group">
                  Jitter
                  <select
                    value={rule.jitter}
                    onChange={(event) =>
                      onChange({
                        ...spec,
                        rules: spec.rules.map((r, i) =>
                          i === index
                            ? {
                                ...r,
                                jitter: event.target
                                  .value as typeof rule.jitter,
                              }
                            : r,
                        ),
                      })
                    }
                  >
                    <option>none</option>
                    <option>deterministic</option>
                  </select>
                </label>
                <label className="check-field">
                  <input
                    type="checkbox"
                    checked={rule.allow_failover ?? false}
                    onChange={(event) =>
                      onChange({
                        ...spec,
                        rules: spec.rules.map((r, i) =>
                          i === index
                            ? { ...r, allow_failover: event.target.checked }
                            : r,
                        ),
                      })
                    }
                  />
                  Allow failover
                </label>
              </div>
              <button
                type="button"
                className="text-button"
                onClick={() =>
                  onChange({
                    ...spec,
                    rules: spec.rules.filter((_, i) => i !== index),
                  })
                }
              >
                Remove rule {index + 1}
              </button>
            </div>
          ))}
          <button
            type="button"
            className="button button-secondary"
            onClick={() =>
              onChange({
                ...spec,
                rules: [
                  ...spec.rules,
                  {
                    failure_class: "provider.transient",
                    max_retries: 2,
                    initial_delay_ms: 1000,
                    max_delay_ms: 60000,
                    multiplier: 2,
                    jitter: "none",
                    exhaustion_action: "fail",
                    allow_failover: false,
                  },
                ],
              })
            }
          >
            Add retry rule
          </button>
        </fieldset>
      ) : null}
    </>
  );
}
