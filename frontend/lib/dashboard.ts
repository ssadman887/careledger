import type { Schemas } from "@/lib/api/client";
import { formatDateTime, formatMoney } from "@/lib/format";

export type ValueFormat = "money" | "count" | "percent" | "text" | "date";

/** Display a dashboard value. Money arrives as an exact decimal string. */
export function formatValue(value: string, format: ValueFormat): string {
  switch (format) {
    case "money":
      return formatMoney(value);
    case "percent":
      return `${value}%`;
    case "count":
      return Number.isFinite(Number(value)) ? Number(value).toLocaleString("en-US") : value;
    case "date":
      return formatDateTime(value);
    default:
      return value;
  }
}

/**
 * Chart rows for Recharts. Decimal strings become numbers here only to draw shapes; every
 * figure shown as text (KPIs, tooltips) comes from the exact string.
 */
export function chartData(chart: Schemas["ChartOut"]): Record<string, string | number>[] {
  return chart.rows.map((row) => {
    const out: Record<string, string | number> = { label: row.label };
    for (const k of chart.keys) out[k.key] = Number(row.values[k.key] ?? "0");
    return out;
  });
}
