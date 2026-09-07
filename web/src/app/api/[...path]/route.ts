import { type NextRequest } from "next/server";

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
          code: "api.unavailable",
          message: "The API is temporarily unavailable.",
          request_id: requestId,
          details: {},
        },
      },
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
  ]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  // Do not forward user-controlled X-Forwarded-* headers. The API compares this
  // Host directly to its configured public origin, including the port.
  headers.set("host", request.headers.get("host") ?? "");
  headers.set("x-request-id", requestId);
  try {
    const upstream = await fetch(target, {
      method: request.method,
      headers,
      body:
        request.method === "GET" || request.method === "HEAD"
          ? undefined
          : await request.arrayBuffer(),
      redirect: "manual",
      cache: "no-store",
      signal: request.signal,
    });
    const outgoing = new Headers(upstream.headers);
    for (const name of [
      "connection",
      "keep-alive",
      "transfer-encoding",
      "content-encoding",
      "content-length",
    ])
      outgoing.delete(name);
    outgoing.set("Cache-Control", "no-store");
    return new Response(upstream.body, {
      status: upstream.status,
      headers: outgoing,
    });
  } catch {
    return failure(502);
  }
}
export const GET = forward;
export const POST = forward;
