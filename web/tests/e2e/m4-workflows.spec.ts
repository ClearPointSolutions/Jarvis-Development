import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import type {
  RegistryRecord,
  RegistryWrite,
  WorkflowDocument,
} from "@jarvis/contracts";

test.use({ trace: "off" });
test("WF-001 / WF-004 canonical editor, validation, publication, immutable history and accessibility", async ({
  page,
}, testInfo) => {
  test.skip(
    !process.env.JARVIS_BROWSER_RUN_ID,
    "requires the disposable PostgreSQL browser runner",
  );
  test.setTimeout(240000);
  page.setDefaultTimeout(15000);
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

  // Real M3 immutable registry fixtures; no provider network requests or runtime handlers.
  const fixtures = await page.evaluate(async () => {
    const session = await (await fetch("/api/v1/session")).json();
    const suffix = Date.now();
    async function create(
      name: string,
      spec: RegistryWrite["spec"],
    ): Promise<RegistryRecord> {
      const response = await fetch(`/api/v1/registry/${spec.kind}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": session.csrf_token,
        },
        body: JSON.stringify({
          key: `wf-${spec.kind}-${suffix}`,
          display_name: name,
          spec,
          idempotency_key: crypto.randomUUID(),
        }),
      });
      if (!response.ok)
        throw new Error(`Fixture ${spec.kind} rejected: ${response.status}`);
      return response.json();
    }
    const provider = await create("WF DEMO provider", {
      kind: "provider_connection",
      provider_kind: "demo",
    });
    const profile = await create("WF model", {
      kind: "model_profile",
      provider_revision_id: provider.revision_id,
      model_identifier: "demo-workflow",
      purposes: ["organizer", "developer"],
      capabilities: ["chat"],
      context_limit: 32000,
      output_limit: 4096,
    });
    const route = await create("WF model route", {
      kind: "route_policy",
      candidates: [{ profile_revision_id: profile.revision_id }],
      purposes: ["organizer", "developer"],
      required_capabilities: ["chat"],
      allow_unknown_health: true,
    });
    const worker = await create("WF worker", {
      kind: "worker",
      capabilities: ["code", "git", "tests"],
      model_binding: {
        mode: "control_plane",
        allowed_profile_revision_ids: [profile.revision_id],
      },
    });
    const retry = await create("WF retries", {
      kind: "retry_policy",
      rules: [
        {
          failure_class: "code.test_failure",
          max_retries: 2,
          initial_delay_ms: 0,
          max_delay_ms: 0,
          multiplier: 1,
          jitter: "none",
          exhaustion_action: "fail",
        },
      ],
    });
    const permission = await create("WF permissions", {
      kind: "permission_policy",
      allowed_capabilities: ["code", "git", "tests"],
      approval_required_actions: ["worker.execute"],
      git: "allow",
      shell: "allow",
    });
    return {
      worker: worker.revision_id,
      route: route.revision_id,
      retry: retry.revision_id,
      permission: permission.revision_id,
    };
  });

  const name = `Workflow acceptance ${Date.now()}`;
  await page.goto("/workflows");
  await page
    .getByRole("button", { name: "Create workflow", exact: true })
    .click();
  await expect(page.getByLabel("Workflow key")).toBeFocused();
  await page.getByLabel("Workflow key").fill(`workflow-${Date.now()}`);
  await page.getByLabel("Workflow name").fill(name);
  const inert = "<img src=x onerror=alert('workflow-xss')>";
  await page.getByLabel("Workflow description").fill(inert);
  await page.getByRole("button", { name: "Create draft", exact: true }).click();
  await expect(page.getByRole("heading", { name, exact: true })).toBeVisible();
  await page
    .getByText("Workflow settings and default policies", { exact: true })
    .click();
  await page.getByRole("button", { name: "Inspect default policies" }).click();
  await page
    .getByRole("combobox", { name: "Retry policy revision", exact: true })
    .selectOption(fixtures.retry);
  await page
    .getByRole("combobox", { name: "Permission policy revision", exact: true })
    .selectOption(fixtures.permission);
  await page.getByLabel("Timeout (seconds)", { exact: true }).fill("300");
  await page
    .getByRole("button", { name: "Add Organizer", exact: true })
    .click();
  await page.getByLabel("Summary limit").fill("1800");
  await page.getByLabel("Model route revision").selectOption(fixtures.route);
  await page.getByRole("button", { name: "Add Approval", exact: true }).click();
  await page
    .getByRole("combobox", { name: "Action type", exact: true })
    .selectOption("worker.execute");
  await page.getByRole("button", { name: "Add Worker", exact: true }).click();
  await page
    .getByRole("combobox", { name: "Worker revision", exact: true })
    .selectOption(fixtures.worker);
  await page
    .getByLabel("Required worker capabilities (comma separated)")
    .fill("code, git");
  await page.getByLabel("Model route revision").selectOption(fixtures.route);
  await page.getByLabel("Verification behavior").selectOption("required");
  await page.getByLabel("Approval action").selectOption("worker.execute");
  await page.getByLabel("Required approval node").selectOption("approval");
  await page.getByLabel("Approval expiry (seconds)").fill("600");
  await page.getByRole("button", { name: "Add Verify", exact: true }).click();
  await page
    .getByRole("combobox", { name: "Worker revision", exact: true })
    .selectOption(fixtures.worker);
  await page.getByLabel("Verification behavior").selectOption("required");
  await page.getByRole("button", { name: "Add Finalize", exact: true }).click();
  await page.getByLabel("Node label").fill("Stop on rejection");
  await page
    .getByRole("combobox", { name: "Outcome", exact: true })
    .selectOption("blocked");
  await page.getByLabel("Entry node").selectOption("organizer");

  await page
    .getByText("Keyboard outline and connections", { exact: true })
    .click();
  async function connect(from: string, to: string) {
    await page.getByLabel("Connect from").selectOption(from);
    await page.getByLabel("Connect to").selectOption(to);
    await page
      .getByRole("button", { name: "Connect nodes", exact: true })
      .click();
  }
  await connect("organizer", "approval");
  await connect("approval", "worker");
  await page.getByLabel("Edge kind").selectOption("on_result");
  await page
    .getByLabel("Condition state path")
    .selectOption("$.approval.decision");
  await page.getByLabel("Condition value", { exact: true }).fill("approved");
  await connect("approval", "finalize");
  await page.getByLabel("Edge kind").selectOption("on_result");
  await page.getByLabel("Fallback route").check();
  await connect("worker", "verify");
  await connect("verify", "finish");

  await page.getByRole("button", { name: /^Inspect edge edge_4:/ }).click();
  await page
    .getByRole("button", { name: "Disconnect edge", exact: true })
    .click();
  await expect(page.locator('.react-flow__edge[data-id="edge_4"]')).toHaveCount(
    0,
  );
  await page.getByRole("button", { name: "Fit View", exact: true }).click();
  await page
    .locator('.react-flow__node[data-id="worker"] .source')
    .dragTo(page.locator('.react-flow__node[data-id="verify"] .target'));
  await expect(page.locator('.react-flow__edge[data-id="edge_4"]')).toHaveCount(
    1,
  );

  // Invalid declarative routing is addressed to the exact canvas edge.
  await page.getByRole("button", { name: /^Inspect edge edge_2:/ }).click();
  await page.getByLabel("Use a condition").uncheck();
  await page
    .getByRole("button", { name: "Validate workflow", exact: true })
    .click();
  await expect(page.getByLabel("Workflow validation")).toContainText(
    "Result route requires a predicate",
  );
  await expect(page.locator('.react-flow__edge[data-id="edge_2"]')).toHaveClass(
    /workflow-edge-invalid/,
  );
  await page.getByLabel("Use a condition").check();
  await page
    .getByLabel("Condition state path")
    .selectOption("$.approval.decision");
  await page.getByLabel("Condition value", { exact: true }).fill("approved");

  // Backend-addressed validation errors highlight the exact node without losing edits.
  await page.getByRole("button", { name: "Add Router", exact: true }).click();
  await page
    .getByRole("button", { name: "Validate workflow", exact: true })
    .click();
  await expect(page.getByLabel("Workflow validation")).toContainText(
    "Node is unreachable",
  );
  const orphan = page.locator('.react-flow__node[data-id="router"]');
  await expect(orphan).toHaveClass(/workflow-node-invalid/);
  await page
    .getByRole("button", { name: "Node is unreachable", exact: true })
    .first()
    .click();
  await expect(page.getByLabel("Node label")).toHaveValue("Router");
  await orphan.focus();
  await page.keyboard.press("Delete");
  await expect(orphan).toHaveCount(0);

  // React Flow keyboard movement updates only the persisted presentation layout.
  const workerNode = page.locator('.react-flow__node[data-id="worker"]');
  await workerNode.focus();
  await page.keyboard.press("Enter");
  await page
    .getByRole("button", { name: "Inspect Worker (worker)", exact: true })
    .click();
  const oldX = Number(await page.getByLabel("Position x").inputValue());
  await expect(workerNode).toHaveClass(/selected/);
  await workerNode.focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByLabel("Position x")).toHaveValue(String(oldX + 5));
  await page.getByRole("button", { name: "Fit View", exact: true }).click();
  await workerNode.scrollIntoViewIfNeeded();
  const workerBox = await workerNode.boundingBox();
  if (!workerBox) throw new Error("Worker node is not visible for dragging");
  await page.mouse.move(workerBox.x + 30, workerBox.y + 25);
  await page.mouse.down();
  await page.mouse.move(workerBox.x + 60, workerBox.y + 45, { steps: 5 });
  await page.mouse.up();
  const finalWorkerX = Number(await page.getByLabel("Position x").inputValue());
  expect(finalWorkerX).toBeGreaterThan(oldX + 5);
  await page.getByRole("button", { name: "Zoom In", exact: true }).click();
  await page.getByRole("button", { name: "Zoom Out", exact: true }).click();

  await page
    .getByRole("button", { name: "Validate workflow", exact: true })
    .click();
  await expect(page.getByLabel("Workflow validation")).toContainText(
    "Workflow valid",
  );
  const publicationResponse = page.waitForResponse(
    (response) =>
      response.url().endsWith("/publish") &&
      response.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Publish version", exact: true })
    .click();
  const published = (await (
    await publicationResponse
  ).json()) as WorkflowDocument;
  expect(published.version.published).toBe(true);
  expect(
    published.version.spec.nodes.find((node) => node.id === "worker")?.policy
      ?.worker_selector?.revision_id,
  ).toBe(fixtures.worker);
  expect(
    published.version.spec.edges.find(
      (edge) => edge.from === "approval" && edge.to === "worker",
    )?.when,
  ).toMatchObject({ path: "$.approval.decision", op: "eq", value: "approved" });
  expect(published.version.layout.nodes?.worker.x).toBe(finalWorkerX);
  expect(published.version.layout.viewport?.zoom).toBeGreaterThanOrEqual(0.1);
  await expect(
    page.getByText("Published · read only", { exact: false }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Add Worker", exact: true }),
  ).toBeDisabled();
  await page.reload();
  await expect(
    page.getByText(`Version ${published.version.id}`, { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText(`Content SHA-256 ${published.version.content_hash}`, {
      exact: true,
    }),
  ).toBeVisible();
  await page
    .getByText("Keyboard outline and connections", { exact: true })
    .click();
  await page
    .getByRole("button", { name: "Inspect Worker (worker)", exact: true })
    .click();
  await expect(page.getByLabel("Node label")).toBeDisabled();
  await expect(page.getByLabel("Position x")).toBeDisabled();
  expect(await page.locator("img").count()).toBe(0);
  const desktopAxe = await new AxeBuilder({ page }).analyze();
  await page.evaluate(() => {
    (document.activeElement as HTMLElement | null)?.blur();
    window.scrollTo(0, 0);
  });
  await page.screenshot({
    path: testInfo.outputPath("m4-workflow-published.png"),
    fullPage: true,
  });
  expect(desktopAxe.violations).toEqual([]);

  // A new draft uses a new version identity; the published JSON/layout/hash remain exact.
  await page
    .getByRole("button", { name: "Create new draft", exact: true })
    .click();
  await expect(
    page.getByText("Draft · version 2", { exact: true }),
  ).toBeVisible();
  await page
    .getByText("Keyboard outline and connections", { exact: true })
    .click();
  await page
    .getByRole("button", { name: "Inspect Organizer (organizer)", exact: true })
    .click();
  await page.getByLabel("Node label").fill(inert);
  await page.getByRole("button", { name: "Save draft", exact: true }).click();
  await expect(
    page.getByRole("status").filter({ hasText: "Saved draft version 2" }),
  ).toBeVisible();
  await expect(
    page.getByRole("group", { name: new RegExp("workflow-xss") }),
  ).toBeVisible();
  expect(await page.locator("img").count()).toBe(0);
  const historical = (await page.evaluate(
    async ({ templateId, versionId }) =>
      (
        await fetch(
          `/api/v1/workflow-templates/${templateId}/versions/${versionId}`,
        )
      ).json(),
    { templateId: published.template.id, versionId: published.version.id },
  )) as WorkflowDocument;
  expect(historical.version).toEqual(published.version);
  await page
    .getByRole("button", { name: "Version history", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Version history" }),
  ).toContainText("Version 1");
  await page
    .getByRole("button", { name: "View version 1", exact: true })
    .click();
  await expect(
    page.getByText(`Content SHA-256 ${published.version.content_hash}`, {
      exact: true,
    }),
  ).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "Fit View", exact: true }).click();
  const mobileAxe = await new AxeBuilder({ page }).analyze();
  expect(mobileAxe.violations).toEqual([]);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.evaluate(() => {
    (document.activeElement as HTMLElement | null)?.blur();
    window.scrollTo(0, 0);
  });
  await page.screenshot({
    path: testInfo.outputPath("m4-workflow-mobile.png"),
    fullPage: true,
  });
  expect(serious).toEqual([]);
});
