import { describe, expect, it } from "vitest";

import { entityHref } from "@/lib/approvals";
import { can } from "@/lib/permissions";
import {
  budgetLinesToPayload,
  percentToRate,
  periodLabel,
  rateToPercent,
  slabsToPayload,
} from "@/lib/payroll";

describe("tax rate conversions", () => {
  it("converts percents to 4-dp rates without floating point", () => {
    expect(percentToRate("10")).toBe("0.1000");
    expect(percentToRate("12.5")).toBe("0.1250");
    expect(percentToRate("0")).toBe("0.0000");
    expect(percentToRate("0.07")).toBe("0.0007");
    expect(percentToRate("100")).toBeNull();
    expect(percentToRate("abc")).toBeNull();
    expect(percentToRate("1.234")).toBeNull();
  });

  it("formats rates back to percents", () => {
    expect(rateToPercent("0.3000")).toBe("30");
    expect(rateToPercent("0.1250")).toBe("12.5");
    expect(rateToPercent("0.0500")).toBe("5");
  });
});

describe("tax slab payloads", () => {
  const band = (lower_bound: string, upper_bound: string, rate_percent: string) => ({
    lower_bound,
    upper_bound,
    rate_percent,
  });

  it("builds contiguous slabs with an open-ended top band", () => {
    expect(slabsToPayload([band("0.00", "12000.00", "0"), band("12000.00", "", "10")])).toEqual({
      slabs: [
        { lower_bound: "0.00", upper_bound: "12000.00", rate: "0.0000" },
        { lower_bound: "12000.00", upper_bound: null, rate: "0.1000" },
      ],
    });
  });

  it("rejects gaps, a non-zero start and open middle bands", () => {
    expect(slabsToPayload([])).toEqual({ error: "Add at least one band" });
    expect("error" in slabsToPayload([band("10.00", "", "5")])).toBe(true);
    expect("error" in slabsToPayload([band("0", "100", "0"), band("150", "", "10")])).toBe(true);
    expect("error" in slabsToPayload([band("0", "", "0"), band("100", "", "10")])).toBe(true);
  });
});

describe("budget line payloads", () => {
  it("validates accounts and annual amounts", () => {
    expect(budgetLinesToPayload([{ account_id: "7", annual: "120000.00" }])).toEqual({
      lines: [{ account_id: 7, annual: "120000.00" }],
    });
    expect("error" in budgetLinesToPayload([{ account_id: "", annual: "1" }])).toBe(true);
    expect("error" in budgetLinesToPayload([{ account_id: "7", annual: "1.234" }])).toBe(true);
    expect(
      "error" in
        budgetLinesToPayload([
          { account_id: "7", annual: "1" },
          { account_id: "7", annual: "2" },
        ]),
    ).toBe(true);
  });
});

describe("payroll navigation and permissions", () => {
  it("links payroll approvals to the run and labels periods", () => {
    expect(entityHref({ kind: "payroll_run", entity_id: 4 })).toBe("/payroll/runs/4");
    expect(periodLabel(2026, 11)).toBe("Nov 2026");
  });

  it("separates payroll preparation from approval and budgets", () => {
    expect(can(["accountant"], "managePayroll")).toBe(true);
    expect(can(["accountant"], "approvePayroll")).toBe(false);
    expect(can(["finance_manager"], "approvePayroll")).toBe(true);
    expect(can(["finance_manager"], "manageBudgets")).toBe(true);
    expect(can(["accountant"], "manageBudgets")).toBe(false);
    expect(can(["auditor"], "managePayroll")).toBe(false);
  });
});
