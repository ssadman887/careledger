import { describe, expect, it } from "vitest";

import { formatMoney } from "@/lib/format";

describe("formatMoney", () => {
  it("formats API money strings with two decimals", () => {
    expect(formatMoney("1250")).toBe("$1,250.00");
    expect(formatMoney("0.10")).toBe("$0.10");
    expect(formatMoney("-42.50")).toBe("-$42.50");
  });

  it("renders a dash for missing or invalid values", () => {
    expect(formatMoney(null)).toBe("—");
    expect(formatMoney("")).toBe("—");
    expect(formatMoney("abc")).toBe("—");
  });
});
