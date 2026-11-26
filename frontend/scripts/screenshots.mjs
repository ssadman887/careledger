// Capture README screenshots from a running, freshly seeded stack:
//   node scripts/screenshots.mjs   (from frontend/, with .\scripts\dev.ps1 running)
import { fileURLToPath } from "node:url";

import { chromium } from "@playwright/test";

const BASE = process.env.E2E_BASE_URL ?? "http://localhost:3000";
const PASSWORD = process.env.DEMO_PASSWORD ?? "CareLedger!2026";
const OUT = new URL("../../docs/screenshots/", import.meta.url);

async function login(page, user) {
  await page.goto(`${BASE}/login`);
  await page.getByLabel("Username or email").fill(user);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByRole("heading", { name: /Welcome/ }).waitFor();
}

async function shot(page, name, path, { wait, fullPage = false } = {}) {
  await page.goto(`${BASE}${path}`);
  if (wait) await page.getByText(wait).first().waitFor();
  await page.waitForTimeout(2500); // let chart animations finish
  await page.screenshot({ path: fileURLToPath(new URL(`${name}.png`, OUT)), fullPage });
  console.log(`saved ${name}.png`);
}

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, colorScheme: "light" });
await login(page, "finance");
await shot(page, "dashboard", "/dashboard", { wait: "Revenue and expenses, last 12 months" });
await shot(page, "approvals", "/approvals?tab=to_decide", { wait: "Review" });
await shot(page, "ar-aging", "/ar", { wait: "Total outstanding" });
await shot(page, "budget-variance", "/budgets/2", { wait: "Variance by account" });
await shot(page, "payroll-run", "/payroll/runs/6", { wait: "Payslips" });
await page.goto(`${BASE}/claims`);
await page
  .getByRole("link", { name: /^CLM-\d{6}$/ })
  .first()
  .click();
await page
  .getByText("Claim events")
  .first()
  .waitFor()
  .catch(() => {});
await page.waitForTimeout(500);
await page.screenshot({ path: fileURLToPath(new URL("claim.png", OUT)) });
console.log("saved claim.png");
await shot(page, "trial-balance", "/reports?tab=trial-balance", { wait: "Balanced" });
await shot(page, "audit-log", "/audit", { wait: "entries" });
await browser.close();
