import AxeBuilder from "@axe-core/playwright";
import path from "node:path";
import { expect, test } from "@playwright/test";

test.use({ trace: "off" });
test("M3 real registry forms, immutable revisions, route preview and accessibility", async ({
  page,
}, testInfo) => {
  test.skip(
    !process.env.JARVIS_BROWSER_RUN_ID,
    "requires disposable database runner",
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
  const suffix = Date.now().toString();
  let sequence = 0;
  async function create(path: string, kind: string, name: string) {
    await page.goto(path);
    await page.getByRole("button", { name: `Create ${kind}` }).click();
    await page
      .getByLabel("Stable key")
      .fill(`browser-${kind.replaceAll(" ", "-")}-${suffix}-${sequence++}`);
    await page.getByLabel("Display name").fill(name);
  }
  async function save(name: string, revision = 1) {
    await page.getByRole("button", { name: "Save revision" }).click();
    await expect(
      page
        .getByRole("status")
        .filter({ hasText: `Saved ${name}, revision ${revision}.` }),
    ).toBeVisible();
  }
  await create("/providers", "provider connection", "Browser DEMO provider");
  await expect(page.getByLabel("Replace secret reference")).toHaveValue("");
  await save("Browser DEMO provider");
  await page
    .getByRole("button", { name: "Validate Browser DEMO provider" })
    .click();
  await expect(page.getByLabel("Validation result")).toContainText(
    "No live network probe performed",
  );
  await page
    .getByRole("button", { name: "Edit Browser DEMO provider" })
    .click();
  await expect(page.getByLabel("Replace secret reference")).toHaveValue("");
  await page.getByRole("button", { name: "Cancel", exact: true }).click();

  await create("/providers", "provider connection", "Browser local Ollama");
  await page.getByLabel("Provider type").selectOption("ollama");
  await page
    .getByLabel("Endpoint", { exact: true })
    .fill(process.env.JARVIS_BROWSER_PROVIDER_ENDPOINT!);
  const opaqueReference = "secret:browser-m3-synthetic";
  await page.getByLabel("Replace secret reference").fill(opaqueReference);
  const providerResponse = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/v1/registry/provider_connection") &&
      response.request().method() === "POST",
  );
  await save("Browser local Ollama");
  const providerBody = await (await providerResponse).text();
  expect(providerBody).not.toContain(opaqueReference);
  expect(providerBody).not.toContain("secret_ref");
  await expect(
    page.getByText("Configured · masked", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Edit Browser local Ollama" }).click();
  await expect(page.getByLabel("Replace secret reference")).toHaveValue("");
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  const rejectedCanary = await page.evaluate(async (endpoint) => {
    const session = await (await fetch("/api/v1/session")).json();
    const canary = "sk-proj-" + "synthetic_browser_canary_".repeat(4);
    const response = await fetch("/api/v1/registry/provider_connection", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": session.csrf_token,
      },
      body: JSON.stringify({
        key: "browser-rejected-canary",
        display_name: canary,
        idempotency_key: crypto.randomUUID(),
        spec: {
          kind: "provider_connection",
          provider_kind: "ollama",
          base_url: endpoint,
        },
      }),
    });
    return {
      status: response.status,
      leaked: (await response.text()).includes(canary),
    };
  }, process.env.JARVIS_BROWSER_PROVIDER_ENDPOINT!);
  expect(rejectedCanary).toEqual({ status: 422, leaked: false });

  await create("/models", "model profile", "Browser utility model");
  await page
    .getByLabel("Provider revision", { exact: true })
    .selectOption({ label: "Browser DEMO provider · revision 1" });
  await page.getByLabel("Model identifier").fill("demo-utility");
  await page.getByLabel("Output token limit").fill("40000");
  await page.getByRole("button", { name: "Save revision" }).click();
  await expect(
    page.getByRole("alert").filter({ hasText: "must not exceed" }),
  ).toContainText("must not exceed");
  await page.getByLabel("Output token limit").fill("4096");
  await save("Browser utility model");
  await expect(
    page
      .getByRole("article")
      .filter({
        has: page.getByRole("heading", {
          name: "Browser utility model",
          exact: true,
        }),
      })
      .getByText("Unknown", { exact: true }),
  ).toBeVisible();

  await create("/workers", "worker", "Browser worker");
  await page.getByLabel("Capabilities (comma separated)").fill("code, review");
  await page.getByLabel("Maximum concurrency").fill("2");
  await save("Browser worker");
  await page.getByRole("button", { name: "Edit Browser worker" }).click();
  await page.getByLabel("Display name").fill("Browser worker revised");
  await page.getByLabel("Enabled", { exact: true }).uncheck();
  await save("Browser worker revised", 2);
  await page
    .getByRole("button", { name: "History Browser worker revised" })
    .click();
  const history = page.getByRole("region", { name: "Revision history" });
  await expect(
    history.locator("summary").filter({ hasText: "Revision 1" }),
  ).toContainText("Browser worker · Enabled");
  await expect(
    history.locator("summary").filter({ hasText: "Revision 2" }),
  ).toContainText("Disabled");
  await page.getByRole("button", { name: "Close history" }).click();

  await create("/routing", "route policy", "Browser utility route");
  await page
    .getByLabel("Add candidate")
    .selectOption({ label: "Browser utility model · revision 1" });
  await page.getByLabel("Required capabilities (comma separated)").fill("chat");
  await page.getByLabel("Allow unknown health").check();
  await save("Browser utility route");
  const browserRoute = page.getByRole("article").filter({
    has: page.getByRole("heading", {
      name: "Browser utility route",
      exact: true,
    }),
  });
  await browserRoute
    .getByText("Deterministic resolution preview", { exact: true })
    .click();
  await browserRoute.getByRole("button", { name: "Resolve route" }).click();
  await expect(
    browserRoute.getByRole("heading", { name: /Decision: allow/ }),
  ).toBeVisible();
  await browserRoute
    .getByLabel("Data classification")
    .selectOption("restricted");
  await browserRoute.getByRole("button", { name: "Resolve route" }).click();
  await expect(
    browserRoute.getByRole("heading", { name: /Decision: deny/ }),
  ).toBeVisible();
  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(accessibility.violations).toEqual([]);
  await page.evaluate(() => {
    (document.activeElement as HTMLElement | null)?.blur();
    window.scrollTo(0, 0);
  });
  await page.screenshot({
    path: testInfo.outputPath("m3-routing.png"),
    fullPage: true,
  });
  if (!process.env.CI)
    await page.screenshot({
      path: path.resolve("../.worktrees/m3-registry.png"),
      fullPage: true,
    });

  await create("/policies", "retry policy", "Browser retries");
  await page.getByRole("button", { name: "Add retry rule" }).click();
  await save("Browser retries");
  await page
    .getByRole("button", { name: "Permission policies", exact: true })
    .click();
  await page.getByRole("button", { name: "Create permission policy" }).click();
  await page.getByLabel("Stable key").fill(`browser-permission-${suffix}`);
  await page.getByLabel("Display name").fill("Browser permissions");
  await expect(page.getByLabel("unknown action")).toHaveValue("deny");
  await save("Browser permissions");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/workers");
  await page
    .getByRole("button", { name: "Edit Browser worker revised" })
    .click();
  await expect(page.getByLabel("Stable key")).toBeFocused();
  const mobileAxe = await new AxeBuilder({ page }).analyze();
  expect(mobileAxe.violations).toEqual([]);
  await page.evaluate(() => {
    (document.activeElement as HTMLElement | null)?.blur();
    window.scrollTo(0, 0);
  });
  await page.screenshot({
    path: testInfo.outputPath("m3-worker-mobile.png"),
    fullPage: true,
  });
  expect(await page.locator("body").innerText()).not.toContain(
    process.env.JARVIS_BROWSER_PASSWORD!,
  );
  expect(serious).toEqual([]);
});
