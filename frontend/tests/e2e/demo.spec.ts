/**
 * The demo script (README "Demo script"), end to end, in order. Each step is its own test so a
 * failure points at the step; they share state and run serially.
 */
import { expect, test, type Page } from "@playwright/test";

const PASSWORD = process.env.DEMO_PASSWORD ?? "CareLedger!2026";
const badge = (page: Page, text: string | RegExp) => page.locator('[data-slot="badge"]', { hasText: text });
const stamp = Date.now().toString().slice(-6);

async function login(page: Page, username: string) {
  await page.goto("/login");
  await page.getByLabel("Username or email").fill(username);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: /Welcome/ })).toBeVisible();
}

async function choose(page: Page, label: string, option: RegExp | string) {
  await page.getByLabel(label, { exact: true }).click();
  await page.getByRole("option", { name: option }).first().click();
}

/** Issue an invoice for the given visit row ("Bill") with one service. */
async function billVisit(page: Page, serviceCode: string) {
  await page.getByRole("link", { name: "Bill" }).first().click();
  await page.getByRole("button", { name: "Create draft" }).click();
  await expect(badge(page, "Draft")).toBeVisible();
  await page.getByRole("button", { name: "Add charge" }).click();
  await choose(page, "Service, line 1", new RegExp(`^${serviceCode} · `));
  await page.getByRole("button", { name: "Save charges" }).click();
  await expect(page.getByText("Charges saved")).toBeVisible();
  await page.getByRole("button", { name: "Issue invoice" }).click();
  await page.getByRole("button", { name: "Issue and post" }).click();
  await expect(badge(page, "Issued")).toBeVisible();
}

async function draftClaim(page: Page): Promise<string> {
  await page.getByRole("button", { name: "Create claim" }).click();
  await expect(page.getByText("Insurer pays")).toBeVisible();
  await page.getByRole("button", { name: "Draft claim" }).click();
  await expect(page.getByRole("heading", { name: /^CLM-\d{6}$/ })).toBeVisible();
  return page.url();
}

async function adjudicate(page: Page, outcome: RegExp) {
  await page.getByRole("button", { name: "Submit to insurer" }).click();
  await expect(badge(page, "Submitted")).toBeVisible();
  await page.getByRole("button", { name: "Run mock insurer" }).click();
  await choose(page, "Outcome", outcome);
  await page.getByRole("button", { name: "Adjudicate" }).click();
}

const state: {
  patientUrl: string;
  invoiceUrl: string;
  invoiceNumber: string;
  partialClaimUrl: string;
  deniedClaimUrl: string;
  claimNumber: string;
  approved: string;
} = {
  patientUrl: "",
  invoiceUrl: "",
  invoiceNumber: "",
  partialClaimUrl: "",
  deniedClaimUrl: "",
  claimNumber: "",
  approved: "",
};

test.describe.configure({ mode: "serial" });

test("1-2. billing clerk records a visit, invoices it and issues it", async ({ page }) => {
  test.setTimeout(60_000);
  await login(page, "billing");
  await page.goto("/patients");
  await page.getByRole("button", { name: "Register patient" }).click();
  await page.getByLabel("First name").fill("Demo");
  await page.getByLabel("Last name").fill(`Patient${stamp}`);
  await page.getByLabel("Date of birth").fill("1972-06-15");
  await page.getByRole("button", { name: "Register", exact: true }).click();
  await expect(page.getByRole("heading", { name: `Demo Patient${stamp}` })).toBeVisible();
  state.patientUrl = page.url();

  await page.getByRole("button", { name: "Add policy" }).click();
  await choose(page, "Insurer", "Crestline Health Plan");
  await page.getByLabel("Policy number").fill(`CRS-D${stamp}`);
  await page.getByRole("button", { name: "Add policy" }).last().click();
  await expect(page.getByText("Crestline Health Plan")).toBeVisible();

  await page.getByRole("button", { name: "New visit" }).click();
  await choose(page, "Department", "Radiology");
  await page.getByLabel("Attending physician").fill("Dr. Demo");
  await page.getByRole("button", { name: "Create visit" }).click();
  await expect(page.getByText(/^Visit V-\d+ created$/)).toBeVisible();

  await billVisit(page, "RAD-MRI-KNEE");
  await expect(page.getByText(/visit V-\d+/)).toBeVisible();
  state.invoiceUrl = page.url();
  state.invoiceNumber = (await page.getByRole("heading", { name: /^INV-\d{6}$/ }).textContent()) ?? "";
  state.partialClaimUrl = await draftClaim(page);

  // A second visit and invoice for the claim that will be denied.
  await page.goto(state.patientUrl);
  await billVisit(page, "RAD-CT-HEAD");
  state.deniedClaimUrl = await draftClaim(page);
});

