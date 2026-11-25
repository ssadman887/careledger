import { describe, expect, it } from "vitest";

import { NAV, navForRoles } from "@/lib/nav";

const labels = (roles: Parameters<typeof navForRoles>[0]) =>
  navForRoles(roles).flatMap((s) => s.items.map((i) => i.label));

describe("navForRoles", () => {
  it("shows Users only to admins (and auditors)", () => {
    expect(labels(["admin"])).toContain("Users");
    expect(labels(["billing_clerk"])).not.toContain("Users");
    expect(labels(["auditor"])).toContain("Users");
  });

  it("gives auditors every item", () => {
    const all = NAV.flatMap((s) => s.items).length;
    expect(labels(["auditor"])).toHaveLength(all);
  });

  it("keeps billing clerks out of the ledger", () => {
    const items = labels(["billing_clerk"]);
    expect(items).toContain("Invoices");
    expect(items).not.toContain("Journal entries");
  });

  it("drops empty sections", () => {
    expect(navForRoles([])).toEqual([]);
    const revenue = navForRoles(["admin"]).find((s) => s.title === "Revenue cycle");
    expect(revenue?.items.map((i) => i.label)).toEqual(["Insurers"]);
  });
});
