import { describe, expect, it } from "vitest";

import { filenameFrom } from "@/lib/api/exports";
import { diffFields } from "@/lib/audit";
import { chartData, formatValue } from "@/lib/dashboard";

describe("dashboard values", () => {
  it("formats money, percents and counts from exact strings", () => {
    expect(formatValue("1695422.44", "money")).toBe("$1,695,422.44");
    expect(formatValue("-997718.93", "money")).toBe("-$997,718.93");
    expect(formatValue("37.5", "percent")).toBe("37.5%");
    expect(formatValue("12345", "count")).toBe("12,345");
    expect(formatValue("Cash", "text")).toBe("Cash");
  });

  it("turns chart rows into numeric series for drawing only", () => {
    const rows = chartData({
      id: "pl",
      title: "P&L",
      kind: "bar",
      description: "",
      keys: [
        { key: "revenue", label: "Revenue", format: "money" },
        { key: "expenses", label: "Expenses", format: "money" },
      ],
      rows: [{ label: "Oct 2026", values: { revenue: "1200.50" } }],
    });
    expect(rows).toEqual([{ label: "Oct 2026", revenue: 1200.5, expenses: 0 }]);
  });
});

describe("audit diffs", () => {
  it("flags changed fields first and shows creates as all-new", () => {
    const fields = diffFields({ status: "draft", total: "10.00" }, { status: "issued", total: "10.00" });
    expect(fields[0]).toEqual({ field: "status", before: "draft", after: "issued", changed: true });
    expect(fields[1]?.changed).toBe(false);
    expect(diffFields(null, { id: 1, tags: ["a"] })).toEqual([
      { field: "id", before: "", after: "1", changed: true },
      { field: "tags", before: "", after: '["a"]', changed: true },
    ]);
    expect(diffFields(null, null)).toEqual([]);
  });
});

describe("export downloads", () => {
  it("reads the file name from Content-Disposition", () => {
    expect(filenameFrom('attachment; filename="trial-balance-2026-11-25.csv"', "x.csv")).toBe(
      "trial-balance-2026-11-25.csv",
    );
    expect(filenameFrom(null, "export.pdf")).toBe("export.pdf");
  });
});
