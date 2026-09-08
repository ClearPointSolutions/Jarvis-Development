import { type NextRequest } from "next/server";
import { request as httpRequest, type IncomingMessage } from "node:http";
import { request as httpsRequest } from "node:https";
import { Readable } from "node:stream";
import type { ApiErrorResponse } from "@jarvis/contracts";

const MAX_REQUEST_BYTES = 65_536;
class RequestTooLarge extends Error {}

async function boundedBody(
  request: NextRequest,
  maximum = MAX_REQUEST_BYTES,
): Promise<ArrayBuffer | undefined> {
  if (!request.body) return undefined;
  const reader = request.body.getReader();
  const output = new Uint8Array(maximum);
  let length = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) return output.slice(0, length).buffer;
      if (value.byteLength > maximum - length) {
        await reader.cancel();
        throw new RequestTooLarge();
      }
      output.set(value, length);
      length += value.byteLength;
    }
  } finally {
    reader.releaseLock();
  }
}

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// This is the same-origin transport boundary, never an alternate authorization
// layer. FastAPI validates the original Host, Origin, cookie, CSRF and resource.
async function forward(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) {
  const requestId = crypto.randomUUID();
  const failure = (status: number) =>
    Response.json(
      {
        error: {
          code: status === 413 ? "request.too_large" : "api.unavailable",
          message:
            status === 413
              ? "The request exceeds the allowed size."
              : "The API is temporarily unavailable.",
          request_id: requestId,
          details: {},
        },
      } satisfies ApiErrorResponse,
      { status, headers: { "Cache-Control": "no-store" } },
    );
  const apiUrl = process.env.JARVIS_API_URL;
  if (!apiUrl) return failure(503);
  const { path } = await context.params;
  if (path.some((segment) => segment === "." || segment === ".."))
    return failure(400);
  const target = new URL(
    `${apiUrl.replace(/\/$/, "")}/api/${path.map(encodeURIComponent).join("/")}`,
  );
  target.search = request.nextUrl.search;
  const headers = new Headers();
  for (const name of [
    "accept",
    "content-type",
    "cookie",
    "origin",
    "x-csrf-token",
    "last-event-id",
    "sec-fetch-site",
  ]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  // Do not forward user-controlled X-Forwarded-* headers. The API compares this
  // Host directly to its configured public origin, including the port.
  headers.set("host", request.headers.get("host") ?? "");
  headers.set("x-request-id", requestId);
  try {
    const body =
      request.method === "GET" || request.method === "HEAD"
        ? undefined
        : await boundedBody(
            request,
            path[0] === "v1" && path[1] === "workflow-templates"
              ? 1_048_576
              : MAX_REQUEST_BYTES,
          );
    if (body) headers.set("content-length", String(body.byteLength));
    const upstream = await new Promise<IncomingMessage>((resolve, reject) => {
      // Native HTTP preserves the explicit Host. Node fetch may replace it with
      // the transport destination, which breaks the API's public-origin guard.
      const transport =
        target.protocol === "https:" ? httpsRequest : httpRequest;
      let incoming: IncomingMessage | undefined;
      const outgoing = transport(
        target,
        { method: request.method, headers: Object.fromEntries(headers) },
        (response) => {
          incoming = response;
          response.once("close", cleanup);
          resolve(response);
        },
      );
      function abort() {
        outgoing.destroy(new Error("Client disconnected"));
        incoming?.destroy();
      }
      function cleanup() {
        request.signal.removeEventListener("abort", abort);
      }
      outgoing.once("error", (error) => {
        cleanup();
        reject(error);
      });
      request.signal.addEventListener("abort", abort, { once: true });
      if (request.signal.aborted) {
        abort();
        return;
      }
      outgoing.end(body ? Buffer.from(body) : undefined);
    });
    const outgoing = new Headers();
    for (const [name, value] of Object.entries(upstream.headers)) {
      if (
        value === undefined ||
        [
          "connection",
          "keep-alive",
          "transfer-encoding",
          "content-length",
        ].includes(name)
      )
        continue;
      for (const item of Array.isArray(value) ? value : [value])
        outgoing.append(name, item);
    }
    outgoing.set("Cache-Control", "no-store");
    const status = upstream.statusCode ?? 502;
    if ([204, 205, 304].includes(status) || request.method === "HEAD") {
      upstream.resume();
      return new Response(null, { status, headers: outgoing });
    }
    const source = Readable.toWeb(upstream) as ReadableStream<Uint8Array>;
    if (!outgoing.get("content-type")?.startsWith("text/event-stream"))
      return new Response(source, { status, headers: outgoing });
    // An API restart ends this SSE connection. EventSource reconnects with its
    // durable cursor; do not turn the expected transport closure into a page error.
    const reader = source.getReader();
    const stream = new ReadableStream<Uint8Array>({
      async pull(controller) {
        try {
          const next = await reader.read();
          if (next.done) controller.close();
          else controller.enqueue(next.value);
        } catch {
          controller.close();
        }
      },
      cancel() {
        return reader.cancel();
      },
    });
    return new Response(stream, { status, headers: outgoing });
  } catch (error) {
    return failure(error instanceof RequestTooLarge ? 413 : 502);
  }
}
export const GET = forward;
export const POST = forward;
export const PUT = forward;
