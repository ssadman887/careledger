const CURRENCY = process.env.NEXT_PUBLIC_CURRENCY ?? "USD";

const moneyFormatter = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: CURRENCY,
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

/**
 * Format a money string from the API (e.g. "1250.00") for display.
 * Money arrives as a decimal string; it is only converted to a number for display formatting,
 * never for arithmetic.
 */
export function formatMoney(value: string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  return Number.isFinite(n) ? moneyFormatter.format(n) : "—";
}

const dateTimeFormatter = new Intl.DateTimeFormat("en-US", {
  dateStyle: "medium",
  timeStyle: "short",
});

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? "—" : dateTimeFormatter.format(d);
}

/** "partially_paid" -> "Partially paid" */
export function humanize(value: string): string {
  const text = value.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}
