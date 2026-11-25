/**
 * Exact money arithmetic for the UI using integer cents (bigint). Never floats.
 * Used only for presentation (e.g. live debit/credit totals in the journal line editor);
 * the backend remains the authority and re-validates everything.
 */
export const MONEY_INPUT_PATTERN = /^\d{1,12}(\.\d{1,2})?$/;

export function toCents(value: string | null | undefined): bigint | null {
  if (value === null || value === undefined) return null;
  const trimmed = value.trim();
  if (trimmed === "") return 0n;
  const match = /^(-)?(\d+)(?:\.(\d{1,2}))?$/.exec(trimmed);
  if (!match) return null;
  const [, sign, whole = "0", frac = ""] = match;
  const cents = BigInt(whole) * 100n + BigInt(frac.padEnd(2, "0"));
  return sign ? -cents : cents;
}

export function centsToString(cents: bigint): string {
  const negative = cents < 0n;
  const abs = negative ? -cents : cents;
  const whole = abs / 100n;
  const frac = (abs % 100n).toString().padStart(2, "0");
  return `${negative ? "-" : ""}${whole}.${frac}`;
}

export function sumMoney(values: readonly (string | null | undefined)[]): string {
  let total = 0n;
  for (const v of values) total += toCents(v) ?? 0n;
  return centsToString(total);
}
