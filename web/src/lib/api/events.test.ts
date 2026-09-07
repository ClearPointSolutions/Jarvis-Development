import { describe, expect, it } from "vitest";
import { mergeEvent, parseStreamEvent } from "./events";
const event = {
  schema_version: "1.1",
  event_id: "event-one",
  global_position: 1,
  message: "<script>text</script>",
  type: "system.future_minor",
  recorded_at: "2026-09-07T00:00:00Z",
  severity: "info",
};
describe("stream envelope recovery", () => {
  it("accepts unknown minor event types and deduplicates reconnect delivery", () => {
    const parsed = parseStreamEvent(JSON.stringify(event));
    expect(mergeEvent([parsed], parsed)).toHaveLength(1);
    expect(parsed.message).toBe("<script>text</script>");
  });
  it("rejects unsupported majors and malformed envelopes", () => {
    expect(() =>
      parseStreamEvent(JSON.stringify({ ...event, schema_version: "2.0" })),
    ).toThrow("Unsupported");
    expect(() =>
      parseStreamEvent(JSON.stringify({ ...event, message: { html: "bad" } })),
    ).toThrow("Invalid");
    expect(() => parseStreamEvent("null")).toThrow("Invalid");
  });
  it("orders replayed rows and bounds the visible event cache", () => {
    const parsed = parseStreamEvent(JSON.stringify(event));
    const rows = Array.from({ length: 200 }, (_, i) => ({
      ...parsed,
      event_id: String(i + 2),
      global_position: i + 2,
    }));
    const merged = mergeEvent(rows, {
      ...parsed,
      event_id: "last",
      global_position: 202,
    });
    expect(merged).toHaveLength(200);
    expect(merged[0].global_position).toBe(3);
    expect(merged.at(-1)?.global_position).toBe(202);
  });
});
