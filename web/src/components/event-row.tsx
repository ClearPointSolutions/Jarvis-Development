import { safeDisplayText } from "@/lib/content-safety";
import type { NormalizedEvent } from "@jarvis/contracts";

import { DemoBadge, StatusLabel } from "@/components/states";

const eventLabels: Record<string, string> = {
  "auth.login_succeeded": "Authentication",
  "run.queued": "Run queued",
  "run.started": "Run started",
  "run.completed": "Run completed",
  "project.created": "Project created",
  "job.created": "Job created",
  "run.claimed": "Run claimed",
  "run.pause_requested": "Pause requested",
  "run.paused": "Run paused",
  "run.resumed": "Run resumed",
  "run.cancel_requested": "Cancellation requested",
  "run.cancelled": "Run cancelled",
  "run.recovering": "Recovering run",
  "run.recovered": "Run recovered",
  "run.failed": "Run failed",
  "run.blocked": "Run blocked",
  "run.command_requested": "Command recorded",
  "run.command_applied": "Command applied",
  "run.command_rejected": "Command rejected or superseded",
  "node.queued": "Node queued",
  "node.started": "Node started",
  "node.waiting": "Node waiting",
  "node.interrupted": "Node interrupted",
  "node.succeeded": "Node succeeded",
  "node.failed": "Node failed",
  "node.cancelled": "Node cancelled",
  "effect.prepared": "Effect prepared",
  "effect.dispatched": "Effect dispatched",
  "effect.succeeded": "Effect succeeded",
  "effect.cancel_requested": "Effect cancellation requested",
  "effect.cancelled": "Effect cancelled",
  "effect.unknown": "Effect needs reconciliation",
  "lease.expired": "Lease expired",
  "failure.classified": "Failure classified",
  "retry.budget_consumed": "Retry scheduled",
  "retry.budget_exhausted": "Retry budget exhausted",
  "graph.checkpointed": "Graph checkpointed",
  "graph.route_selected": "Graph route selected",
  "model.route_selected": "Model route selected",
  "model.failover": "Model failover",
  "instruction.applied": "Instruction delivered",
  "task.created": "Task created",
  "test.completed": "Verification completed",
};

const severityTone = {
  critical: "danger",
  debug: "neutral",
  error: "danger",
  info: "neutral",
  success: "good",
  warning: "warning",
} as const;

export function EventRow({ event }: { event: NormalizedEvent }) {
  const knownLabel = eventLabels[event.type];
  return (
    <article className="event-row">
      <div className="event-row-meta">
        <StatusLabel
          label={event.severity}
          tone={severityTone[event.severity] ?? "neutral"}
        />
        {event.mode === "demo" ? <DemoBadge /> : null}
        <time dateTime={event.recorded_at}>
          {new Date(event.recorded_at).toLocaleString()}
        </time>
      </div>
      <h3>{knownLabel ?? "Observable event"}</h3>
      <p>{safeDisplayText(event.message)}</p>
      <code>{safeDisplayText(event.type)}</code>
      {!knownLabel ? (
        <span className="unknown-label">Unknown event type</span>
      ) : null}
    </article>
  );
}
