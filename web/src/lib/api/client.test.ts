import { describe, expect, it, vi } from "vitest";

import { createBrowserApiClient } from "./client";

const session = {
  user: {
    id: "01992f3e-7e4d-7e8a-a32d-4f82a1e1cb29",
    username: "demo-owner",
    role: "owner" as const,
  },
  csrf_token: "csrf-token-with-more-than-thirty-two-characters",
  idle_expires_at: "2026-09-07T17:00:00Z",
  absolute_expires_at: "2026-09-08T17:00:00Z",
};

describe("browser API client", () => {
  it("uses same-origin credentials and keeps CSRF in memory", async () => {
    const fetchMock = vi
      .fn<(request: Request) => Promise<Response>>()
      .mockResolvedValueOnce(Response.json(session))
      .mockResolvedValueOnce(Response.json({ revoked: true }));
    const client = createBrowserApiClient(fetchMock);

    await client.getSession();
    await client.logout();

    const sessionRequest = fetchMock.mock.calls[0][0];
    const logoutRequest = fetchMock.mock.calls[1][0];
    expect(sessionRequest.credentials).toBe("same-origin");
    expect(logoutRequest.headers.get("x-csrf-token")).toBe(session.csrf_token);
    expect(logoutRequest.headers.get("content-type")).toBe("application/json");
    expect(localStorage).toHaveLength(0);
    expect(sessionStorage).toHaveLength(0);
    expect(document.cookie).toBe("");
  });

  it("sends login credentials only in a JSON request body", async () => {
    const fetchMock = vi
      .fn<(request: Request) => Promise<Response>>()
      .mockResolvedValue(Response.json(session));
    const client = createBrowserApiClient(fetchMock);

    await client.login({ username: "owner", password: "synthetic-password" });

    const request = fetchMock.mock.calls[0][0];
    expect(request.url).not.toContain("synthetic-password");
    expect(await request.json()).toEqual({
      username: "owner",
      password: "synthetic-password",
    });
    expect(request.credentials).toBe("same-origin");
  });
});
