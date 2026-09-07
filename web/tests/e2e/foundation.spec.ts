import { expect, test } from "@playwright/test";

test("renders the Mission Control foundation", async ({ page }) => {
  const seriousErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") seriousErrors.push(message.text());
  });
  page.on("pageerror", (error) => seriousErrors.push(error.message));

  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Mission Control foundation" }),
  ).toBeVisible();
  await expect(page).toHaveTitle("Jarvis Mission Control");
  expect(seriousErrors).toEqual([]);
});
