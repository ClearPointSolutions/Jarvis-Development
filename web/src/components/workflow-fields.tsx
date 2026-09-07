import { useState } from "react";
import type {
  NodePolicy,
  NodeTypeDefinition,
  Predicate,
  PredicateOperator,
  RegistryRecord,
  WorkflowEdge,
  WorkflowNode,
  WorkflowSpec,
} from "@jarvis/contracts";
import type { RegistryKind } from "@/lib/api/registry";

export const humanize = (value: string) =>
  value.replaceAll("_", " ").replace(/^./, (c) => c.toUpperCase());

function ListField({
  value,
  onChange,
  label,
}: {
  value: string[];
  onChange: (value: string[]) => void;
  label: string;
}) {
  const [text, setText] = useState(value.join(", "));
  return (
    <label className="field-group">
      {label}
      <input
        value={text}
        onChange={(event) => {
          setText(event.target.value);
          onChange(
            event.target.value
              .split(",")
              .map((x) => x.trim())
              .filter(Boolean),
          );
        }}
      />
    </label>
  );
}

export function RevisionField({
  label,
  kind,
  value,
  references,
  onChange,
}: {
  label: string;
  kind: RegistryKind;
  value?: string | null;
  references: RegistryRecord[];
  onChange: (value: string | null) => void;
}) {
  const choices = references.filter((r) => r.spec.kind === kind);
  return (
    <label className="field-group">
      {label}
      <select
        value={value ?? ""}
        onChange={(event) => onChange(event.target.value || null)}
      >
        <option value="">Inherit / unassigned</option>
        {value && !choices.some((r) => r.revision_id === value) ? (
          <option value={value}>Pinned revision {value}</option>
        ) : null}
        {choices.map((r) => (
          <option key={r.revision_id} value={r.revision_id}>
            {r.display_name} · revision {r.revision}
            {r.archived ? " · archived" : !r.enabled ? " · disabled" : ""}
          </option>
        ))}
      </select>
    </label>
  );
}

/** Render the server's code-reviewed JSON Schema as data-only controls. */
export function ConfigFields({
  definition,
  config,
  onChange,
}: {
  definition: NodeTypeDefinition;
  config: WorkflowNode["config"];
  onChange: (value: WorkflowNode["config"]) => void;
}) {
  const properties = definition.config_schema.properties as
    Record<string, Record<string, unknown>> | undefined;
  return (
    <fieldset>
      <legend>Node configuration</legend>
      {Object.entries(properties ?? {}).map(([key, original]) => {
        const schema = Array.isArray(original.anyOf)
          ? {
              ...original,
              ...(original.anyOf as Record<string, unknown>[]).find(
                (s) => s.type !== "null",
              ),
            }
          : original;
        const value = Object.prototype.hasOwnProperty.call(config, key)
          ? config[key]
          : schema.default;
        const change = (v: unknown) => onChange({ ...config, [key]: v });
        const label = humanize(key);
        if (schema.const !== undefined)
          return (
            <div className="workflow-fixed-field" key={key}>
              <span>{label}</span>
              <code>{String(schema.const)}</code>
            </div>
          );
        if (schema.type === "array")
          return (
            <ListField
              key={key}
              label={`${label} (comma separated)`}
              value={Array.isArray(value) ? (value as string[]) : []}
              onChange={change}
            />
          );
        if (schema.type === "boolean")
          return (
            <label className="check-field" key={key}>
              <input
                type="checkbox"
                checked={Boolean(value)}
                onChange={(e) => change(e.target.checked)}
              />
              {label}
            </label>
          );
        return (
          <label className="field-group" key={key}>
            {label}
            {Array.isArray(schema.enum) ? (
              <select
                value={String(value ?? "")}
                onChange={(e) => change(e.target.value)}
              >
                {schema.enum.map((v) => (
                  <option key={String(v)} value={String(v)}>
                    {String(v)}
                  </option>
                ))}
              </select>
            ) : (
              <input
                type={
                  schema.type === "integer" || schema.type === "number"
                    ? "number"
                    : "text"
                }
                min={schema.minimum as number | undefined}
                max={schema.maximum as number | undefined}
                maxLength={schema.maxLength as number | undefined}
                value={String(value ?? "")}
                onChange={(e) =>
                  change(
                    schema.type === "integer" || schema.type === "number"
                      ? e.target.value === ""
                        ? null
                        : Number(e.target.value)
                      : e.target.value,
                  )
                }
              />
            )}
          </label>
        );
      })}
      {Object.keys(properties ?? {}).length === 0 ? (
        <p>This node has no additional configuration.</p>
      ) : null}
    </fieldset>
  );
}

