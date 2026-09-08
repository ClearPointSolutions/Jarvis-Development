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
  "task.ready": "Task ready",
  "task.dependencies_set": "Dependencies recorded",
  "task.attempt_started": "Developer attempt started",
  "task.verifying": "Verifying task",
  "task.reviewing": "Reviewing task",
  "task.succeeded": "Task succeeded",
  "task.retry_scheduled": "Task retry scheduled",
  "worker.invocation_dispatched": "Demo worker dispatched",
  "worker.invocation_completed": "Demo worker completed",
  "worker.invocation_failed": "Demo worker failed",
  "worker.cancelled": "Worker cancelled",
  "command.started": "Command activity started",
  "command.completed": "Command activity completed",
  "file.write_completed": "File change recorded",
  "test.started": "Verification started",
  "test.failed": "Verification failed",
  "review.started": "Review started",
  "review.failed": "Review failed",
  "review.completed": "Review completed",
  "model.call_started": "Model call started",
  "model.call_completed": "Model call completed",
  "model.call_failed": "Model call failed",
  "model.usage_recorded": "Model usage recorded",
  "service.health_changed": "Dependency health changed",
  "artifact.created": "Immutable artifact created",
  "approval.requested": "Decision requested",
  "approval.decided": "Decision recorded",
  "git.push_started": "Publication started",
  "git.pr_created": "Publication recorded",
  "git.ci_updated": "CI status updated",
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
      {event.data?.summary || event.data?.feedback || event.data?.ci ? (
        <p>
          {safeDisplayText(
            String(
              event.data.feedback ?? event.data.summary ?? event.data.ci,
            ).slice(0, 1000),
          )}
        </p>
      ) : null}
      <code>{safeDisplayText(event.type)}</code>
      {!knownLabel ? (
        <span className="unknown-label">Unknown event type</span>
      ) : null}
    </article>
  );
}
