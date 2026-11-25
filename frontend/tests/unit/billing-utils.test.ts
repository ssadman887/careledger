import { describe, expect, it } from "vitest";

import { humanize } from "@/lib/format";
import { newKey } from "@/lib/idempotency";
import { can } from "@/lib/permissions";

describe("billing helpers", () => {
  it("humanizes status values", () => {
    expect(humanize("partially_paid")).toBe("Partially paid");
    expect(humanize("bank_transfer")).toBe("Bank transfer");
  });

  it("generates unique idempotency keys long enough for the API (8-128 chars)", () => {
    const keys = new Set(Array.from({ length: 100 }, () => newKey()));
    expect(keys.size).toBe(100);
    for (const k of keys) expect(k.length).toBeGreaterThanOrEqual(8);
  });

  it("mirrors billing permissions", () => {
    expect(can(["billing_clerk"], "bill")).toBe(true);
    expect(can(["insurance_officer"], "bill")).toBe(false);
    expect(can(["finance_manager"], "voidInvoice")).toBe(true);
    expect(can(["billing_clerk"], "approveRefund")).toBe(false);
  });
});

describe("claims permissions", () => {
  it("lets clerks draft but only insurance officers work claims", () => {
    expect(can(["billing_clerk"], "draftClaim")).toBe(true);
    expect(can(["billing_clerk"], "workClaims")).toBe(false);
    expect(can(["insurance_officer"], "workClaims")).toBe(true);
    expect(can(["finance_manager"], "draftClaim")).toBe(false);
  });
});
