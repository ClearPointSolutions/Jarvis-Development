import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

test.use({ trace: "off" });
test("M8 real runtime evidence, sealed integration and authorized downloads", async ({
  page,
}) => {
  test.skip(
    !process.env.JARVIS_M8_RUN_ID,
    "requires PostgreSQL repository verification",
  );
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
  await page.goto(`/runs/${process.env.JARVIS_M8_RUN_ID}`);
  const panel = page.getByRole("region", {
    name: "Repository verification and review",
  });
  await expect(
    panel.getByText("review.completed", { exact: false }),
  ).toBeVisible();
  await expect(
    panel.getByText("git.integration_completed", { exact: false }),
  ).toBeVisible();
  const artifact = panel.getByRole("link", {
    name: "Sealed integration snapshot",
    exact: true,
  });
  await expect(artifact).toBeVisible();
  // Chromium carries the Secure, HttpOnly cookie on the loopback test origin;
  // Playwright's separate Node request transport does not share that exception.
  const response = await page.evaluate(
    async (href) => {
      const result = await fetch(href!);
      return { status: result.status, body: await result.json() };
    },
    await artifact.getAttribute("href"),
  );
  expect(response.status, JSON.stringify(response.body)).toBe(200);
  const snapshot = response.body;
  expect(snapshot.content.git_status).toBe("clean");
  expect(snapshot.content.head_sha).toMatch(/^[a-f0-9]{40}$/);
  await page.reload();
  await expect(artifact).toBeVisible();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  expect(serious).toEqual([]);
});
