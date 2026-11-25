import { expect, test, type Page } from "@playwright/test";

const PASSWORD = process.env.DEMO_PASSWORD ?? "CareLedger!2026";

async function login(page: Page, username: string) {
  await page.goto("/login");
  await page.getByLabel("Username or email").fill(username);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: /Welcome/ })).toBeVisible();
}

async function chooseOption(page: Page, label: string, option: RegExp) {
  await page.getByLabel(label).click();
  await page.getByRole("option", { name: option }).click();
}

test("accountant posts a balanced manual entry and sees it in the trial balance", async ({ page }) => {
  await login(page, "accountant");
  await page.goto("/journal/new");
  const memo = `E2E supplies ${Date.now()}`;
  await page.getByLabel("Memo").fill(memo);
  await chooseOption(page, "Account, line 1", /^5200 · Medical Supplies Expense/);
  await page.getByLabel("Debit, line 1").fill("123.45");
  await chooseOption(page, "Account, line 2", /^1020 · Bank - Operating/);
  await page.getByLabel("Credit, line 2").fill("123.40");
  await expect(page.getByText("Balanced")).toHaveCount(0);
  await page.getByLabel("Credit, line 2").fill("123.45");
  await expect(page.getByText("Balanced")).toBeVisible();
  await page.getByRole("button", { name: "Post entry" }).click();

  await expect(page.getByRole("heading", { name: /^JE-\d{6}$/ })).toBeVisible();
  await expect(page.getByText(memo)).toBeVisible();
  await expect(page.locator('[data-slot="badge"]', { hasText: /^Posted$/ })).toBeVisible();

  await page.goto("/reports?tab=trial-balance");
  await expect(page.getByText("Balanced").first()).toBeVisible();
  await expect(page.getByRole("link", { name: "Medical Supplies Expense" })).toBeVisible();
});

test("large entry needs finance-manager approval", async ({ page }) => {
  await login(page, "accountant");
  await page.goto("/journal/new");
  const memo = `E2E big ${Date.now()}`;
  await page.getByLabel("Memo").fill(memo);
  await chooseOption(page, "Account, line 1", /^5300 · Utilities/);
  await page.getByLabel("Debit, line 1").fill("25000");
  await chooseOption(page, "Account, line 2", /^1020 · Bank - Operating/);
  await page.getByLabel("Credit, line 2").fill("25000");
  await page.getByRole("button", { name: "Post entry" }).click();
  await expect(page.locator('[data-slot="badge"]', { hasText: "Pending approval" })).toBeVisible();
  const url = page.url();

  await page.getByRole("button", { name: /Avery|Casey/ }).click();
  await page.getByRole("menuitem", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/);
  await login(page, "finance");
  await page.goto(url);
  await page.getByRole("button", { name: "Approve and post" }).click();
  await expect(page.locator('[data-slot="badge"]', { hasText: /^Posted$/ })).toBeVisible();
});

test("reports render all four statements", async ({ page }) => {
  await login(page, "finance");
  await page.goto("/reports?tab=balance-sheet");
  await expect(page.getByText("Total liabilities and equity")).toBeVisible();
  await expect(page.getByText("Balanced")).toBeVisible();
  await page.getByRole("tab", { name: "Income statement" }).click();
  await expect(page.getByText("Net income")).toBeVisible();
  await page.goto("/accounts");
  await page.getByRole("link", { name: "Bank - Operating" }).click();
  await expect(page.getByRole("cell", { name: "Opening balance", exact: true }).first()).toBeVisible();
  await expect(page.getByText(/Closing balance \(debit-normal account\)/)).toBeVisible();
});

test("billing clerk cannot reach the ledger", async ({ page }) => {
  await login(page, "billing");
  const nav = page.getByRole("navigation", { name: "Main" });
  await expect(nav.getByRole("link", { name: "Journal entries" })).toHaveCount(0);
});