test("3. insurance officer submits claims: one partial approval, one denial, an appeal", async ({ page }) => {
  await login(page, "insurance");
  await page.goto(state.partialClaimUrl);
  await adjudicate(page, /Partially approve/);
  await expect(badge(page, "Partially approved")).toBeVisible();
  state.claimNumber = (await page.getByRole("heading", { name: /^CLM-\d{6}$/ }).textContent()) ?? "";
  const approvedText =
    (await page
      .getByText(/^Approved$/)
      .locator("..")
      .locator("..")
      .textContent()) ?? "";
  state.approved = /\$([\d,]+\.\d{2})/.exec(approvedText)?.[1]?.replace(/,/g, "") ?? "";
  expect(state.approved).toMatch(/^\d+\.\d{2}$/);

  await page.goto(state.deniedClaimUrl);
  await adjudicate(page, /^Deny/);
  await expect(badge(page, "Denied")).toBeVisible();
  await page.getByRole("button", { name: "Appeal" }).click();
  await page.getByLabel("Grounds (required)").fill("Clinical notes support medical necessity.");
  await page.getByRole("button", { name: "File appeal" }).click();
  await expect(badge(page, "Appealed")).toBeVisible();
});

test("4. patient payment and insurer remittance post to the ledger", async ({ page }) => {
  test.setTimeout(60_000);
  await login(page, "billing");
  await page.goto(state.invoiceUrl);
  await page.getByRole("button", { name: "Record payment" }).click();
  await page.getByLabel("Amount").fill("50.00");
  await page.getByRole("dialog").getByRole("button", { name: "Record payment" }).click();
  await expect(badge(page, "Partially paid")).toBeVisible();
  await page.getByRole("button", { name: /Blake/ }).click();
  await page.getByRole("menuitem", { name: "Sign out" }).click();

  await login(page, "insurance");
  await page.goto("/remittances");
  await page.getByRole("button", { name: "Import CSV" }).click();
  await choose(page, "Insurer", "Crestline Health Plan");
  await page.getByLabel("Payer reference (EFT / cheque)").fill(`EFT-DEMO-${stamp}`);
  await page.getByLabel("CSV file").setInputFiles({
    name: "era.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(`claim_number,paid_amount,remark\n${state.claimNumber},${state.approved},Paid\n`),
  });
  await page.getByRole("button", { name: "Import and reconcile" }).click();
  await expect(badge(page, /^Matched$/)).toBeVisible();
  await page.getByRole("button", { name: /Post 1 line\(s\) to ledger/ }).click();
  await expect(badge(page, /^Posted$/)).toBeVisible();
  await page.getByRole("button", { name: /Indira/ }).click();
  await page.getByRole("menuitem", { name: "Sign out" }).click();

  // The resulting journal entries, as the finance manager sees them.
  await login(page, "finance");
  await page.goto("/journal");
  await page.getByLabel("Search", { exact: true }).fill(state.invoiceNumber);
  await expect(page.getByRole("link", { name: /^JE-\d{6}$/ }).nth(1)).toBeVisible(); // issue + payment
  await page.getByLabel("Search", { exact: true }).fill(state.claimNumber);
  await page
    .getByRole("link", { name: /^JE-\d{6}$/ })
    .first()
    .click();
  await expect(page.getByRole("link", { name: /1110.*Accounts Receivable - Insurers/ })).toBeVisible();
});

