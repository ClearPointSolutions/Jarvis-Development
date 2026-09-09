import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

test.use({ trace: "off" });
test("M5 real enqueue, pause, same-thread resume, cancel and accessible acknowledgements", async ({
  page,
}) => {
  test.skip(
    !process.env.JARVIS_BROWSER_RUN_ID,
    "requires disposable PostgreSQL runner",
  );
  test.setTimeout(120000);
  const serious: string[] = [];
  page.on("pageerror", (error) => serious.push(error.message));
  page.on("console", (message) => {
    if (
      message.type() === "error" &&
      !message.text().includes("Failed to load resource")
    )
      serious.push(message.text());
  });
  await page.goto("/login");
  await page.getByLabel("Username").fill("browser-owner");
  await page
    .getByLabel("Password", { exact: true })
    .fill(process.env.JARVIS_BROWSER_PASSWORD!);
  await page.getByRole("button", { name: "Sign in securely" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
  const version = await page.evaluate(async () => {
    const session = await (await fetch("/api/v1/session")).json();
    const headers = {
      "Content-Type": "application/json",
      "X-CSRF-Token": session.csrf_token,
    };
    async function write(path: string, body: unknown, method = "POST") {
      const response = await fetch(`/api/v1/workflow-templates${path}`, {
        method,
        headers,
        body: JSON.stringify(body),
      });
      if (!response.ok)
        throw new Error(`Workflow fixture rejected ${response.status}`);
      return response.json();
    }
    let doc = await write("", {
      key: `runtime-${Date.now()}`,
      name: "M5 runtime boundaries",
      idempotency_key: crypto.randomUUID(),
    });
    const spec = doc.version.spec;
    const final = spec.nodes[0];
    async function registry(kind: string, data: object) {
      const response = await fetch(`/api/v1/registry/${kind}`, {
        method: "POST",
        headers,
        body: JSON.stringify({
          key: `m5-${kind}-${Date.now()}`,
          display_name: `M5 ${kind}`,
          spec: { kind, ...data },
          idempotency_key: crypto.randomUUID(),
        }),
      });
      if (!response.ok)
        throw new Error(`Registry fixture rejected ${response.status}`);
      return (await response.json()).revision_id;
    }
    const retry = await registry("retry_policy", { rules: [] });
    const permission = await registry("permission_policy", {
      allowed_capabilities: ["code", "git", "tests"],
      git: "allow",
      shell: "allow",
    });
    const worker = await registry("worker", {
      capabilities: ["code", "git", "tests"],
    });
    spec.defaults = {
      timeout_seconds: 60,
      retry_policy_ref: retry,
      permission_policy_ref: permission,
      worker_selector: { revision_id: worker },
    };
    spec.nodes = [
      {
        id: "browser_work",
        type: "worker",
        label: "Controlled browser effect",
        config: {},
      },
      final,
    ];
    spec.entrypoint = "browser_work";
    spec.edges = [
      {
        id: "finish_effect",
        from: "browser_work",
        to: final.id,
        kind: "always",
      },
    ];
    doc = await write(
      `/${doc.template.id}/draft`,
      {
        spec,
        layout: {},
        expected_version: doc.template.version,
        idempotency_key: crypto.randomUUID(),
      },
      "PUT",
    );
    doc = await write(`/${doc.template.id}/publish`, {
      expected_version: doc.template.version,
      idempotency_key: crypto.randomUUID(),
    });
    return doc.version.id as string;
  });
  await page.goto("/runs");
  await page.getByLabel("Project name").fill("M5 browser project");
  await page.getByLabel("Project slug").fill(`m5-${Date.now()}`);
  await page
    .getByRole("button", { name: "Create project", exact: true })
    .click();
  await expect(page.getByRole("status")).toContainText("Project created");
  await page
    .getByLabel("Project", { exact: true })
    .selectOption({ label: "M5 browser project" });
  await page.getByLabel("Published workflow").selectOption(version);
  await page.getByLabel("Execution mode").selectOption("real");
  await page
    .getByLabel("Objective")
    .fill("Observe durable local control boundaries");
  await page.getByRole("button", { name: "Start run", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Pause", exact: true }),
  ).toBeEnabled();
  const original = await page.evaluate(async () =>
    (await fetch(`/api/v1${location.pathname}`)).json(),
  );
  await page.getByRole("button", { name: "Pause", exact: true }).click();
  await expect(page.getByTestId("run-status")).toHaveText("paused", {
    timeout: 30000,
  });
  await expect(page.getByLabel("Command acknowledgements")).toContainText(
    "pause — applied",
  );
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page.screenshot({
    path: "../.worktrees/m5-paused.png",
    fullPage: true,
  });
  await page.reload();
  await expect(
    page.getByRole("button", { name: "Resume", exact: true }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "Resume", exact: true }).click();
  await expect(page.getByTestId("run-status")).toHaveText("completed", {
    timeout: 30000,
  });
  const completed = await page.evaluate(async () =>
    (await fetch(`/api/v1${location.pathname}`)).json(),
  );
  expect(completed.thread_id).toBe(original.thread_id);
  expect(completed.last_run_sequence).toBeGreaterThan(
    original.last_run_sequence,
  );
  const next = await page.evaluate(
    async ({ project, workflow }) => {
      const session = await (await fetch("/api/v1/session")).json();
      const response = await fetch(`/api/v1/projects/${project}/jobs`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": session.csrf_token,
        },
        body: JSON.stringify({
          workflow_version_id: workflow,
          objective: "Cancel at durable boundary",
          mode: "real",
          idempotency_key: crypto.randomUUID(),
        }),
      });
      if (response.status !== 202) throw new Error("Run enqueue failed");
      return response.json();
    },
    { project: original.project_id, workflow: version },
  );
  await page.goto(`/runs/${next.id}`);
  const cancelledReceipt = page.waitForResponse(
    (response) =>
      response.url().endsWith(`/runs/${next.id}/commands`) &&
      response.status() === 202,
  );
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await cancelledReceipt;
  await expect(page.getByTestId("run-status")).toHaveText("cancelled", {
    timeout: 30000,
  });
  await expect(
    page.getByRole("button", { name: "Resume", exact: true }),
  ).toBeDisabled();
  await page.setViewportSize({ width: 390, height: 844 });
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page.screenshot({
    path: "../.worktrees/m5-cancelled-mobile.png",
    fullPage: true,
  });
  expect(serious).toEqual([]);
});
