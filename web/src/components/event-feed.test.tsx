import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AppProviders } from "./app-providers";
import { EventFeed } from "./event-feed";
class FakeSource {
  static instances: FakeSource[] = [];
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  listeners = new Map<string, (event: { data: string }) => void>();
  close = vi.fn();
  constructor(readonly url: string) {
    FakeSource.instances.push(this);
  }
  addEventListener(name: string, callback: (event: { data: string }) => void) {
    this.listeners.set(name, callback);
  }
  emit(name: string, value: unknown) {
    this.listeners.get(name)?.({ data: JSON.stringify(value) });
  }
}
const projection = {
  run_id: "run-id",
  status: "queued",
  last_event_position: 0,
  last_run_sequence: 0,
  last_event_at: null,
  read_cursor: 0,
};
afterEach(() => {
  vi.unstubAllGlobals();
  FakeSource.instances = [];
});
describe("authorized activity", () => {
  it("replays duplicate delivery once and refreshes authoritative projection", async () => {
    vi.stubGlobal("EventSource", FakeSource);
    const fetchMock = vi
      .fn()
      .mockImplementation(() => Promise.resolve(Response.json(projection)));
    vi.stubGlobal("fetch", fetchMock);
    const view = render(
      <AppProviders>
        <EventFeed runId="run-id" />
      </AppProviders>,
    );
    await waitFor(() => expect(FakeSource.instances).toHaveLength(1));
    const source = FakeSource.instances[0];
    expect(source.url).toContain("after=0");
    const event = {
      schema_version: "1.0",
      event_id: "one",
      global_position: 1,
      message: "Persisted event",
      type: "future.minor",
      recorded_at: "2026-09-07T00:00:00Z",
      severity: "info",
    };
    fetchMock.mockImplementation(() =>
      Promise.resolve(
        Response.json({
          ...projection,
          last_event_position: 1,
          status: "running",
        }),
      ),
    );
    act(() => {
      source.onopen?.();
      source.emit("jarvis.event", event);
      source.emit("jarvis.event", event);
    });
    expect(await screen.findByText("Persisted event")).toBeVisible();
    expect(screen.getAllByText("Persisted event")).toHaveLength(1);
    await waitFor(() =>
      expect(screen.getByTestId("run-status")).toHaveTextContent("running"),
    );
    view.unmount();
    expect(source.close).toHaveBeenCalledOnce();
  });
  it("resets at a fresh server snapshot cursor and closes unsupported versions", async () => {
    vi.stubGlobal("EventSource", FakeSource);
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockImplementation(() =>
          Promise.resolve(Response.json({ ...projection, read_cursor: 12 })),
        ),
    );
    render(
      <AppProviders>
        <EventFeed runId="run-id" />
      </AppProviders>,
    );
    await waitFor(() => expect(FakeSource.instances).toHaveLength(1));
    act(() =>
      FakeSource.instances[0].emit("stream.reset", {
        reason: "cursor_expired",
      }),
    );
    await waitFor(() => expect(FakeSource.instances).toHaveLength(2));
    expect(FakeSource.instances[1].url).toContain("after=12");
    act(() =>
      FakeSource.instances[1].emit("stream.reset", {
        reason: "unsupported_schema",
      }),
    );
    expect(
      await screen.findByText(/Update Mission Control before reconnecting/),
    ).toBeVisible();
    expect(FakeSource.instances[1].close).toHaveBeenCalled();
  });
});
