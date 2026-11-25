import { describe, expect, it } from "vitest";

import { newAPLine, toPayload } from "@/components/payables/ap-line-editor";
import { entityHref } from "@/lib/approvals";
import { can } from "@/lib/permissions";

describe("AP line payloads", () => {
  it("validates lines before sending", () => {
    expect(toPayload([])).toEqual({ error: "Add at least one line" });
    const missing = { ...newAPLine(), description: "Gloves" };
    expect("error" in toPayload([missing])).toBe(true);
    const ok = { ...newAPLine("7"), description: " Gloves ", quantity: "2", unit_price: "10.50" };
    expect(toPayload([ok])).toEqual({
      lines: [{ description: "Gloves", account_id: 7, quantity: "2", unit_price: "10.50" }],
    });
    expect("error" in toPayload([{ ...ok, unit_price: "10.505" }])).toBe(true);
  });
});

describe("approval links and permissions", () => {
  it("points each approval kind at its record", () => {
    expect(entityHref({ kind: "manual_journal", entity_id: 5 })).toBe("/journal/5");
    expect(entityHref({ kind: "vendor_bill", entity_id: 9 })).toBe("/payables/bills/9");
    expect(entityHref({ kind: "write_off", entity_id: 1 })).toBe("/ar?tab=write-offs");
  });

  it("limits payables to accountants and policies to admin/finance", () => {
    expect(can(["accountant"], "managePayables")).toBe(true);
    expect(can(["finance_manager"], "managePayables")).toBe(false);
    expect(can(["finance_manager"], "editApprovalPolicies")).toBe(true);
    expect(can(["accountant"], "editApprovalPolicies")).toBe(false);
  });
});
