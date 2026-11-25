import { expect, test } from "@playwright/test";

const PASSWORD = process.env.DEMO_PASSWORD ?? "CareLedger!2026";

test("login shows the demo banner and role-aware navigation", async ({ page }) => {
  await page.goto("/login");
  await expect(page.getByRole("status")).toHaveText(
    "Demo system. Synthetic data only. Not for real patient data.",
  );

  await page.getByLabel("Username or email").fill("admin");
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page.getByRole("heading", { name: /Welcome, Avery/ })).toBeVisible();
  const nav = page.getByRole("navigation", { name: "Main" });
  await expect(nav.getByRole("link", { name: "Users" })).toBeVisible();

  await nav.getByRole("link", { name: "Users" }).click();
  await expect(page.getByRole("cell", { name: "auditor@careledger.example" })).toBeVisible();
});

test("billing clerk does not see user administration", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Username or email").fill("billing");
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: /Welcome, Blake/ })).toBeVisible();
  await expect(
    page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Users" }),
  ).toHaveCount(0);
});

test("wrong password shows an error", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Username or email").fill("admin");
  await page.getByLabel("Password").fill("wrong-password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText("Invalid credentials")).toBeVisible();
});
