// @vitest-environment node
import {
  createServer,
  type Server,
  type RequestListener,
  type IncomingHttpHeaders,
} from "node:http";
import { once } from "node:events";
import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { GET, POST } from "./route";
const servers: Server[] = [];
async function backend(listener: RequestListener) {
  const server = createServer(listener);
  servers.push(server);
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  const address = server.address();
  if (!address || typeof address === "string")
    throw new Error("Missing test port");
  vi.stubEnv("JARVIS_API_URL", `http://127.0.0.1:${address.port}`);
  return server;
}
afterEach(async () => {
  vi.unstubAllEnvs();
  await Promise.all(
    servers.splice(0).map(
      (server) =>
        new Promise<void>((resolve) => {
          server.closeAllConnections();
          server.close(() => resolve());
        }),
    ),
  );
});
describe("same-origin native HTTP transport", () => {
  it.each([65_536, 65_537])(
    "bounds streamed mutation bytes at %s without trusting Content-Length",
    async (size) => {
      let received = 0;
      let calls = 0;
      await backend((request, response) => {
        calls++;
        request.on("data", (chunk) => {
          received += chunk.length;
        });
        request.on("end", () => {
          response.setHeader("Content-Type", "application/json");
          response.end('{"revoked":true}');
        });
      });
      let sent = 0;
      const body = new ReadableStream<Uint8Array>({
        pull(controller) {
          if (sent === size) {
            controller.close();
            return;
          }
          const length = Math.min(16_384, size - sent);
          sent += length;
          controller.enqueue(new Uint8Array(length));
        },
      });
      const request = new NextRequest("http://localhost/api/v1/auth/login", {
        method: "POST",
        headers: { host: "localhost", "content-length": "2" },
        body,
        duplex: "half",
      } as ConstructorParameters<typeof NextRequest>[1]);
      const response = await POST(request, {
        params: Promise.resolve({ path: ["v1", "auth", "login"] }),
      });
      expect(response.status).toBe(size === 65_536 ? 200 : 413);
      const payload = await response.json();
      if (size === 65_536) {
        expect(calls).toBe(1);
        expect(received).toBe(size);
      } else {
        expect(calls).toBe(0);
        expect(payload.error.code).toBe("request.too_large");
      }
    },
  );
  it("preserves actual public Host, cursor, origin and cookies across loopback HTTP", async () => {
    let received: IncomingHttpHeaders = {};
    let receivedPath = "";
    await backend((request, response) => {
      received = request.headers;
      receivedPath = request.url ?? "";
      response.writeHead(200, {
        "Content-Type": "text/event-stream",
        "Set-Cookie": "opaque=synthetic; HttpOnly; SameSite=Strict",
      });
      response.end("event: jarvis.event\ndata: {}\n\n");
    });
    const response = await GET(
      new NextRequest(
        "http://127.0.0.1:3000/api/v1/runs/id/events/stream?after=7",
        {
          headers: {
            host: "127.0.0.1:3000",
            origin: "http://127.0.0.1:3000",
            "last-event-id": "9",
            "sec-fetch-site": "same-origin",
            "x-forwarded-host": "evil.invalid",
            "x-forwarded-for": "evil.invalid",
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
    expect(await response.text()).toContain("jarvis.event");
    expect(receivedPath).toBe("/api/v1/runs/id/events/stream?after=7");
    expect(received.host).toBe("127.0.0.1:3000");
    expect(received.origin).toBe("http://127.0.0.1:3000");
    expect(received["last-event-id"]).toBe("9");
    expect(received["sec-fetch-site"]).toBe("same-origin");
    expect(received.cookie).toBe("opaque=synthetic");
    expect(received["x-forwarded-host"]).toBeUndefined();
    expect(received["x-forwarded-for"]).toBeUndefined();
    expect(response.headers.get("set-cookie")).toContain("HttpOnly");
  });
  it("streams an open response and tears down its socket when the browser disconnects", async () => {
    let disconnected = false;
    await backend((request, response) => {
      response.writeHead(200, { "Content-Type": "text/event-stream" });
      response.write(": keepalive\n\n");
      request.once("close", () => {
        disconnected = true;
      });
    });
    const controller = new AbortController();
    const response = await GET(
      new NextRequest("http://localhost/api/v1/runs/id/events/stream", {
        headers: { host: "localhost" },
        signal: controller.signal,
      }),
      {
        params: Promise.resolve({
          path: ["v1", "runs", "id", "events", "stream"],
        }),
      },
    );
    const reader = response.body!.getReader();
    expect((await reader.read()).value?.byteLength).toBeGreaterThan(0);
    controller.abort();
    await reader.read().catch(() => undefined);
    await vi.waitFor(() => expect(disconnected).toBe(true));
  });
  it("returns a safe error when the backend closes without a response", async () => {
    await backend((request) => request.socket.destroy());
    const response = await POST(
      new NextRequest("http://localhost/api/v1/auth/login", {
        method: "POST",
        headers: { host: "localhost", "content-type": "application/json" },
        body: "{}",
      }),
      { params: Promise.resolve({ path: ["v1", "auth", "login"] }) },
    );
    expect(response.status).toBe(502);
    expect((await response.json()).error.message).toBe(
      "The API is temporarily unavailable.",
    );
  });
});
