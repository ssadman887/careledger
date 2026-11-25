"use client";

import { Plus, Trash2 } from "lucide-react";

import { Money } from "@/components/money";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { Account } from "@/lib/api/hooks";
import { centsToString, MONEY_INPUT_PATTERN, toCents } from "@/lib/money";

export interface APDraftLine {
  key: string;
  description: string;
  account_id: string;
  quantity: string;
  unit_price: string;
}

let n = 0;
export const newAPLine = (accountId = ""): APDraftLine => ({
  key: `ap${++n}`,
  description: "",
  account_id: accountId,
  quantity: "1",
  unit_price: "",
});

const QTY = /^\d{1,8}(\.\d{1,2})?$/;

/** Validate and convert draft lines to API payloads. Returns an error message or the lines. */
export function toPayload(
  lines: APDraftLine[],
):
  | { error: string }
  | { lines: { description: string; account_id: number; quantity: string; unit_price: string }[] } {
  if (lines.length === 0) return { error: "Add at least one line" };
  for (const [i, l] of lines.entries()) {
    if (!l.description.trim() || !l.account_id)
      return { error: `Line ${i + 1}: description and account are required` };
    if (!QTY.test(l.quantity) || l.quantity === "0") return { error: `Line ${i + 1}: invalid quantity` };
    if (!MONEY_INPUT_PATTERN.test(l.unit_price)) return { error: `Line ${i + 1}: unit price like 12.50` };
  }
  return {
    lines: lines.map((l) => ({
      description: l.description.trim(),
      account_id: Number(l.account_id),
      quantity: l.quantity,
      unit_price: l.unit_price,
    })),
  };
}

/** Indicative line amount for display (exact: integer cents x quantity with 2 decimals). */
function lineAmount(l: APDraftLine): string | null {
  const price = toCents(l.unit_price);
  if (price === null || !QTY.test(l.quantity)) return null;
  const [whole = "0", frac = ""] = l.quantity.split(".");
  const qtyHundredths = BigInt(whole) * 100n + BigInt(frac.padEnd(2, "0"));
  const cents = (price * qtyHundredths + 50n) / 100n; // half-up, matches the server for positives
  return centsToString(cents);
}

export function APLineEditor({
  lines,
  onChange,
  accounts,
}: {
  lines: APDraftLine[];
  onChange: (lines: APDraftLine[]) => void;
  accounts: Account[];
}) {
  const expenseAccounts = accounts.filter(
    (a) => !a.is_header && a.is_active && (a.type === "expense" || a.type === "asset"),
  );
  const update = (key: string, patch: Partial<APDraftLine>) =>
    onChange(lines.map((l) => (l.key === key ? { ...l, ...patch } : l)));
  return (
    <div className="flex flex-col gap-2">
      {lines.map((l, i) => (
        <fieldset
          key={l.key}
          className="grid gap-2 rounded-md border p-2 sm:grid-cols-[2fr_1.6fr_0.7fr_1fr_0.9fr_36px]"
        >
          <legend className="sr-only">Line {i + 1}</legend>
          <Input
            aria-label={`Description, line ${i + 1}`}
            placeholder="Description"
            value={l.description}
            onChange={(e) => update(l.key, { description: e.target.value })}
          />
          <div>
            <Label htmlFor={`ap-acc-${l.key}`} className="sr-only">
              Account, line {i + 1}
            </Label>
            <Select value={l.account_id} onValueChange={(v) => update(l.key, { account_id: v })}>
              <SelectTrigger id={`ap-acc-${l.key}`} className="w-full">
                <SelectValue placeholder="Account" />
              </SelectTrigger>
              <SelectContent>
                {expenseAccounts.map((a) => (
                  <SelectItem key={a.id} value={String(a.id)}>
                    {a.code} · {a.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <Input
            aria-label={`Quantity, line ${i + 1}`}
            inputMode="decimal"
            value={l.quantity}
            onChange={(e) => update(l.key, { quantity: e.target.value })}
          />
          <Input
            aria-label={`Unit price, line ${i + 1}`}
            inputMode="decimal"
            placeholder="0.00"
            value={l.unit_price}
            onChange={(e) => update(l.key, { unit_price: e.target.value })}
          />
          <span className="self-center text-right text-sm">
            {lineAmount(l) ? <Money value={lineAmount(l) ?? "0"} /> : "—"}
          </span>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label={`Remove line ${i + 1}`}
            disabled={lines.length <= 1}
            onClick={() => onChange(lines.filter((x) => x.key !== l.key))}
          >
            <Trash2 />
          </Button>
        </fieldset>
      ))}
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="self-start"
        onClick={() => onChange([...lines, newAPLine()])}
      >
        <Plus /> Add line
      </Button>
    </div>
  );
}
