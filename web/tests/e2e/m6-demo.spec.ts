import { existsSync, unlinkSync, writeFileSync } from "node:fs";
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

test.use({ trace: "off" });
test("M6 real demo, retry, durable decision, restart, artifacts and history", async ({
  page,
}) => {
  test.skip(!process.env.JARVIS_M6_E2E, "requires scripts/demo.sh --e2e");
  test.setTimeout(360000);
  page.setDefaultTimeout(15000);
  const serious: string[] = [];
  const external: string[] = [];
  page.on("pageerror", (error) => serious.push(error.message));
  page.on("console", (message) => {
    if (
      message.type() === "error" &&
      !message.text().includes("Failed to load resource")
    )
      serious.push(message.text());
  });
  await page.context().route("**/*", (route) => {
    const url = new URL(route.request().url());
    if (url.origin !== "http://127.0.0.1:3000") {
      external.push(url.origin);
      return route.abort();
    }
    return route.continue();
  });
  await page.goto("/login");
  await page.getByLabel("Username").fill("demo-owner");
  await page
    .getByLabel("Password", { exact: true })
    .fill(process.env.JARVIS_BROWSER_PASSWORD!);
  await page.getByRole("button", { name: "Sign in securely" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
  await page.goto("/workers");
  await expect(
    page.getByRole("heading", { name: "DEMO worker", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Edit DEMO worker", exact: true })
    .click();
  await page.getByLabel("Display name").fill("DEMO worker");
  await page
    .getByRole("button", { name: "Save revision", exact: true })
    .click();
  await expect(
    page
      .getByRole("status")
      .filter({ hasText: "Saved DEMO worker, revision 2" }),
  ).toBeVisible();
  await page.goto("/routing");
  await expect(
    page.getByRole("heading", { name: "DEMO route", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Edit DEMO route", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Save revision", exact: true })
    .click();
  await expect(
    page
      .getByRole("status")
      .filter({ hasText: "Saved DEMO route, revision 2" }),
  ).toBeVisible();
  await page.goto("/workflows");
  await expect(
    page.getByText("DEMO deterministic development", { exact: true }).first(),
  ).toBeVisible();
  await page
    .getByRole("button", {
      name: "Open DEMO deterministic development",
      exact: true,
    })
    .click();
  await page
    .getByRole("button", { name: "Create new draft", exact: true })
    .click();
  await expect(
    page.getByText("Draft · version 2", { exact: true }),
  ).toBeVisible();
  await page
    .getByText("Keyboard outline and connections", { exact: true })
    .click();
  await page.getByRole("button", { name: /Inspect DEMO organizer/ }).click();
  await page.getByLabel("Node label").fill("DEMO Organizer objective");
  await page.getByRole("button", { name: "Save draft", exact: true }).click();
  await expect(
    page.getByRole("status").filter({ hasText: "Saved draft version 2" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Validate workflow", exact: true })
    .click();
  await expect(page.getByLabel("Workflow validation")).toContainText(
    "Workflow valid",
  );
  await page
    .getByRole("button", { name: "Publish version", exact: true })
    .click();
  await expect(
    page.getByText("Published · read only", { exact: false }),
  ).toBeVisible();
  await page.goto("/runs");
  await page
    .getByLabel("Project name", { exact: true })
    .fill("DEMO browser project");
  await page.getByLabel("Project slug").fill("demo-browser-project");
  await page
    .getByRole("button", { name: "Create project", exact: true })
    .click();
  await page
    .getByLabel("Project", { exact: true })
    .selectOption({ label: "DEMO browser project" });
  await page
    .getByLabel("Published workflow")
    .selectOption({ label: "DEMO deterministic development" });
  await page
    .getByLabel("Objective", { exact: true })
    .fill("Build a greeting fixture");
  const queued = page.waitForResponse(
    (r) => r.url().endsWith("/jobs") && r.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Start run", exact: true }).click();
  const response = await queued;
  expect(response.status()).toBe(202);
  expect((await response.json()).status).toBe("queued");
  await expect(page).toHaveURL(/\/runs\/[^/]+$/);
  const runUrl = page.url();
  await expect(
    page.getByRole("region", { name: "Task progress" }),
  ).toContainText("2 of 2 tasks completed", { timeout: 60000 });
  await expect(
    page.getByRole("region", { name: "Retry history" }),
  ).toContainText("code.test_failure: 1/2");
  await expect(
    page.getByRole("button", { name: "Approve demo publication" }),
  ).toBeEnabled();
  const before = Number(await page.getByTestId("run-sequence").innerText());
  async function restart() {
    const ack = process.env.JARVIS_M6_ACK!;
    if (existsSync(ack)) unlinkSync(ack);
    writeFileSync(process.env.JARVIS_M6_CONTROL!, "restart");
    await expect.poll(() => existsSync(ack), { timeout: 20000 }).toBe(true);
    await expect
      .poll(
        async () => {
          try {
            return (await page.request.get("/api/v1/session")).status();
          } catch {
            return 0;
          }
        },
        { timeout: 20000 },
      )
      .toBe(200);
  }
  await restart();
  await page.getByRole("button", { name: "Reconnect and refresh" }).click();
  await expect(page.getByTestId("run-status")).toHaveText("approval_required");
  expect(
    Number(await page.getByTestId("run-sequence").innerText()),
  ).toBeGreaterThanOrEqual(before);
  await page.getByRole("button", { name: "Approve demo publication" }).click();
  await expect(page.getByTestId("run-status")).toHaveText("completed", {
    timeout: 60000,
  });
  await restart();
  await page.goto(runUrl);
  await expect(page.getByTestId("run-status")).toHaveText("completed");
  await expect(
    page.getByRole("region", { name: "Persisted run events" }),
  ).toContainText("git.pr_created", { timeout: 30000 });
  await expect(
    page.getByRole("region", { name: "Runtime workflow" }),
  ).toContainText("succeeded");
  await expect(
    page.getByRole("region", { name: "Task progress" }),
  ).toContainText("Attempt 1: failed; Attempt 2: succeeded");
  const artifact = page
    .getByRole("region", { name: "Run artifacts" })
    .getByRole("link")
    .first();
  await expect(artifact).toBeVisible();
  expect(
    (await page.request.get((await artifact.getAttribute("href"))!)).status(),
  ).toBe(200);
  const findings = await new AxeBuilder({ page }).analyze();
  expect(findings.violations).toEqual([]);
  await page.screenshot({
    path: "test-results/m6-completed.png",
    fullPage: true,
  });
  async function signature() {
    const id = new URL(page.url()).pathname.split("/").at(-1)!;
    const data = await (
      await page.request.get(`/api/v1/runs/${id}/events?limit=1000`)
    ).json();
    return data.items.map(
      (e: { type: string; data: Record<string, unknown> }) => [
        e.type,
        e.data.from ?? null,
        e.data.to ?? null,
        e.data.failure_class ?? null,
      ],
    );
  }
  const canonical = await signature();
  for (const scenario of ["canonical", "infrastructure", "reject"]) {
    await page.goto("/runs");
    await page
      .getByLabel("Project", { exact: true })
      .selectOption({ label: "DEMO browser project" });
    await page
      .getByLabel("Published workflow")
      .selectOption({ label: "DEMO deterministic development" });
    await page
      .getByLabel("DEMO scenario")
      .selectOption(scenario === "reject" ? "canonical" : scenario);
    await page
      .getByLabel("Objective", { exact: true })
      .fill("Build a greeting fixture");
    await page.getByRole("button", { name: "Start run", exact: true }).click();
    await expect(
      page.getByRole("button", { name: "Approve demo publication" }),
    ).toBeEnabled({ timeout: 60000 });
    if (scenario === "canonical") {
      await restart();
      await page.getByRole("button", { name: "Reconnect and refresh" }).click();
      await expect(page.getByTestId("run-status")).toHaveText(
        "approval_required",
      );
    }
    if (scenario === "infrastructure") {
      await expect(
        page.getByRole("region", { name: "Retry history" }),
      ).toContainText("infrastructure.worker_transport: 1/2");
      await expect(
        page.getByRole("region", { name: "Retry history" }),
      ).not.toContainText("code.test_failure");
    }
    await page
      .getByRole("button", {
        name:
          scenario === "reject"
            ? "Reject demo publication"
            : "Approve demo publication",
      })
      .click();
    await expect(page.getByTestId("run-status")).toHaveText(
      scenario === "reject" ? "cancelled" : "completed",
      { timeout: 60000 },
    );
    if (scenario === "canonical") {
      await restart();
      await page.reload();
      await expect(page.getByTestId("run-status")).toHaveText("completed");
      expect(await signature()).toEqual(canonical);
    }
    if (scenario === "reject")
      expect(
        (await signature()).filter((e: unknown[]) => e[0] === "git.pr_created"),
      ).toEqual([]);
  }
  expect(serious).toEqual([]);
  expect(external).toEqual([]);
});
