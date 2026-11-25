import { expect, test, type Page } from "@playwright/test";

const PASSWORD = process.env.DEMO_PASSWORD ?? "CareLedger!2026";

async function login(page: Page, username: string) {
  await page.goto("/login");
  await page.getByLabel("Username or email").fill(username);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: /Welcome/ })).toBeVisible();
}

async function logout(page: Page) {
  await page.getByRole("button", { name: /Blake|Morgan|Casey/ }).click();
  await page.getByRole("menuitem", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/);
}

const badge = (page: Page, text: string | RegExp) => page.locator('[data-slot="badge"]', { hasText: text });

test("billing clerk captures charges, issues, takes a partial payment and requests a refund", async ({
  page,
}) => {
  await login(page, "billing");

  // Register a fresh synthetic patient so the test is independent of seed state.
  await page.goto("/patients");
  await page.getByRole("button", { name: "Register patient" }).click();
  const last = `E2E${Date.now().toString().slice(-6)}`;
  await page.getByLabel("First name").fill("Playwright");
  await page.getByLabel("Last name").fill(last);
  await page.getByLabel("Date of birth").fill("1985-04-12");
  await page.getByRole("button", { name: "Register", exact: true }).click();
  await expect(page.getByRole("heading", { name: `Playwright ${last}` })).toBeVisible();

  // New invoice (no visit) -> draft
  await page.getByRole("link", { name: "New invoice" }).click();
  await expect(page.getByText(`Playwright ${last}`).first()).toBeVisible();
  await page.getByRole("button", { name: "Create draft" }).click();
  await expect(page.getByRole("heading", { name: /^INV-\d{6}$/ })).toBeVisible();
  await expect(badge(page, "Draft")).toBeVisible();

  // Charge capture: priced by the server from the price list.
  await page.getByRole("button", { name: "Add charge" }).click();
  await page.getByLabel("Service, line 1").click();
  await page.getByRole("option", { name: /^OPD-NEW · / }).click();
  await page.getByRole("button", { name: "Add charge" }).click();
  await page.getByLabel("Service, line 2").click();
  await page.getByRole("option", { name: /^PHAR-ANALG · / }).click();
  await page.getByLabel("Quantity, line 2").fill("2");
  await page.getByRole("button", { name: "Save charges" }).click();
  await expect(page.getByRole("cell", { name: "Outpatient consultation, new patient" })).toBeVisible();
  // 210.00 + 2 x 18.00 + 5% tax on 36.00 (1.80) = 247.80
  await expect(page.getByText("$247.80").first()).toBeVisible();

  // Issue -> posts to the ledger
  await page.getByRole("button", { name: "Issue invoice" }).click();
  await page.getByRole("button", { name: "Issue and post" }).click();
  await expect(badge(page, "Issued")).toBeVisible();
  await expect(page.getByText("Posted to ledger")).toBeVisible();

  // Partial cash payment
  await page.getByRole("button", { name: "Record payment" }).click();
  await page.getByLabel("Amount").fill("100.00");
  await page.getByRole("dialog").getByRole("button", { name: "Record payment" }).click();
  await expect(badge(page, "Partially paid")).toBeVisible();
  await expect(page.getByText("$147.80").first()).toBeVisible();

  // Refund part of it (below threshold: completes immediately)
  await page.getByRole("button", { name: "Refund" }).click();
  await page.getByLabel("Amount").fill("20.00");
  await page.getByLabel("Reason").fill("Duplicate analgesic charge");
  await page.getByRole("button", { name: "Request refund" }).click();
  await expect(page.getByText("$167.80").first()).toBeVisible();

  const invoiceNumber = (await page.getByRole("heading", { name: /^INV-\d{6}$/ }).textContent()) ?? "";
  await logout(page);

  // The accountant can follow the invoice to its balanced journal entry.
  await login(page, "accountant");
  await page.goto("/journal");
  await page.getByLabel("Search").fill(invoiceNumber);
  await page
    .getByRole("link", { name: /^JE-\d{6}$/ })
    .first()
    .click();
  await expect(page.getByText(`Invoice ${invoiceNumber}`).first()).toBeVisible();
  await expect(page.getByRole("link", { name: /1100.*Accounts Receivable - Patients/ })).toBeVisible();
});

test("large refund waits for finance-manager approval", async ({ page }) => {
  await login(page, "billing");
  await page.goto("/patients");
  await page.getByRole("button", { name: "Register patient" }).click();
  const last = `Refund${Date.now().toString().slice(-6)}`;
  await page.getByLabel("First name").fill("Big");
  await page.getByLabel("Last name").fill(last);
  await page.getByLabel("Date of birth").fill("1970-01-01");
  await page.getByRole("button", { name: "Register", exact: true }).click();
  await expect(page.getByRole("heading", { name: `Big ${last}` })).toBeVisible();

  // Deposit on account, then refund most of it (above the 500.00 threshold).
  await page.getByRole("button", { name: "Record deposit" }).click();
  await page.getByLabel("Amount").fill("900.00");
  await page.getByRole("dialog").getByRole("button", { name: "Record deposit" }).click();
  await expect(page.getByText("$900.00").first()).toBeVisible();

  await page.goto("/payments?tab=payments");
  await page.getByLabel("Search").fill(last);
  await page
    .getByRole("row", { name: new RegExp(last) })
    .getByRole("button", { name: "Refund" })
    .click();
  await page.getByLabel("Amount").fill("700.00");
  await page.getByLabel("Reason").fill("Admission cancelled");
  await page.getByRole("button", { name: "Request refund" }).click();
  await expect(page.getByText(/sent for finance-manager approval/)).toBeVisible();
  await logout(page);

  await login(page, "finance");
  await page.goto("/payments?tab=refunds");
  const row = page.getByRole("row", { name: new RegExp(`Big ${last}`) });
  await row.getByRole("button", { name: "Approve" }).click();
  await page.getByRole("button", { name: "Approve refund" }).click();
  await expect(page.getByText(/approved and posted/)).toBeVisible();
});

test("insurance officer can view invoices but not bill", async ({ page }) => {
  await login(page, "insurance");
  await page.goto("/invoices");
  await expect(page.getByRole("heading", { name: "Invoices" })).toBeVisible();
  await expect(page.getByRole("link", { name: "New invoice" })).toHaveCount(0);
});
