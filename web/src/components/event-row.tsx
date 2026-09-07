import type { NormalizedEvent } from "@jarvis/contracts";

import { DemoBadge, StatusLabel } from "@/components/states";

const eventLabels: Record<string, string> = {
  "auth.login_succeeded": "Authentication",
  "run.queued": "Run queued",
  "run.started": "Run started",
  "run.completed": "Run completed",
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
          tone={severityTone[event.severity]}
        />
        {event.mode === "demo" ? <DemoBadge /> : null}
        <time dateTime={event.recorded_at}>
          {new Date(event.recorded_at).toLocaleString()}
        </time>
      </div>
      <h3>{knownLabel ?? "Observable event"}</h3>
      <p>{event.message}</p>
      <code>{event.type}</code>
      {!knownLabel ? (
        <span className="unknown-label">Unknown event type</span>
      ) : null}
    </article>
  );
}
