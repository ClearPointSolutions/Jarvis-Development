import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

const demoSession = {
  user: {
    id: "01992f3e-7e4d-7e8a-a32d-4f82a1e1cb29",
    username: "demo-owner",
    role: "owner",
  },
  csrf_token: "synthetic-csrf-value-for-browser-fixture-only",
  idle_expires_at: "2026-09-07T17:00:00Z",
  absolute_expires_at: "2026-09-08T17:00:00Z",
};

async function installDemoSession(page: Page) {
  await page.route("**/api/v1/session", (route) =>
    route.fulfill({
      contentType: "application/json",
      headers: { "X-Jarvis-Fixture": "demo" },
      body: JSON.stringify(demoSession),
    }),
  );
}

function collectSeriousErrors(page: Page) {
  const errors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  page.on("pageerror", (error) => errors.push(error.message));
  return errors;
}

test("desktop shell is keyboard accessible, secure, and free of serious violations", async ({
  page,
}, testInfo) => {
  const seriousErrors = collectSeriousErrors(page);
  await installDemoSession(page);

  const response = await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Mission overview" }),
  ).toBeVisible();
  await expect(page.getByText("Demo fixture", { exact: true })).toBeVisible();
  await expect(page.getByText(/not runtime activity/i)).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Primary" })).toBeVisible();
  await expect(page.getByText("Foundation ready")).toBeVisible();

  const csp = response?.headers()["content-security-policy"] ?? "";
  const scriptPolicy = csp
    .split(";")
    .find((part) => part.trim().startsWith("script-src"));
  expect(scriptPolicy).toContain("'nonce-");
  expect(scriptPolicy).not.toContain("'unsafe-inline'");
  expect(scriptPolicy).not.toContain("'unsafe-eval'");
  expect(csp).toContain("frame-ancestors 'none'");
  expect(response?.headers()["x-content-type-options"]).toBe("nosniff");

  await page.keyboard.press("Tab");
  await expect(
    page.getByRole("link", { name: "Skip to main content" }),
  ).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("#main-content")).toBeFocused();

  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(
    accessibility.violations.filter(
      (violation) =>
        violation.impact === "serious" || violation.impact === "critical",
    ),
  ).toEqual([]);

  await page.screenshot({
    path: testInfo.outputPath("desktop-shell.png"),
    fullPage: true,
  });
  expect(seriousErrors).toEqual([]);
});

test("mobile navigation remains operable and labeled", async ({
  page,
}, testInfo) => {
  const seriousErrors = collectSeriousErrors(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await installDemoSession(page);
  await page.goto("/");

  const menu = page.getByRole("button", { name: "Toggle navigation" });
  await expect(menu).toHaveAttribute("aria-expanded", "false");
  await menu.click();
  await expect(menu).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByRole("navigation", { name: "Primary" })).toBeVisible();
  await page.getByRole("link", { name: "Runs" }).click();
  await expect(page.getByRole("heading", { name: "Runs" })).toBeVisible();

  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(
    accessibility.violations.filter(
      (violation) =>
        violation.impact === "serious" || violation.impact === "critical",
    ),
  ).toEqual([]);
  await page.screenshot({
    path: testInfo.outputPath("mobile-runs.png"),
    fullPage: true,
  });
  expect(seriousErrors).toEqual([]);
});

test("login posts only to the exact API route and stores no browser token", async ({
  page,
}) => {
  const seriousErrors = collectSeriousErrors(page);
  await installDemoSession(page);
  let loginBody: unknown;
  await page.route("**/api/v1/auth/login", async (route) => {
    loginBody = route.request().postDataJSON();
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(demoSession),
    });
  });

  await page.goto("/login");
  await page.getByLabel("Username").fill("demo-owner");
  await page.getByLabel("Password").fill("synthetic-browser-password");
  await page.getByRole("button", { name: "Sign in securely" }).click();
  await expect(page).toHaveURL("/");
  await expect(
    page.getByRole("heading", { name: "Mission overview" }),
  ).toBeVisible();

  expect(loginBody).toEqual({
    username: "demo-owner",
    password: "synthetic-browser-password",
  });
  expect(page.url()).not.toContain("synthetic-browser-password");
  expect(
    await page.evaluate(() => ({
      local: Object.keys(localStorage),
      session: Object.keys(sessionStorage),
      cookie: document.cookie,
    })),
  ).toEqual({ local: [], session: [], cookie: "" });
  expect(seriousErrors).toEqual([]);
});
