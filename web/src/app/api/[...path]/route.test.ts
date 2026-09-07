import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { GET, POST } from "./route";
afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});
describe("same-origin API transport", () => {
  it("preserves validated public Host and SSE cursor without trusting forwarding headers", async () => {
    vi.stubEnv("JARVIS_API_URL", "http://127.0.0.1:8000");
    const upstream = vi.fn().mockResolvedValue(
      new Response("event: jarvis.event\ndata: {}\n\n", {
        headers: {
          "content-type": "text/event-stream",
          "set-cookie": "opaque=synthetic; HttpOnly; SameSite=Strict",
        },
      }),
    );
    vi.stubGlobal("fetch", upstream);
    const response = await GET(
      new NextRequest(
        "http://127.0.0.1:3000/api/v1/runs/id/events/stream?after=7",
        {
          headers: {
            host: "127.0.0.1:3000",
            origin: "http://127.0.0.1:3000",
            "last-event-id": "9",
            "x-forwarded-host": "evil.invalid",
            cookie: "opaque=synthetic",
          },
        },
      ),
      {
        params: Promise.resolve({
          path: ["v1", "runs", "id", "events", "stream"],
        }),
      },
    );
    const [url, options] = upstream.mock.calls[0];
    expect(String(url)).toBe(
      "http://127.0.0.1:8000/api/v1/runs/id/events/stream?after=7",
    );
    expect(options.headers.get("host")).toBe("127.0.0.1:3000");
    expect(options.headers.get("last-event-id")).toBe("9");
    expect(options.headers.has("x-forwarded-host")).toBe(false);
    expect(response.headers.get("set-cookie")).toContain("HttpOnly");
    expect(await response.text()).toContain("jarvis.event");
  });
  it("returns a safe error when the backend is unavailable", async () => {
    vi.stubEnv("JARVIS_API_URL", "http://127.0.0.1:8000");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new Error("private backend exception")),
    );
    const response = await POST(
      new NextRequest("http://localhost/api/v1/auth/login", {
        method: "POST",
        headers: { host: "localhost", "content-type": "application/json" },
        body: "{}",
      }),
      { params: Promise.resolve({ path: ["v1", "auth", "login"] }) },
    );
    expect(response.status).toBe(502);
    expect(await response.text()).not.toContain("private backend exception");
  });
});
