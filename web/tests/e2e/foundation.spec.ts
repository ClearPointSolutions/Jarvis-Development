import { expect, test } from "@playwright/test";

test("renders the Mission Control foundation", async ({ page }) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Mission Control foundation" }),
  ).toBeVisible();
  await expect(page).toHaveTitle("Jarvis Mission Control");
});