export function PolicyFields({
  policy,
  references,
  nodes,
  onChange,
}: {
  policy: NodePolicy;
  references: RegistryRecord[];
  nodes: WorkflowSpec["nodes"];
  onChange: (value: NodePolicy) => void;
}) {
  return (
    <fieldset>
      <legend>Execution policy</legend>
      <RevisionField
        label="Worker revision"
        kind="worker"
        value={policy.worker_selector?.revision_id}
        references={references}
        onChange={(revision_id) =>
          onChange({
            ...policy,
            worker_selector: revision_id
              ? {
                  revision_id,
                  requires: policy.worker_selector?.requires ?? [],
                }
              : null,
          })
        }
      />
      {policy.worker_selector ? (
        <ListField
          key={policy.worker_selector.revision_id}
          label="Required worker capabilities (comma separated)"
          value={policy.worker_selector.requires ?? []}
          onChange={(requires) =>
            onChange({
              ...policy,
              worker_selector: { ...policy.worker_selector!, requires },
            })
          }
        />
      ) : null}
      {(
        [
          ["model_route_ref", "Model route revision", "route_policy"],
          ["retry_policy_ref", "Retry policy revision", "retry_policy"],
          [
            "permission_policy_ref",
            "Permission policy revision",
            "permission_policy",
          ],
        ] as const
      ).map(([key, label, kind]) => (
        <RevisionField
          key={key}
          label={label}
          kind={kind}
          value={policy[key]}
          references={references}
          onChange={(value) => onChange({ ...policy, [key]: value })}
        />
      ))}
      <label className="field-group">
        Timeout (seconds)
        <input
          type="number"
          min={1}
          max={86400}
          value={policy.timeout_seconds ?? ""}
          onChange={(e) =>
            onChange({
              ...policy,
              timeout_seconds: e.target.value ? Number(e.target.value) : null,
            })
          }
        />
      </label>
      <label className="field-group">
        Maximum concurrency
        <input
          type="number"
          min={1}
          max={1000}
          value={policy.max_concurrency ?? ""}
          onChange={(e) =>
            onChange({
              ...policy,
              max_concurrency: e.target.value ? Number(e.target.value) : null,
            })
          }
        />
      </label>
      <label className="field-group">
        Verification behavior
        <select
          value={
            policy.verification
              ? policy.verification.required
                ? "required"
                : "optional"
              : "inherit"
          }
          onChange={(e) =>
            onChange({
              ...policy,
              verification:
                e.target.value === "inherit"
                  ? null
                  : { source: "task", required: e.target.value === "required" },
            })
          }
        >
          <option value="inherit">Inherit</option>
          <option value="required">Require task verification</option>
          <option value="optional">Task verification optional</option>
        </select>
      </label>
      <label className="field-group">
        Approval action
        <select
          value={policy.approval?.action_type ?? ""}
          onChange={(e) =>
            onChange({
              ...policy,
              approval: e.target.value
                ? {
                    ...policy.approval,
                    action_type: e.target.value as NonNullable<
                      NodePolicy["approval"]
                    >["action_type"],
                  }
                : null,
            })
          }
        >
          <option value="">Inherit / none</option>
          <option value="github.push_and_pr">
            GitHub push and pull request
          </option>
          <option value="git.integrate">Git integrate</option>
          <option value="worker.execute">Worker execute</option>
        </select>
      </label>
      {policy.approval ? (
        <>
          <label className="field-group">
            Required approval node
            <select
              value={policy.approval.required_grant_from ?? ""}
              onChange={(e) =>
                onChange({
                  ...policy,
                  approval: {
                    ...policy.approval,
                    required_grant_from: e.target.value || null,
                  },
                })
              }
            >
              <option value="">Choose a granting node</option>
              {nodes
                .filter((n) => n.type === "approval")
                .map((n) => (
                  <option key={n.id} value={n.id}>
                    {n.label} ({n.id})
                  </option>
                ))}
            </select>
          </label>
          <label className="field-group">
            Approval expiry (seconds)
            <input
              type="number"
              min={1}
              value={policy.approval.expires_in_seconds ?? ""}
              onChange={(e) =>
                onChange({
                  ...policy,
                  approval: {
                    ...policy.approval,
                    expires_in_seconds: e.target.value
                      ? Number(e.target.value)
                      : null,
                  },
                })
              }
            />
          </label>
        </>
      ) : null}
      <label className="check-field">
        <input
          type="checkbox"
          checked={policy.accepts_runtime_instructions ?? false}
          onChange={(e) =>
            onChange({
              ...policy,
              accepts_runtime_instructions: e.target.checked,
            })
          }
        />
        Accept runtime instructions
      </label>
    </fieldset>
  );
}

