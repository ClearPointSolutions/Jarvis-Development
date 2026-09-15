import { expect, test } from "@playwright/test";

test("validation, persistence, and follow-on completion journey", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Add item" }).click();
  await expect(page.getByRole("alert")).toHaveText("Title is required");
  await page.getByLabel("Item title").fill("Ship bounded profiles");
  await page.getByRole("button", { name: "Add item" }).click();
  await expect(page.getByRole("list", { name: "Items" })).toContainText("Ship bounded profiles");
  await page.reload();
  await expect(page.getByRole("list", { name: "Items" })).toContainText("Ship bounded profiles");
  await page.getByRole("button", { name: "Complete Ship bounded profiles" }).click();
  await expect(page.getByRole("list", { name: "Items" })).toContainText("complete");
  await page.reload();
  await expect(page.getByRole("list", { name: "Items" })).toContainText("complete");
});
