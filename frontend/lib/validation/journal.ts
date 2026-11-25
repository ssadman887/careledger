import { z } from "zod";

import { MONEY_INPUT_PATTERN, toCents } from "@/lib/money";

const amount = z
  .string()
  .trim()
  .refine((v) => v === "" || MONEY_INPUT_PATTERN.test(v), "Use a number with up to 2 decimals");

export const journalLineSchema = z
  .object({
    account_id: z.string().min(1, "Choose an account"),
    debit: amount,
    credit: amount,
    description: z.string().max(500),
    department_id: z.string(),
  })
  .refine((l) => (toCents(l.debit) ?? 0n) > 0n !== (toCents(l.credit) ?? 0n) > 0n, {
    message: "Enter a debit or a credit (not both)",
    path: ["debit"],
  });

export const journalEntrySchema = z
  .object({
    entry_date: z.string().min(1, "Choose a date"),
    memo: z.string().trim().min(1, "Memo is required").max(2000),
    lines: z.array(journalLineSchema).min(2, "At least two lines"),
  })
  .refine(
    (e) => {
      const debit = e.lines.reduce((s, l) => s + (toCents(l.debit) ?? 0n), 0n);
      const credit = e.lines.reduce((s, l) => s + (toCents(l.credit) ?? 0n), 0n);
      return debit === credit && debit > 0n;
    },
    { message: "Total debits must equal total credits", path: ["lines"] },
  );

export type JournalEntryValues = z.infer<typeof journalEntrySchema>;
export type JournalLineValues = z.infer<typeof journalLineSchema>;

export const emptyLine = (): JournalLineValues => ({
  account_id: "",
  debit: "",
  credit: "",
  description: "",
  department_id: "",
});
