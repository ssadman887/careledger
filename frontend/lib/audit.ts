export interface FieldChange {
  field: string;
  before: string;
  after: string;
  changed: boolean;
}

function show(value: unknown): string {
  if (value === undefined) return "";
  if (value === null) return "null";
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

/**
 * Field-by-field view of an audit entry. Fields present on either side are listed; the ones
 * whose value differs are flagged (creates show every field as changed, deletes likewise).
 */
export function diffFields(
  before: Record<string, unknown> | null | undefined,
  after: Record<string, unknown> | null | undefined,
): FieldChange[] {
  const b = before ?? {};
  const a = after ?? {};
  const fields = [...new Set([...Object.keys(b), ...Object.keys(a)])].sort();
  return fields
    .map((field) => {
      const prev = show(b[field]);
      const next = show(a[field]);
      return { field, before: prev, after: next, changed: !(field in b && field in a) || prev !== next };
    })
    .sort((x, y) => Number(y.changed) - Number(x.changed));
}
