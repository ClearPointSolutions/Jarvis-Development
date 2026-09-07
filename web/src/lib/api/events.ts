import type { NormalizedEvent } from "@jarvis/contracts";

// JSON is untrusted even on an authenticated stream. Unknown minor event types
// remain inert text; incompatible envelopes stop delivery instead of guessing.
export function parseStreamEvent(value: string): NormalizedEvent {
  const event: unknown = JSON.parse(value);
  if (!event || typeof event !== "object")
    throw new Error("Invalid event envelope");
  const row = event as Record<string, unknown>;
  if (
    typeof row.schema_version !== "string" ||
    !/^1\.\d+$/.test(row.schema_version)
  )
    throw new Error(
      "Unsupported event schema. Reload after updating Mission Control.",
    );
  if (
    !Number.isSafeInteger(row.global_position) ||
    Number(row.global_position) < 1 ||
    typeof row.event_id !== "string" ||
    typeof row.message !== "string" ||
    typeof row.type !== "string" ||
    typeof row.recorded_at !== "string" ||
    typeof row.severity !== "string"
  )
    throw new Error("Invalid event envelope");
  return event as NormalizedEvent;
}

export function mergeEvent(
  events: NormalizedEvent[],
  incoming: NormalizedEvent,
): NormalizedEvent[] {
  if (
    events.some(
      (event) =>
        event.event_id === incoming.event_id ||
        event.global_position === incoming.global_position,
    )
  )
    return events;
  return [...events, incoming]
    .sort((a, b) => a.global_position - b.global_position)
    .slice(-200);
}
