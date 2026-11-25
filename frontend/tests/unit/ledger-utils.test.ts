import { describe, expect, it } from "vitest";

import { flattenTree } from "@/lib/accounts-tree";
import { centsToString, sumMoney, toCents } from "@/lib/money";
import { can } from "@/lib/permissions";
import { emptyLine, journalEntrySchema } from "@/lib/validation/journal";

describe("money (integer cents, no floats)", () => {
  it("parses and formats exactly", () => {
    expect(toCents("0.1")).toBe(10n);
    expect(toCents("1234.56")).toBe(123456n);
    expect(toCents("")).toBe(0n);
    expect(toCents("1.234")).toBeNull();
    expect(toCents("abc")).toBeNull();
    expect(centsToString(-5n)).toBe("-0.05");
  });

  it("sums without floating point drift", () => {
    expect(sumMoney(["0.10", "0.20"])).toBe("0.30");
    expect(sumMoney(Array.from({ length: 10 }, () => "0.10"))).toBe("1.00");
    expect(sumMoney(["999999999999.99", "0.01"])).toBe("1000000000000.00");
  });
});

describe("flattenTree", () => {
  it("orders children under parents with depth", () => {
    const rows = flattenTree([
      { id: 3, code: "1010", parent_id: 1 },
      { id: 1, code: "1000", parent_id: null },
      { id: 2, code: "2000", parent_id: null },
      { id: 4, code: "1005", parent_id: 1 },
    ]);
    expect(rows.map((r) => [r.code, r.depth])).toEqual([
      ["1000", 0],
      ["1005", 1],
      ["1010", 1],
      ["2000", 0],
    ]);
  });
});

describe("journal entry validation", () => {
  const line = (account: string, debit: string, credit: string) => ({
    ...emptyLine(),
    account_id: account,
    debit,
    credit,
  });

  it("accepts a balanced entry", () => {
    const ok = journalEntrySchema.safeParse({
      entry_date: "2026-06-01",
      memo: "Test",
      lines: [line("1", "10.00", ""), line("2", "", "10.00")],
    });
    expect(ok.success).toBe(true);
  });

  it("rejects unbalanced, two-sided and empty lines", () => {
    const base = { entry_date: "2026-06-01", memo: "Test" };
    expect(
      journalEntrySchema.safeParse({ ...base, lines: [line("1", "10", ""), line("2", "", "9.99")] }).success,
    ).toBe(false);
    expect(
      journalEntrySchema.safeParse({ ...base, lines: [line("1", "10", "10"), line("2", "", "10")] }).success,
    ).toBe(false);
    expect(
      journalEntrySchema.safeParse({ ...base, lines: [line("1", "", ""), line("2", "", "")] }).success,
    ).toBe(false);
  });
});

describe("permissions mirror backend roles", () => {
  it("lets only accountants post and finance managers approve", () => {
    expect(can(["accountant"], "postJournal")).toBe(true);
    expect(can(["finance_manager"], "postJournal")).toBe(false);
    expect(can(["finance_manager"], "approveJournal")).toBe(true);
    expect(can(["auditor"], "approveJournal")).toBe(false);
  });
});
