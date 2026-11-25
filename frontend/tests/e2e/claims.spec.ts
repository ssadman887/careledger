import { expect, test, type Page } from "@playwright/test";

const PASSWORD = process.env.DEMO_PASSWORD ?? "CareLedger!2026";
const badge = (page: Page, text: string | RegExp) => page.locator('[data-slot="badge"]', { hasText: text });

async function login(page: Page, username: string) {
  await page.goto("/login");
  await page.getByLabel("Username or email").fill(username);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: /Welcome/ })).toBeVisible();
}

async function logout(page: Page) {
  await page.getByRole("button", { name: /Blake|Indira/ }).click();
  await page.getByRole("menuitem", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/);
}

/** Billing clerk: issue an invoice for the patient and draft a claim; returns the claim URL. */
async function invoiceAndDraftClaim(page: Page, patientUrl: string, serviceCode: string): Promise<string> {
  await page.goto(patientUrl);
  await page.getByRole("link", { name: "New invoice" }).click();
  await page.getByRole("button", { name: "Create draft" }).click();
  await expect(badge(page, "Draft")).toBeVisible();
  await page.getByRole("button", { name: "Add charge" }).click();
  await page.getByLabel("Service, line 1").click();
  await page.getByRole("option", { name: new RegExp(`^${serviceCode} · `) }).click();
  await page.getByRole("button", { name: "Save charges" }).click();
  await expect(page.getByText("Charges saved")).toBeVisible();
  await page.getByRole("button", { name: "Issue invoice" }).click();
  await page.getByRole("button", { name: "Issue and post" }).click();
  await expect(badge(page, "Issued")).toBeVisible();

  await page.getByRole("button", { name: "Create claim" }).click();
  await expect(page.getByText("Insurer pays")).toBeVisible();
  await page.getByRole("button", { name: "Draft claim" }).click();
  await expect(page.getByRole("heading", { name: /^CLM-\d{6}$/ })).toBeVisible();
  return page.url();
}

async function adjudicate(page: Page, outcome: RegExp) {
  await page.getByRole("button", { name: "Run mock insurer" }).click();
  await page.getByLabel("Outcome").click();
  await page.getByRole("option", { name: outcome }).click();
  await page.getByRole("button", { name: "Adjudicate" }).click();
}

test("claims cycle: partial approval, denial and appeal, remittance posts and pays", async ({ page }) => {
  test.setTimeout(90_000);
  await login(page, "billing");

  // Synthetic patient with insurance.
  await page.goto("/patients");
  await page.getByRole("button", { name: "Register patient" }).click();
  const last = `Claim${Date.now().toString().slice(-6)}`;
  await page.getByLabel("First name").fill("Insured");
  await page.getByLabel("Last name").fill(last);
  await page.getByLabel("Date of birth").fill("1979-03-03");
  await page.getByRole("button", { name: "Register", exact: true }).click();
  await expect(page.getByRole("heading", { name: `Insured ${last}` })).toBeVisible();
  const patientUrl = page.url();

  await page.getByRole("button", { name: "Add policy" }).click();
  await page.getByLabel("Insurer").click();
  await page.getByRole("option", { name: "Crestline Health Plan" }).click();
  await page.getByLabel("Policy number").fill(`CRS-${Date.now().toString().slice(-7)}`);
  await page.getByRole("button", { name: "Add policy" }).last().click();
  await expect(page.getByText("Crestline Health Plan")).toBeVisible();

  const partialClaimUrl = await invoiceAndDraftClaim(page, patientUrl, "RAD-MRI-KNEE");
  const deniedClaimUrl = await invoiceAndDraftClaim(page, patientUrl, "RAD-CT-HEAD");
  await expect(page.getByRole("button", { name: "Submit to insurer" })).toHaveCount(0); // clerks only draft
  await logout(page);

  await login(page, "insurance");

  // Claim 1: submit, partially approved by the mock insurer.
  await page.goto(partialClaimUrl);
  await page.getByRole("button", { name: "Submit to insurer" }).click();
  await expect(badge(page, "Submitted")).toBeVisible();
  await adjudicate(page, /Partially approve/);
  await expect(badge(page, "Partially approved")).toBeVisible();
  await expect(
    page.getByRole("list", { name: "Claim events" }).getByText("contractual adjustment (partial approval)"),
  ).toBeVisible();
  const claimNumber = (await page.getByRole("heading", { name: /^CLM-\d{6}$/ }).textContent()) ?? "";
  const approvedText =
    (await page
      .getByText(/^Approved$/)
      .locator("..")
      .locator("..")
      .textContent()) ?? "";
  const approved = /\$([\d,]+\.\d{2})/.exec(approvedText)?.[1]?.replace(/,/g, "") ?? "";
  expect(approved).toMatch(/^\d+\.\d{2}$/);

  // Claim 2: submit, denied, appeal with grounds.
  await page.goto(deniedClaimUrl);
  await page.getByRole("button", { name: "Submit to insurer" }).click();
  await adjudicate(page, /^Deny/);
  await expect(badge(page, "Denied")).toBeVisible();
  await expect(page.getByText("Not deemed a medical necessity")).toBeVisible();
  await page.getByRole("button", { name: "Appeal" }).click();
  await page.getByLabel("Grounds (required)").fill("Clinical notes show necessity; requesting re-review.");
  await page.getByRole("button", { name: "File appeal" }).click();
  await expect(badge(page, "Appealed")).toBeVisible();

  // Remittance for claim 1: import CSV, review, post.
  await page.goto("/remittances");
  await page.getByRole("button", { name: "Import CSV" }).click();
  await page.getByLabel("Insurer").click();
  await page.getByRole("option", { name: "Crestline Health Plan" }).click();
  await page.getByLabel("Payer reference (EFT / cheque)").fill(`EFT-E2E-${Date.now()}`);
  await page.getByLabel("CSV file").setInputFiles({
    name: "era.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(
      `claim_number,paid_amount,remark\n${claimNumber},${approved},Paid\nCLM-999998,10.00,unknown\n`,
    ),
  });
  await page.getByRole("button", { name: "Import and reconcile" }).click();
  await expect(page.getByRole("heading", { name: /^REM-\d{6}$/ })).toBeVisible();
  await expect(badge(page, /^Matched$/)).toBeVisible();
  await expect(badge(page, "Unmatched")).toBeVisible();
  await page.getByRole("button", { name: /Post 1 line\(s\) to ledger/ }).click();
  await expect(badge(page, /^Posted$/)).toBeVisible();

  await page.goto(partialClaimUrl);
  await expect(badge(page, /^Paid$/)).toBeVisible();
});

test("auditor can read claims but not act", async ({ page }) => {
  await login(page, "auditor");
  await page.goto("/claims");
  await expect(page.getByRole("heading", { name: "Claims" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Run mock insurer" })).toHaveCount(0);
});
