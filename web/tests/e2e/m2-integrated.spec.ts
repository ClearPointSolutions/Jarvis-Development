import { execFileSync } from "node:child_process";
import path from "node:path";
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

test.use({ trace: "off" });

test("M2 real auth, CSRF, durable SSE replay, projection and revocation", async ({
  page,
  context,
}) => {
  test.skip(
    !process.env.JARVIS_BROWSER_RUN_ID,
    "requires disposable database runner",
  );
  const runId = process.env.JARVIS_BROWSER_RUN_ID!;
  const serious: string[] = [];
  page.on("pageerror", (error) => serious.push(error.message));
  page.on("console", (message) => {
    if (
      message.type() === "error" &&
      !message.text().includes("Failed to load resource")
    )
      serious.push(message.text());
  });
  const initial = await context.request.get("/api/v1/session");
  expect(initial.status(), await initial.text()).toBe(401);
  await page.goto("/login");
  await expect(page.getByLabel("Username")).toBeVisible();
  async function login() {
    await page.getByLabel("Username").fill("browser-owner");
    await page
      .getByLabel("Password", { exact: true })
      .fill(process.env.JARVIS_BROWSER_PASSWORD!);
    await page.getByRole("button", { name: "Sign in securely" }).click();
    await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
  }
  await login();
  const sessionCookie = (await context.cookies()).find(
    (cookie) => cookie.name === "jarvis_session",
  )!;
  expect(sessionCookie.httpOnly).toBe(true);
  expect(sessionCookie.secure).toBe(true);
  expect(sessionCookie.sameSite).toBe("Strict");
  expect(sessionCookie.path).toBe("/api/v1");
  expect(
    await page.evaluate(() => [localStorage.length, sessionStorage.length]),
  ).toEqual([0, 0]);
  // Real mutation: missing CSRF fails; correct session token and origin succeed.
  const csrfResults = await page.evaluate(async () => {
    const session = await (await fetch("/api/v1/session")).json();
    const bad = await fetch("/api/v1/auth/logout", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    const good = await fetch("/api/v1/auth/logout", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": session.csrf_token,
      },
      body: "{}",
    });
    return [bad.status, good.status];
  });
  expect(csrfResults).toEqual([403, 200]);
  await page.goto("/login");
  await login();
  const noOrigin = await context.request.post("/api/v1/auth/logout", {
    data: {},
  });
  expect(noOrigin.status()).toBe(403);
  await page.goto(`/runs/${runId}`);
  await expect(
    page.getByRole("heading", { name: "Run event monitor" }),
  ).toBeVisible();
  function produce(): { position: number; sequence: number } {
    return JSON.parse(
      execFileSync(
        process.env.JARVIS_BROWSER_PYTHON!,
        ["-m", "scripts.m2_browser_fixture"],
        { cwd: path.resolve(".."), env: process.env, encoding: "utf8" },
      ),
    );
  }
  // EventSource proves real authenticated browser transport. It is explicitly closed
  // while events commit, then replayed by the standard Last-Event-ID header below.
  await page.evaluate((id) => {
    const state = window as unknown as {
      m2stream: EventSource;
      m2events: { global_position: number }[];
    };
    state.m2events = [];
    state.m2stream = new EventSource(
      `/api/v1/runs/${id}/events/stream?after=0`,
    );
    state.m2stream.addEventListener("jarvis.event", (event) =>
      state.m2events.push(JSON.parse((event as MessageEvent).data)),
    );
  }, runId);
  const first = produce();
  await expect
    .poll(() =>
      page.evaluate(() =>
        (
          window as unknown as { m2events: { global_position: number }[] }
        ).m2events.map((event) => event.global_position),
      ),
    )
    .toContain(first.position);
  await page.evaluate(() =>
    (window as unknown as { m2stream: EventSource }).m2stream.close(),
  );
  await expect(page.getByTestId("run-sequence")).toHaveText(
    String(first.sequence),
  );
  await context.setOffline(true);
  const second = produce();
  const third = produce();
  await context.setOffline(false);
  const replay = await page.evaluate(
    async ({ id, cursor, last }) => {
      const controller = new AbortController();
      const response = await fetch(`/api/v1/runs/${id}/events/stream?after=0`, {
        headers: { "Last-Event-ID": String(cursor) },
        signal: controller.signal,
      });
      const reader = response.body!.getReader();
      let text = "";
      while (!text.includes(`id: ${last}\n`)) {
        const chunk = await reader.read();
        if (chunk.done) break;
        text += new TextDecoder().decode(chunk.value);
      }
      controller.abort();
      return text;
    },
    { id: runId, cursor: first.position, last: third.position },
  );
  expect(replay).toContain(`id: ${second.position}\n`);
  expect(replay).toContain(`id: ${third.position}\n`);
  expect(replay).not.toContain(`id: ${first.position}\n`);
  expect(replay).not.toContain("synthetic-" + "event-canary");
  const snapshot = await page.evaluate(async (id) => {
    const response = await fetch(`/api/v1/runs/${id}/event-snapshot`);
    if (!response.ok) throw new Error(`Snapshot failed: ${response.status}`);
    return response.json();
  }, runId);
  expect(snapshot.last_event_position).toBe(third.position);
  expect(snapshot.last_run_sequence).toBe(third.sequence);
  await expect(page.getByTestId("run-sequence")).toHaveText(
    String(third.sequence),
  );
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await expect(page.locator("body")).not.toContainText(
    "synthetic-" + "event-canary",
  );
  await page.screenshot({
    path: "../.worktrees/m2-browser.png",
    fullPage: true,
  });
  const activeCookie = (await context.cookies()).find(
    (cookie) => cookie.name === "jarvis_session",
  )!;
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByLabel("Username")).toBeVisible();
  const revoked = { Cookie: `jarvis_session=${activeCookie.value}` };
  expect(
    (
      await context.request.get(`/api/v1/runs/${runId}/events`, {
        headers: revoked,
      })
    ).status(),
  ).toBe(401);
  expect(
    (
      await context.request.get(`/api/v1/runs/${runId}/events/stream`, {
        headers: revoked,
      })
    ).status(),
  ).toBe(401);
  expect(serious).toEqual([]);
});
