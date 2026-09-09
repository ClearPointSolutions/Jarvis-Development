"use client";

import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { useSession } from "@/lib/session";
import { createRuntimeClient } from "@/lib/api/runtime";
import { WorkflowCanvas } from "@/components/workflow-canvas";
import { RunApprovals } from "@/components/run-approvals";
import type { WorkflowSpec, WorkflowLayout } from "@jarvis/contracts";

/** Presentation order only: follow published connections without executing them. */
function runtimeLayout(spec: WorkflowSpec): WorkflowLayout {
  const order: string[] = [];
  function visit(id: string) {
    if (order.includes(id)) return;
    order.push(id);
    for (const edge of spec.edges.filter(
      (e) => e.from === id && e.kind !== "retry" && !e.fallback,
    ))
      visit(edge.to);
  }
  visit(spec.entrypoint);
  for (const node of spec.nodes) visit(node.id);
  return {
    nodes: Object.fromEntries(
      order.map((id, index) => [
        id,
        { x: (index % 4) * 240, y: Math.floor(index / 4) * 170 },
      ]),
    ),
  };
}

export function RunExperience({ runId }: { runId: string }) {
  const session = useSession();
  const queries = useQueryClient();
  const client = useMemo(
    () => createRuntimeClient(session.data?.csrf_token),
    [session.data?.csrf_token],
  );
  const enabled = Boolean(session.data);
  const run = useQuery({
    queryKey: ["runtime-run", runId],
    queryFn: () => client.get(runId),
    enabled,
  });
  const tasks = useQuery({
    queryKey: ["runtime-tasks", runId],
    queryFn: () => client.tasks(runId),
    enabled,
  });
  const nodes = useQuery({
    queryKey: ["runtime-nodes", runId],
    queryFn: () => client.nodes(runId),
    enabled,
  });
  const workflow = useQuery({
    queryKey: ["runtime-workflow", runId],
    queryFn: () => client.workflow(runId),
    enabled,
  });
  const decision = useQuery({
    queryKey: ["runtime-decision", runId],
    queryFn: () => client.decision(runId),
    enabled,
  });
  const evidence = useQuery({
    queryKey: ["runtime-evidence", runId],
    queryFn: () => client.evidence(runId),
    enabled,
  });
  const events = { data: evidence.data?.items ?? [] };
  const usage = useQuery({
    queryKey: ["runtime-usage", runId],
    queryFn: () => client.usage(runId),
    enabled,
    refetchInterval: 5000,
  });
  const usageEvents = Array.from(
    new Map(
      events.data
        .filter((event) => event.type === "model.usage_recorded")
        .sort((a, b) => a.global_position - b.global_position)
        .map((event) => [event.correlation_id, event]),
    ).values(),
  );
  const integration = useQuery({
    queryKey: ["runtime-integration", runId],
    queryFn: () => client.integrationHeads(runId),
    enabled,
    refetchInterval: 5000,
  });
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const items = tasks.data?.items ?? [];
  const complete = items.filter((t) => t.status === "succeeded");
  const weight = items.reduce((sum, t) => sum + t.weight, 0);
  const percent = weight
    ? Math.round(
        (100 * complete.reduce((sum, t) => sum + t.weight, 0)) / weight,
      )
    : 0;
  const projection = Object.fromEntries([
    ...(workflow.data?.nodes ?? []).map((n) => [n.id, "Not visited"]),
    ...(nodes.data?.items ?? []).map((n) => [n.workflow_node_id, n.status]),
  ]);
  async function decide(value: "approved" | "rejected") {
    if (!decision.data) return;
    setBusy(true);
    try {
      await client.decide(runId, {
        decision_id: decision.data.id,
        decision: value,
        expected_run_version: (await client.get(runId)).version,
        idempotency_key: crypto.randomUUID(),
      });
      setMessage(`Demo decision ${value} recorded.`);
      await queries.invalidateQueries({
        queryKey: ["runtime-decision", runId],
      });
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Decision failed");
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      {run.data?.mode === "real" && <RunApprovals runId={runId} />}
      <section
        className="content-card run-experience-card"
        aria-label="Organizer conversation"
      >
        <h2>Organizer conversation</h2>
        <p>
          Objective, Organizer responses and follow-up instructions persist with
          this run. Instructions take effect only at declared safe points.
        </p>
        <ol>
          {events.data
            .filter((event) => event.type === "message.created")
            .map((event) => (
              <li key={event.event_id}>
                <strong>{String(event.data.role)}</strong>
                <p style={{ whiteSpace: "pre-wrap" }}>
                  {String(event.data.body)}
                </p>
              </li>
            ))}
        </ol>
        <p>
          Use the run instruction control for follow-up requests. The event
          timeline provides persisted history.
        </p>
      </section>
      <section
        className="content-card run-experience-card"
        aria-label="Runtime workflow"
      >
        <p className="eyebrow">
          {run.data?.mode === "demo"
            ? "DEMO · deterministic external dependencies"
            : "Runtime"}
        </p>
        <h2>Workflow execution</h2>
        <p>
          Published workflow with persisted node states.{" "}
          {run.data?.result_summary}
        </p>
        {workflow.data && (
          <WorkflowCanvas
            spec={workflow.data}
            layout={runtimeLayout(workflow.data)}
            readOnly
            selection={null}
            onSelect={() => {}}
            onLayout={() => {}}
            onConnect={() => {}}
            onRemove={() => {}}
            projection={projection}
            transitions={events.data
              .filter((e) => e.type === "graph.route_selected")
              .map((e) => ({
                from: String(e.data.from),
                to: String(e.data.to),
              }))}
          />
        )}
        {workflow.error && <p role="alert">Workflow could not be loaded.</p>}
      </section>
      <section
        className="content-card run-experience-card"
        aria-label="Task progress"
      >
        <h2>Tasks and attempts</h2>
        <p aria-live="polite">
          {complete.length} of {items.length} tasks completed ·{" "}
          {items.filter((t) => t.status === "running").length} active ·{" "}
          {items.filter((t) => ["waiting", "failed"].includes(t.status)).length}{" "}
          failed or retrying ·{" "}
          {
            items.filter((t) => ["pending", "blocked"].includes(t.status))
              .length
          }{" "}
          pending or blocked
        </p>
        {weight > 0 && (
          <progress
            aria-label="Completed task weight"
            value={percent}
            max={100}
          >
            {percent}%
          </progress>
        )}
        <p>Progress counts only the weight of succeeded tasks.</p>
        <ul>
          {items.map((task) => (
            <li key={task.id}>
              <strong>
                {task.key}: {task.title}
              </strong>{" "}
              · {task.status}
              <p>
                {task.dependencies.length} dependencies ·{" "}
                {task.attempts
                  .map((a) => `Attempt ${a.number}: ${a.status}`)
                  .join("; ") || "No coding attempt yet"}
              </p>
            </li>
          ))}
        </ul>
        {tasks.error && <p role="alert">Task history could not be loaded.</p>}
      </section>
      <section
        className="content-card run-experience-card"
        aria-label="Repository verification and review"
      >
        <h2>Repository verification and review</h2>
        <p>
          Each review applies to its recorded candidate SHA. Integration
          requires separate combined gates.
        </p>
        <ul>
          {events.data
            .filter((event) =>
              /^(test\.|review\.|file\.snapshot_created|git\.integration_)/.test(
                event.type,
              ),
            )
            .map((event) => (
              <li key={event.event_id}>
                <details>
                  <summary>
                    {event.type} ·{" "}
                    {String(
                      event.data.summary ??
                        event.data.head_sha ??
                        event.data.source_sha ??
                        "Recorded evidence",
                    )}
                  </summary>
                  <dl>
                    {Object.entries(event.data)
                      .filter(
                        ([key, value]) =>
                          !key.endsWith("artifact_id") &&
                          (typeof value === "string" ||
                            typeof value === "number" ||
                            typeof value === "boolean"),
                      )
                      .map(([key, value]) => (
                        <div key={key}>
                          <dt>{key.replaceAll("_", " ")}</dt>
                          <dd>
                            <code>{String(value)}</code>
                          </dd>
                        </div>
                      ))}
                  </dl>
                  {Object.entries(event.data)
                    .filter(
                      ([key, value]) =>
                        key.endsWith("artifact_id") &&
                        typeof value === "string" &&
                        /^[0-9a-f-]{36}$/.test(value),
                    )
                    .map(([key, value]) => (
                      <p key={key}>
                        <a href={`/api/v1/artifacts/${String(value)}`}>
                          {key.replaceAll("_", " ")}
                        </a>
                      </p>
                    ))}
                </details>
              </li>
            ))}
        </ul>
        <h3>Authoritative integration HEAD</h3>
        {(integration.data?.items ?? []).map((head) => (
          <div key={head.repository_id}>
            <p>
              Branch: <code>{head.branch}</code>
            </p>
            <p>
              Base: <code>{head.base_sha}</code>
            </p>
            <p>
              Current HEAD: <code>{head.head_sha}</code>
            </p>
            <p>
              Lease generation {head.generation} ·{" "}
              {head.released_at
                ? "released"
                : head.lease_owner
                  ? "acquired"
                  : "not acquired"}
            </p>
            {head.snapshot_artifact_id && (
              <a href={`/api/v1/artifacts/${head.snapshot_artifact_id}`}>
                Sealed integration snapshot
              </a>
            )}
          </div>
        ))}
        {!integration.data?.items.length && (
          <p>No integration HEAD has been recorded.</p>
        )}
        {integration.error && (
          <p role="alert">Integration state could not be loaded.</p>
        )}
      </section>
      {decision.data && (
        <section
          className="content-card run-experience-card"
          aria-label="Demo publication decision"
        >
          <h2>DEMO publication decision</h2>
          <p>
            This decision simulates publication and cannot authorize a real
            external action.
          </p>
          <p>Status: {decision.data.decision}</p>
          {decision.data.decision === "pending" && (
            <div className="button-row">
              <button
                className="button"
                disabled={busy || run.data?.status !== "approval_required"}
                onClick={() => void decide("approved")}
              >
                Approve demo publication
              </button>
              <button
                className="button"
                disabled={busy || run.data?.status !== "approval_required"}
                onClick={() => void decide("rejected")}
              >
                Reject demo publication
              </button>
            </div>
          )}
          <p role="status">{message}</p>
        </section>
      )}
      <section
        className="content-card run-experience-card"
        aria-label="Retry history"
      >
        <h2>
          {run.data?.mode === "demo"
            ? "DEMO dependency health"
            : "Dependency health"}
        </h2>
        <ul>
          {events.data
            .filter((e) => e.type === "service.health_changed")
            .map((e) => (
              <li key={e.event_id}>
                {String(e.data.service)}: {String(e.data.health)}
              </li>
            ))}
        </ul>
        <h2>Retry history</h2>
        <ul>
          {events.data
            .filter((e) => e.type === "retry.budget_consumed")
            .map((e) => (
              <li key={e.event_id}>
                {String(e.data.failure_class)}: {String(e.data.used_retries)}/
                {String(e.data.max_retries)} retries consumed
              </li>
            ))}
        </ul>
      </section>
      <section
        className="content-card run-experience-card"
        aria-label="Run artifacts"
      >
        <h2>Model usage</h2>
        <p>
          {usage.data?.calls ?? usageEvents.length} durable model calls
          {run.data?.mode === "demo"
            ? " · token estimates are DEMO fixture values."
            : "."}
        </p>
        {usage.data && (
          <p>
            {usage.data.total_tokens ?? "Unknown"} total gateway tokens (
            {usage.data.provenance}); {usage.data.known_tokens} known tokens,{" "}
            {usage.data.unknown_usage_calls} calls with unknown usage.
            Worker-managed model usage is unavailable.
          </p>
        )}
        {usage.data?.currencies.map((cost) => (
          <p key={cost.currency}>
            {cost.currency}: {cost.total ?? cost.status}; known subtotal{" "}
            {cost.known_subtotal} ({cost.status}).
          </p>
        ))}
        <ul>
          {usageEvents.map((e) => (
            <li key={e.event_id}>
              {workflow.data?.nodes.find(
                (n) => n.id === e.scope?.workflow_node_id,
              )?.label ?? "Model"}
              :{" "}
              {String(
                typeof e.data.usage === "object" &&
                  e.data.usage &&
                  !Array.isArray(e.data.usage) &&
                  "total_tokens" in e.data.usage
                  ? (e.data.usage.total_tokens ?? "unknown")
                  : "unknown",
              )}{" "}
              tokens (
              {typeof e.data.usage === "object" &&
              e.data.usage &&
              !Array.isArray(e.data.usage) &&
              "provenance" in e.data.usage
                ? String(e.data.usage.provenance ?? "unknown")
                : "unknown"}
              )
            </li>
          ))}
        </ul>
        <h2>Immutable artifacts</h2>
        <ul>
          {events.data
            .filter((e) => e.type === "artifact.created")
            .flatMap((e) =>
              (e.artifact_refs ?? []).map((a) => (
                <li key={`${e.event_id}-${a.artifact_id}`}>
                  <a href={`/api/v1/artifacts/${a.artifact_id}`}>
                    {String(e.data.name ?? a.relation)}
                  </a>
                </li>
              )),
            )}
        </ul>
      </section>
    </>
  );
}
