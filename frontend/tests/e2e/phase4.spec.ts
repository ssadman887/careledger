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
  await page.getByRole("button", { name: /Blake|Morgan|Casey/ }).click();
  await page.getByRole("menuitem", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/);
}

test("write-off: billing requests, finance approves in the inbox, bad debt posted", async ({ page }) => {
  test.setTimeout(60_000);
  await login(page, "billing");
  // A fresh patient and invoice so the test is independent of seed state.
  await page.goto("/patients");
  await page.getByRole("button", { name: "Register patient" }).click();
  const last = `WO${Date.now().toString().slice(-6)}`;
  await page.getByLabel("First name").fill("Bad");
  await page.getByLabel("Last name").fill(last);
  await page.getByLabel("Date of birth").fill("1960-02-02");
  await page.getByRole("button", { name: "Register", exact: true }).click();
  await page.getByRole("link", { name: "New invoice" }).click();
  await page.getByRole("button", { name: "Create draft" }).click();
  await page.getByRole("button", { name: "Add charge" }).click();
  await page.getByLabel("Service, line 1").click();
  await page.getByRole("option", { name: /^OPD-FU · / }).click();
  await page.getByRole("button", { name: "Save charges" }).click();
  await expect(page.getByText("Charges saved")).toBeVisible();
  await page.getByRole("button", { name: "Issue invoice" }).click();
  await page.getByRole("button", { name: "Issue and post" }).click();
  await expect(badge(page, "Issued")).toBeVisible();
  const invoiceUrl = page.url();

  await page.getByRole("button", { name: "Write off" }).click();
  await page.getByLabel("Reason").fill("Patient relocated abroad; uncollectible");
  await page.getByRole("button", { name: "Request write-off" }).click();
  await expect(page.getByText(/sent for finance-manager approval/)).toBeVisible();
  await logout(page);

  await login(page, "finance");
  await expect(page.getByRole("navigation", { name: "Main" }).getByLabel(/pending/)).toBeVisible();
  await page.goto("/approvals?tab=to_decide");
  const row = page.getByRole("row", { name: new RegExp(`Bad ${last}`) });
  await row.getByRole("button", { name: "Review" }).click();
  await page.getByLabel("Add a comment").fill("Checked the collection notes");
  await page.getByRole("button", { name: "Comment" }).click();
  await expect(page.getByText("Checked the collection notes")).toBeVisible();
  await page.getByRole("button", { name: "Approve" }).click();
  await expect(page.getByText(/approved$/)).toBeVisible();

  await page.goto(invoiceUrl);
  await expect(badge(page, /^Paid$/)).toBeVisible();
});

test("purchase to pay: PO, receipt, matched bill auto-approves, payment", async ({ page }) => {
  test.setTimeout(60_000);
  await login(page, "accountant");
  await page.goto("/payables?tab=purchase-orders");
  await page.getByRole("button", { name: "New purchase order" }).click();
  await page.getByLabel("Vendor", { exact: true }).click();
  await page.getByRole("option", { name: "Northgate Medical Supplies" }).click();
  await page.getByLabel("Description, line 1").fill("Suture kits");
  await page.getByLabel("Quantity, line 1").fill("10");
  await page.getByLabel("Unit price, line 1").fill("18.40");
  await page.getByRole("button", { name: "Create purchase order" }).click();
  await expect(page.getByRole("heading", { name: /^PO-\d{6}$/ })).toBeVisible();

  await page.getByRole("button", { name: "Issue to vendor" }).click();
  await expect(badge(page, "Issued")).toBeVisible();
  await page.getByRole("button", { name: "Record receipt" }).click();
  await expect(badge(page, "Received")).toBeVisible();
  await page.getByRole("button", { name: "Create bill from PO" }).click();
  await page.getByLabel("Vendor invoice number").fill(`NG-E2E-${Date.now()}`);
  await page.getByRole("button", { name: "Create bill" }).click();
  await expect(page.getByRole("heading", { name: /^BILL-\d{6}$/ })).toBeVisible();
  await expect(badge(page, "Matched")).toBeVisible();

  await page.getByRole("button", { name: "Submit for approval" }).click();
  await expect(badge(page, /^Approved$/)).toBeVisible(); // matched and under threshold
  await page.getByRole("button", { name: "Pay", exact: true }).click();
  await page.getByRole("button", { name: "Record payment" }).click();
  await expect(badge(page, /^Paid$/)).toBeVisible();
});

test("AR aging shows buckets and reminders can be run", async ({ page }) => {
  await login(page, "finance");
  await page.goto("/ar");
  await expect(page.getByRole("columnheader", { name: "90+ days" })).toBeVisible();
  await expect(page.getByText("Total outstanding")).toBeVisible();
  await page.getByRole("tab", { name: "Aging by insurer" }).click();
  await expect(page.getByRole("columnheader", { name: "Insurer" })).toBeVisible();
  await page.getByRole("tab", { name: "Reminders" }).click();
  await page.getByRole("button", { name: "Run reminders" }).click();
  await expect(page.getByText(/^(Sent \d+ reminder\(s\)|No new reminders due)$/)).toBeVisible();
});

test("finance manager voids an approved, unpaid bill with a reversing entry", async ({ page }) => {
  test.setTimeout(60_000);
  await login(page, "accountant");
  await page.goto("/payables?tab=bills");
  await page.getByRole("button", { name: "New bill" }).click();
  await page.getByLabel("Vendor", { exact: true }).click();
  await page.getByRole("option", { name: "Clearview Facility Services" }).click();
  await page.getByLabel("Vendor invoice number").fill(`CV-E2E-${Date.now()}`);
  await page.getByLabel("Description, line 1").fill("Window cleaning");
  await page.getByLabel("Unit price, line 1").fill("180.00");
  await page.getByRole("button", { name: "Create bill" }).click();
  await expect(page.getByRole("heading", { name: /^BILL-\d{6}$/ })).toBeVisible();
  await page.getByRole("button", { name: "Submit for approval" }).click();
  await expect(badge(page, /^Approved$/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Void" })).toHaveCount(0); // accountants cannot void posted bills
  const billUrl = page.url();
  await logout(page);

  await login(page, "finance");
  await page.goto(billUrl);
  await page.getByRole("button", { name: "Void" }).click();
  await page.getByLabel("Reason").fill("Duplicate of an earlier invoice");
  await page.getByRole("button", { name: "Void bill" }).click();
  await expect(badge(page, /^Void$/)).toBeVisible();
  await expect(page.getByRole("link", { name: "Reversal" })).toBeVisible();
});
