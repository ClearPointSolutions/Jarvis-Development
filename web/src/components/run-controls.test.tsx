import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { AppProviders } from "./app-providers";
import { RunControls } from "./run-controls";

afterEach(() => vi.unstubAllGlobals());
it("refreshes a raced run version once while preserving command identity", async () => {
  const bodies: Record<string, unknown>[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        bodies.push(JSON.parse(String(init.body)));
        return bodies.length === 1
          ? Response.json({ detail: "Run version changed" }, { status: 409 })
          : Response.json({ sequence: 4 });
      }
      if (url.endsWith("/commands")) return Response.json({ items: [] });
      return Response.json({
        id: "run",
        status: "running",
        desired_state: "running",
        version: 7 + bodies.length,
        recovering: false,
      });
    }),
  );
  render(
    <AppProviders
      apiClient={{
        getSession: vi.fn().mockResolvedValue({ csrf_token: "synthetic-csrf" }),
        login: vi.fn(),
        logout: vi.fn(),
      }}
    >
      <RunControls runId="run" />
    </AppProviders>,
  );
  await userEvent
    .setup()
    .click(await screen.findByRole("button", { name: "Cancel" }));
  expect(await screen.findByText(/Command 4 recorded\./)).toBeVisible();
  expect(bodies).toHaveLength(2);
  expect(bodies[0]).toMatchObject({ kind: "cancel", expected_run_version: 7 });
  expect(bodies[1]).toMatchObject({
    kind: "cancel",
    expected_run_version: 8,
    idempotency_key: bodies[0].idempotency_key,
  });
});
it.each(["running", "pause_requested", "paused", "cancelled", "blocked"])(
  "uses truthful controls for %s and durable receipts",
  async (status) => {
    const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
      if (init?.method === "POST") return Response.json({ sequence: 4 });
      if (_url.endsWith("/commands"))
        return Response.json({
          items: [
            { id: "command", sequence: 3, kind: "pause", status: "applied" },
          ],
        });
      return Response.json({
        id: "run",
        status,
        desired_state:
          status === "paused" || status === "pause_requested"
            ? "paused"
            : "running",
        version: 7,
        recovering: false,
      });
    });
    vi.stubGlobal("fetch", fetchMock);
    render(
      <AppProviders
        apiClient={{
          getSession: vi
            .fn()
            .mockResolvedValue({ csrf_token: "synthetic-csrf" }),
          login: vi.fn(),
          logout: vi.fn(),
        }}
      >
        <RunControls runId="run" />
      </AppProviders>,
    );
    const pause = await screen.findByRole("button", {
      name: "Pause",
    });
    const resume = screen.getByRole("button", { name: "Resume" });
    if (status === "running") expect(pause).toBeEnabled();
    else expect(pause).toBeDisabled();
    if (status === "paused") expect(resume).toBeEnabled();
    else expect(resume).toBeDisabled();
    if (status === "cancelled" || status === "blocked")
      expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    expect(await screen.findByText("Command 3: pause — applied")).toBeVisible();
    if (status === "running") {
      await userEvent.setup().click(pause);
      await waitFor(() =>
        expect(fetchMock).toHaveBeenCalledWith(
          "/api/v1/runs/run/commands",
          expect.objectContaining({ method: "POST" }),
        ),
      );
      const mutation = fetchMock.mock.calls.find(
        ([, options]) => options?.method === "POST",
      )![1]!;
      expect(JSON.parse(String(mutation.body))).toMatchObject({
        expected_run_version: 7,
        kind: "pause",
      });
      expect(mutation.headers).toMatchObject({
        "X-CSRF-Token": "synthetic-csrf",
      });
      expect(screen.getByText(/Command 4 recorded\./)).toBeVisible();
    }
  },
);