const predicatePaths = [
  "$.node.result",
  "$.node.status",
  "$.node.failure_class",
  "$.outcome.status",
  "$.outcome.failure_class",
  "$.tasks.terminal_count",
  "$.tasks.total_count",
  "$.tasks.current_task",
  "$.verification.passed",
  "$.review.passed",
  "$.approval.decision",
  "$.approval.action_type",
  "$.approval.granted_by",
  "$.final.status",
  "$.cancelled",
];
const operators: PredicateOperator[] = [
  "eq",
  "neq",
  "in",
  "exists",
  "lt",
  "lte",
  "gt",
  "gte",
  "and",
  "or",
  "not",
];
const leaf = (): Predicate => ({
  op: "eq",
  path: "$.node.result",
  value: "succeeded",
});

export function PredicateFields({
  predicate,
  onChange,
  depth = 0,
  trail = "Condition",
}: {
  predicate: Predicate;
  onChange: (value: Predicate) => void;
  depth?: number;
  trail?: string;
}) {
  const logical = ["and", "or", "not"].includes(predicate.op);
  return (
    <fieldset className="workflow-predicate">
      <legend>{trail}</legend>
      <label className="field-group">
        {trail} operator
        <select
          value={predicate.op}
          onChange={(e) => {
            const op = e.target.value as PredicateOperator;
            onChange(
              ["and", "or", "not"].includes(op)
                ? { op, args: op === "not" ? [leaf()] : [leaf(), leaf()] }
                : {
                    ...leaf(),
                    op,
                    ...(op === "exists"
                      ? { value: null }
                      : op === "in"
                        ? { value: [] }
                        : ["lt", "lte", "gt", "gte"].includes(op)
                          ? { value: 0 }
                          : {}),
                  },
            );
          }}
        >
          {operators
            .filter((op) => depth < 7 || !["and", "or", "not"].includes(op))
            .map((op) => (
              <option key={op}>{op}</option>
            ))}
        </select>
      </label>
      {logical ? (
        <>
          {predicate.args?.map((p, index) => (
            <div key={index}>
              <PredicateFields
                predicate={p}
                depth={depth + 1}
                trail={`${trail} ${index + 1}`}
                onChange={(value) =>
                  onChange({
                    ...predicate,
                    args: predicate.args!.map((child, i) =>
                      i === index ? value : child,
                    ),
                  })
                }
              />
              {predicate.op !== "not" && predicate.args!.length > 2 ? (
                <button
                  type="button"
                  className="text-button"
                  onClick={() =>
                    onChange({
                      ...predicate,
                      args: predicate.args!.filter((_, i) => i !== index),
                    })
                  }
                >
                  Remove {trail} {index + 1}
                </button>
              ) : null}
            </div>
          ))}
          {predicate.op !== "not" && (predicate.args?.length ?? 0) < 8 ? (
            <button
              type="button"
              className="button button-secondary"
              onClick={() =>
                onChange({
                  ...predicate,
                  args: [...(predicate.args ?? []), leaf()],
                })
              }
            >
              Add {trail.toLowerCase()} clause
            </button>
          ) : null}
        </>
      ) : (
        <>
          <label className="field-group">
            {trail} state path
            <select
              value={predicate.path ?? ""}
              onChange={(e) => onChange({ ...predicate, path: e.target.value })}
            >
              {predicate.path && !predicatePaths.includes(predicate.path) ? (
                <option value={predicate.path}>{predicate.path}</option>
              ) : null}
              {predicatePaths.map((path) => (
                <option key={path}>{path}</option>
              ))}
            </select>
          </label>
          {predicate.op === "in" ? (
            <ListField
              label={`${trail} values (comma separated)`}
              value={
                Array.isArray(predicate.value)
                  ? predicate.value.map(String)
                  : []
              }
              onChange={(value) => onChange({ ...predicate, value })}
            />
          ) : predicate.op !== "exists" ? (
            <>
              <label className="field-group">
                {trail} value type
                <select
                  value={
                    predicate.value === null ? "null" : typeof predicate.value
                  }
                  onChange={(e) =>
                    onChange({
                      ...predicate,
                      value:
                        e.target.value === "boolean"
                          ? true
                          : e.target.value === "number"
                            ? 0
                            : e.target.value === "null"
                              ? null
                              : "",
                    })
                  }
                >
                  <option value="string">Text</option>
                  <option value="number">Number</option>
                  <option value="boolean">Boolean</option>
                  <option value="null">Null</option>
                </select>
              </label>
              {typeof predicate.value === "boolean" ? (
                <label className="field-group">
                  {trail} value
                  <select
                    value={String(predicate.value)}
                    onChange={(e) =>
                      onChange({
                        ...predicate,
                        value: e.target.value === "true",
                      })
                    }
                  >
                    <option>true</option>
                    <option>false</option>
                  </select>
                </label>
              ) : predicate.value !== null ? (
                <label className="field-group">
                  {trail} value
                  <input
                    type={
                      typeof predicate.value === "number" ? "number" : "text"
                    }
                    maxLength={2000}
                    value={String(predicate.value ?? "")}
                    onChange={(e) =>
                      onChange({
                        ...predicate,
                        value:
                          typeof predicate.value === "number"
                            ? Number(e.target.value)
                            : e.target.value,
                      })
                    }
                  />
                </label>
              ) : null}
            </>
          ) : null}
        </>
      )}
    </fieldset>
  );
}