test("5. finance manager approves a pending write-off", async ({ page }) => {
  await login(page, "billing");
  await page.goto(state.invoiceUrl);
  await page.getByRole("button", { name: "Write off" }).click();
  await page.getByLabel("Reason").fill("Demo: patient balance deemed uncollectible");
  await page.getByRole("button", { name: "Request write-off" }).click();
  await expect(page.getByText(/sent for finance-manager approval/)).toBeVisible();
  await page.getByRole("button", { name: /Blake/ }).click();
  await page.getByRole("menuitem", { name: "Sign out" }).click();

  await login(page, "finance");
  await page.goto("/approvals?tab=to_decide");
  const row = page.getByRole("row", { name: new RegExp(`Demo Patient${stamp}`) });
  await row.getByRole("button", { name: "Review" }).click();
  await page.getByRole("button", { name: "Approve" }).click();
  await expect(page.getByText(/approved$/)).toBeVisible();
});

test("6. dashboard: AR aging, collection rate, revenue by department, budgets", async ({ page }) => {
  await login(page, "finance");
  await expect(page.getByText("Receivables by age")).toBeVisible();
  await expect(page.getByText("Collection rate, 90 days")).toBeVisible();
  await expect(page.getByText("Net revenue by department, year to date")).toBeVisible();
  await expect(page.getByText(/Expense budget used, year to date/)).toBeVisible();
  await page.goto("/budgets");
  await page.getByRole("link", { name: "Emergency 2026" }).click();
  await expect(page.getByText("Variance by account")).toBeVisible();
});

test("7. accountant reviews statements, closes last month and cannot post into it", async ({ page }) => {
  await login(page, "accountant");
  await page.goto("/reports?tab=trial-balance");
  await expect(page.getByText("Balanced").first()).toBeVisible();
  await page.getByRole("tab", { name: "Income statement" }).click();
  await expect(page.getByText("Net income")).toBeVisible();

  const now = new Date();
  const last = new Date(now.getFullYear(), now.getMonth() - 1, 1);
  const name = `${last.getFullYear()}-${String(last.getMonth() + 1).padStart(2, "0")}`;
  await page.goto("/periods");
  const row = page.getByRole("row", { name: new RegExp(`^${name} `) });
  await expect(row).toBeVisible(); // periods loaded before deciding whether to close
  if ((await row.getByRole("button", { name: /Close/ }).count()) > 0) {
    await row.getByRole("button", { name: /Close/ }).click();
    await page.getByRole("button", { name: /^Close period/ }).click();
    await expect(page.getByText(`${name} closed. Postings into it are now rejected.`)).toBeVisible();
  }
  await expect(row.locator('[data-slot="badge"]', { hasText: "Closed" })).toBeVisible();

  await page.goto("/journal/new");
  await page.getByLabel("Entry date").fill(`${name}-15`);
  await page.getByLabel("Memo").fill(`Late adjustment ${stamp}`);
  await choose(page, "Account, line 1", /^5900 · /);
  await page.getByLabel("Debit, line 1").fill("100.00");
  await choose(page, "Account, line 2", /^1020 · /);
  await page.getByLabel("Credit, line 2").fill("100.00");
  await page.getByRole("button", { name: "Post entry" }).click();
  await expect(page.getByText(/closed/i).first()).toBeVisible();
  await expect(page).toHaveURL(/\/journal\/new$/);
});

test("8. auditor opens the audit trail of the invoice from step 2", async ({ page }) => {
  await login(page, "auditor");
  await page.goto(state.invoiceUrl);
  await page.getByRole("link", { name: "Audit trail" }).click();
  await expect(page).toHaveURL(/\/audit\?entity_type=invoice&entity_id=\d+/);
  const rows = page.getByRole("button", { name: /^Show changes for entry \d+$/ });
  await expect(rows.first()).toBeVisible();
  await expect(page.getByRole("cell", { name: /Issue|Create/ }).first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Edit" })).toHaveCount(0);
});
