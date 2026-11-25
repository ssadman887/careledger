import { MONEY_INPUT_PATTERN } from "@/lib/money";

export const MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
] as const;

/** "2026-11" style label for a payroll run or budget month. */
export function periodLabel(year: number, month: number): string {
  return `${MONTHS[month - 1] ?? "?"} ${year}`;
}

export interface SlabDraft {
  lower_bound: string;
  upper_bound: string; // "" = no upper limit
  rate_percent: string; // e.g. "10" for 10%
}

export interface SlabPayload {
  lower_bound: string;
  upper_bound: string | null;
  rate: string;
}

/** Percent string ("12.5") to a 4-dp rate string ("0.1250") without floating point. */
export function percentToRate(percent: string): string | null {
  const m = /^(\d{1,2})(?:\.(\d{1,2}))?$/.exec(percent.trim());
  if (!m) return null;
  const whole = Number(m[1]);
  const frac = (m[2] ?? "").padEnd(2, "0");
  const basisPoints = whole * 100 + Number(frac);
  if (basisPoints >= 10000) return null;
  return `0.${String(basisPoints).padStart(4, "0")}`;
}

/** "0.1250" -> "12.5" */
export function rateToPercent(rate: string): string {
  const bp = Math.round(Number(rate) * 10000); // display only; rates have 4 dp
  const whole = Math.floor(bp / 100);
  const frac = String(bp % 100)
    .padStart(2, "0")
    .replace(/0+$/, "");
  return frac ? `${whole}.${frac}` : String(whole);
}

/** Client-side mirror of the server's slab rules, for instant feedback. */
export function slabsToPayload(drafts: readonly SlabDraft[]): { slabs: SlabPayload[] } | { error: string } {
  if (drafts.length === 0) return { error: "Add at least one band" };
  const slabs: SlabPayload[] = [];
  for (const [i, d] of drafts.entries()) {
    const n = i + 1;
    if (!MONEY_INPUT_PATTERN.test(d.lower_bound)) return { error: `Band ${n}: invalid lower bound` };
    const last = i === drafts.length - 1;
    if (!last && !MONEY_INPUT_PATTERN.test(d.upper_bound))
      return { error: `Band ${n}: only the last band can be open-ended` };
    if (d.upper_bound && !MONEY_INPUT_PATTERN.test(d.upper_bound))
      return { error: `Band ${n}: invalid upper bound` };
    const rate = percentToRate(d.rate_percent);
    if (rate === null) return { error: `Band ${n}: rate must be 0-99.99%` };
    slabs.push({ lower_bound: d.lower_bound, upper_bound: d.upper_bound || null, rate });
  }
  if (Number(slabs[0]?.lower_bound) !== 0) return { error: "The first band must start at 0" };
  for (let i = 1; i < slabs.length; i++) {
    // Bounds are validated money strings; Number() is exact enough to compare them.
    if (Number(slabs[i]?.lower_bound) !== Number(slabs[i - 1]?.upper_bound))
      return { error: `Band ${i + 1} must start where band ${i} ends` };
  }
  return { slabs };
}

export interface BudgetLineDraft {
  account_id: string;
  annual: string;
}

/** Budget lines as an annual amount per account (the server splits them across months). */
export function budgetLinesToPayload(
  drafts: readonly BudgetLineDraft[],
): { lines: { account_id: number; annual: string }[] } | { error: string } {
  if (drafts.length === 0) return { error: "Add at least one account" };
  const seen = new Set<string>();
  const lines = [];
  for (const [i, d] of drafts.entries()) {
    if (!d.account_id) return { error: `Line ${i + 1}: choose an account` };
    if (seen.has(d.account_id)) return { error: `Line ${i + 1}: account already used` };
    seen.add(d.account_id);
    if (!MONEY_INPUT_PATTERN.test(d.annual))
      return { error: `Line ${i + 1}: enter an amount like 120000.00` };
    lines.push({ account_id: Number(d.account_id), annual: d.annual });
  }
  return { lines };
}