export function EdgeFields({
  edge,
  nodes,
  onChange,
}: {
  edge: WorkflowEdge;
  nodes: WorkflowSpec["nodes"];
  onChange: (edge: WorkflowEdge) => void;
}) {
  return (
    <>
      {(["from", "to"] as const).map((key) => (
        <label className="field-group" key={key}>
          {key === "from" ? "Source node" : "Target node"}
          <select
            value={edge[key]}
            onChange={(e) => onChange({ ...edge, [key]: e.target.value })}
          >
            {nodes.map((n) => (
              <option key={n.id} value={n.id}>
                {n.label} ({n.id})
              </option>
            ))}
          </select>
        </label>
      ))}
      <label className="field-group">
        Edge kind
        <select
          value={edge.kind}
          onChange={(e) => {
            const kind = e.target.value as WorkflowEdge["kind"];
            onChange({
              id: edge.id,
              from: edge.from,
              to: edge.to,
              kind,
              priority: edge.priority ?? 0,
              fallback: false,
              when: kind === "always" || kind === "iterate" ? null : leaf(),
              ...(kind === "retry" ? { retry_class: "code.test_failure" } : {}),
              ...(kind === "iterate"
                ? {
                    iteration_key: "planned_tasks",
                    progress_path: "$.tasks.terminal_count",
                    max_iterations: 100,
                  }
                : {}),
            });
          }}
        >
          {["always", "on_result", "on_failure", "retry", "iterate"].map(
            (kind) => (
              <option key={kind}>{kind}</option>
            ),
          )}
        </select>
      </label>
      <label className="field-group">
        Edge priority
        <input
          type="number"
          value={edge.priority ?? 0}
          onChange={(e) =>
            onChange({ ...edge, priority: Number(e.target.value) })
          }
        />
      </label>
      {edge.kind !== "retry" && edge.kind !== "iterate" ? (
        <label className="check-field">
          <input
            type="checkbox"
            checked={edge.fallback ?? false}
            onChange={(e) =>
              onChange({
                ...edge,
                fallback: e.target.checked,
                when:
                  e.target.checked || edge.kind === "always" ? null : leaf(),
              })
            }
          />
          Fallback route
        </label>
      ) : null}
      {edge.kind === "retry" ? (
        <label className="field-group">
          Retry failure class
          <select
            value={edge.retry_class ?? "code.test_failure"}
            onChange={(e) =>
              onChange({
                ...edge,
                retry_class: e.target.value as WorkflowEdge["retry_class"],
              })
            }
          >
            {[
              "code.implementation_failure",
              "code.test_failure",
              "code.review_failure",
              "code.git_conflict",
              "infrastructure.worker_unavailable",
              "infrastructure.worker_transport",
              "infrastructure.service_unavailable",
              "provider.rate_limited",
              "provider.transient",
              "provider.contract_failure",
              "orchestration.runtime_error",
            ].map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        </label>
      ) : null}
      {edge.kind === "iterate" ? (
        <>
          <label className="field-group">
            Iteration key
            <input
              maxLength={80}
              value={edge.iteration_key ?? ""}
              onChange={(e) =>
                onChange({ ...edge, iteration_key: e.target.value })
              }
            />
          </label>
          <p>
            Progress: <code>$.tasks.terminal_count</code>
          </p>
          <label className="field-group">
            Maximum iterations
            <input
              type="number"
              min={1}
              max={10000}
              value={edge.max_iterations ?? 100}
              onChange={(e) =>
                onChange({ ...edge, max_iterations: Number(e.target.value) })
              }
            />
          </label>
        </>
      ) : null}
      {edge.kind !== "always" && !edge.fallback ? (
        <>
          <label className="check-field">
            <input
              type="checkbox"
              checked={Boolean(edge.when)}
              onChange={(e) =>
                onChange({ ...edge, when: e.target.checked ? leaf() : null })
              }
            />
            Use a condition
          </label>
          {edge.when ? (
            <PredicateFields
              key={`${edge.id}-${edge.kind}`}
              predicate={edge.when}
              onChange={(when) => onChange({ ...edge, when })}
            />
          ) : null}
        </>
      ) : null}
    </>
  );
}
