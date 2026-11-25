import { expect, test, type Page } from "@playwright/test";

const PASSWORD = process.env.DEMO_PASSWORD ?? "CareLedger!2026";

async function login(page: Page, username: string) {
  await page.goto("/login");
  await page.getByLabel("Username or email").fill(username);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: /Welcome/ })).toBeVisible();
}

test("dashboards show the sections each role may see", async ({ page }) => {
  await login(page, "finance");
  for (const title of ["Financial position", "Revenue cycle", "Insurance claims"]) {
    await expect(page.getByRole("heading", { name: title })).toBeVisible();
  }
  await expect(page.getByRole("heading", { name: "System activity" })).toHaveCount(0);
  await expect(page.getByText("Cash and bank")).toBeVisible();
  await expect(page.getByText("Revenue and expenses, last 12 months")).toBeVisible();

  await page.getByRole("button", { name: /Morgan/ }).click();
  await page.getByRole("menuitem", { name: "Sign out" }).click();
  await login(page, "billing");
  await expect(page.getByRole("heading", { name: "Revenue cycle" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Financial position" })).toHaveCount(0);
});

test("global search finds records and opens them", async ({ page }) => {
  await login(page, "accountant");
  await page.keyboard.press("/");
  await page.getByRole("combobox", { name: "Search records" }).fill("1020");
  await page.getByRole("option", { name: /1020 Bank - Operating/ }).click();
  await expect(page).toHaveURL(/\/accounts\?focus=\d+$/);
});

test("notifications: finance sees unread items and opens one", async ({ page }) => {
  await login(page, "finance");
  const bell = page.getByRole("button", { name: /^Notifications, \d+ unread$/ });
  await expect(bell).toBeVisible();
  await bell.click();
  await expect(page.getByRole("menuitem").first()).toBeVisible();
  await page
    .getByRole("menuitem")
    .filter({ hasText: /Approval needed|Budget/ })
    .first()
    .click();
  await expect(page).toHaveURL(/\/(approvals|budgets)/);
});

test("audit viewer filters, expands changes and exports CSV", async ({ page }) => {
  await login(page, "admin");
  await page.goto("/audit");
  await page.getByLabel("Action").click();
  await page.getByRole("option", { name: "Login", exact: true }).click();
  await page.getByRole("button", { name: "Apply filters" }).click();
  const firstRow = page.getByRole("button", { name: /^Show changes for entry \d+$/ }).first();
  await expect(firstRow).toBeVisible();
  await expect(page.getByRole("row").nth(1)).toContainText("Login");
  await firstRow.click();
  await expect(
    page.getByRole("columnheader", { name: "Field" }).or(page.getByText("Field").first()),
  ).toBeVisible();

  await page.getByRole("button", { name: "Export" }).click();
  const download = page.waitForEvent("download");
  await page.getByRole("menuitem", { name: /CSV/ }).click();
  expect((await download).suggestedFilename()).toMatch(/^audit-log-\d{4}-\d{2}-\d{2}\.csv$/);
});

test("financial reports export as CSV and PDF", async ({ page }) => {
  await login(page, "accountant");
  await page.goto("/reports?tab=trial-balance");
  await page.getByRole("button", { name: "Export" }).click();
  let download = page.waitForEvent("download");
  await page.getByRole("menuitem", { name: /CSV/ }).click();
  expect((await download).suggestedFilename()).toMatch(/^trial-balance-.*\.csv$/);

  await page.goto("/reports?tab=balance-sheet");
  await page.getByRole("button", { name: "Export" }).click();
  download = page.waitForEvent("download");
  await page.getByRole("menuitem", { name: "PDF" }).click();
  expect((await download).suggestedFilename()).toMatch(/^balance-sheet-.*\.pdf$/);
});
