import { expect, test, type Page } from "@playwright/test";

const PASSWORD = process.env.DEMO_PASSWORD ?? "CareLedger!2026";
const badge = (page: Page, text: string | RegExp) => page.locator('[data-slot="badge"]', { hasText: text });
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

async function login(page: Page, username: string) {
  await page.goto("/login");
  await page.getByLabel("Username or email").fill(username);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: /Welcome/ })).toBeVisible();
}

async function logout(page: Page) {
  await page.getByRole("button", { name: /Morgan|Casey|Jordan/ }).click();
  await page.getByRole("menuitem", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/);
}

/** Start a run for the first month (from Dec 2026) that has none yet; returns the run URL. */
async function startFreeRun(page: Page): Promise<string> {
  await page.goto("/payroll");
  for (let i = 0; i < 12; i++) {
    const year = 2026 + Math.floor((11 + i) / 12);
    const month = MONTHS[(11 + i) % 12] ?? "Dec";
    await page.getByRole("button", { name: "New payroll run" }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("Month").click();
    await page.getByRole("option", { name: month, exact: true }).click();
    await dialog.getByLabel("Year").fill(String(year));
    // Earlier "already exists" toasts may still be on screen: wait for a new one.
    const seen = await page.getByText(/already exists/).count();
    await dialog.getByRole("button", { name: "Start run" }).click();
    const outcome = await Promise.race([
      page.waitForURL(/\/payroll\/runs\/\d+$/, { timeout: 10_000 }).then(() => "created" as const),
      page
        .getByText(/already exists/)
        .nth(seen)
        .waitFor({ timeout: 10_000 })
        .then(() => "exists" as const),
    ]);
    if (outcome === "created") return page.url();
    await page.keyboard.press("Escape");
  }
  throw new Error("No free payroll month in the next 12 months");
}

test("payroll: background run, finance approval posts, accountant pays", async ({ page }) => {
  test.setTimeout(90_000);
  await login(page, "accountant");
  const runUrl = await startFreeRun(page);
  // The background job (Celery worker, or in-process fallback) calculates the payslips.
  await expect(badge(page, /^Calculated$/)).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole("button", { name: /Payslip PDF for/ }).first()).toBeVisible();
  await page.getByRole("button", { name: "Submit for approval" }).click();
  await expect(badge(page, "Pending approval")).toBeVisible();
  await expect(page.getByText("Awaiting finance-manager approval")).toBeVisible();
  await logout(page);

  await login(page, "finance");
  await page.goto(runUrl);
  await page.getByRole("button", { name: "Approve and post" }).click();
  await expect(badge(page, /^Posted$/)).toBeVisible();
  await expect(page.getByRole("link", { name: "View entry" })).toBeVisible();
  await logout(page);

  await login(page, "accountant");
  await page.goto(runUrl);
  await page.getByRole("button", { name: "Pay salaries" }).click();
  await page.getByRole("button", { name: "Confirm payment" }).click();
  await expect(badge(page, /^Paid$/)).toBeVisible();
  await expect(page.getByRole("link", { name: "View entry" })).toHaveCount(3);
});

test("employees: accountant adds an employee; auditors see masked bank details", async ({ page }) => {
  test.setTimeout(60_000);
  await login(page, "accountant");
  await page.goto("/payroll?tab=employees");
  const last = `E2E${Date.now().toString().slice(-6)}`;
  await page.getByRole("button", { name: "Add employee" }).click();
  const form = page.getByRole("dialog");
  await form.getByLabel("First name").fill("Test");
  await form.getByLabel("Last name").fill(last);
  await form.getByLabel("Department").click();
  await page.getByRole("option", { name: "Laboratory" }).click();
  await form.getByLabel("Position").fill("Lab Assistant");
  await form.getByLabel("Bank reference").fill("GB00-E2E-445566");
  await form.getByLabel("Basic salary").fill("2800.00");
  await form.getByRole("button", { name: "Add employee" }).click();
  await expect(page.getByText(new RegExp(`EMP-\\d+ Test ${last} added`))).toBeVisible();
  await logout(page);

  await login(page, "auditor");
  await page.goto("/payroll?tab=employees");
  await page.getByLabel("Search").fill(last);
  await page.getByRole("button", { name: `Test ${last}` }).click();
  await expect(page.getByText(/\*+5566/)).toBeVisible();
  await expect(page.getByText("GB00-E2E-445566")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Edit salary and details" })).toHaveCount(0);
});

test("budgets: variance shows the Emergency overrun and alerts", async ({ page }) => {
  await login(page, "finance");
  await page.goto("/budgets");
  await expect(page.getByText(/Emergency: 5100 Salaries & Wages exceeded/).first()).toBeVisible();
  await page.getByRole("link", { name: "Emergency 2026" }).click();
  await page.getByLabel("Year to date through").click();
  await page.getByRole("option", { name: "Oct 2026" }).click();
  const salaries = page.getByRole("row", { name: /^5100 Salaries & Wages expense/i });
  await expect(salaries.locator('[data-slot="badge"]', { hasText: "Exceeded" })).toBeVisible();
  await expect(page.getByText("Monthly expenses: budget vs actual")).toBeVisible();
  await page.goto("/budgets");
  await page.getByRole("button", { name: "Check alerts now" }).click();
  await expect(page.getByText(/^(\d+ new alert\(s\)|No new alerts)$/)).toBeVisible();
});
