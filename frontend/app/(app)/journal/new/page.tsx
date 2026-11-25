"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Plus, Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { Controller, useFieldArray, useForm } from "react-hook-form";
import { toast } from "sonner";

import { Money } from "@/components/money";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { api, errorMessage } from "@/lib/api/client";
import { useAccounts, useDepartments } from "@/lib/api/hooks";
import { centsToString, sumMoney, toCents } from "@/lib/money";
import { emptyLine, journalEntrySchema, type JournalEntryValues } from "@/lib/validation/journal";

const NONE = "none";

export default function NewJournalEntryPage() {
  const router = useRouter();
  const { accounts } = useAccounts();
  const departments = useDepartments();
  const postable = accounts.filter((a) => !a.is_header && a.is_active);

  const {
    register,
    control,
    handleSubmit,
    watch,
    formState: { errors, isSubmitting },
  } = useForm<JournalEntryValues>({
    resolver: zodResolver(journalEntrySchema),
    defaultValues: {
      entry_date: new Date().toISOString().slice(0, 10),
      memo: "",
      lines: [emptyLine(), emptyLine()],
    },
  });
  const { fields, append, remove } = useFieldArray({ control, name: "lines" });
  const lines = watch("lines");
  const totalDebit = sumMoney(lines.map((l) => l.debit));
  const totalCredit = sumMoney(lines.map((l) => l.credit));
  const difference = centsToString((toCents(totalDebit) ?? 0n) - (toCents(totalCredit) ?? 0n));
  const balanced = totalDebit === totalCredit && totalDebit !== "0.00";

  const onSubmit = handleSubmit(async (v) => {
    const { data, error } = await api.POST("/api/v1/journal-entries", {
      body: {
        entry_date: v.entry_date,
        memo: v.memo,
        lines: v.lines.map((l) => ({
          account_id: Number(l.account_id),
          debit: l.debit || "0",
          credit: l.credit || "0",
          description: l.description,
          department_id: l.department_id && l.department_id !== NONE ? Number(l.department_id) : null,
        })),
      },
    });
    if (!data) return void toast.error(errorMessage(error, "Could not save entry"));
    toast.success(
      data.status === "pending_approval"
        ? `${data.entry_number} submitted for finance-manager approval`
        : `${data.entry_number} posted`,
    );
    router.push(`/journal/${data.id}`);
  });

  return (
    <>
      <PageHeader
        title="New journal entry"
        description="Manual entries above the approval threshold wait for a finance manager before posting."
      />
      <form onSubmit={onSubmit} noValidate className="flex flex-col gap-6">
        <Card>
          <CardContent className="grid gap-4 sm:grid-cols-[200px_1fr]">
            <div className="flex flex-col gap-2">
              <Label htmlFor="je-date">Entry date</Label>
              <Input
                id="je-date"
                type="date"
                aria-invalid={!!errors.entry_date}
                {...register("entry_date")}
              />
              {errors.entry_date && <p className="text-destructive text-sm">{errors.entry_date.message}</p>}
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="je-memo">Memo</Label>
              <Textarea id="je-memo" rows={2} aria-invalid={!!errors.memo} {...register("memo")} />
              {errors.memo && <p className="text-destructive text-sm">{errors.memo.message}</p>}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="flex flex-col gap-3">
            <div className="text-muted-foreground hidden grid-cols-[2fr_1.2fr_1fr_1fr_1.5fr_40px] gap-2 text-xs font-medium lg:grid">
              <span>Account</span>
              <span>Department</span>
              <span className="text-right">Debit</span>
              <span className="text-right">Credit</span>
              <span>Line description</span>
              <span className="sr-only">Remove</span>
            </div>
            {fields.map((field, i) => {
              const lineErr = errors.lines?.[i];
              return (
                <fieldset
                  key={field.id}
                  className="grid gap-2 rounded-md border p-3 lg:grid-cols-[2fr_1.2fr_1fr_1fr_1.5fr_40px] lg:border-0 lg:p-0"
                >
                  <legend className="sr-only">Line {i + 1}</legend>
                  <div>
                    <Label htmlFor={`line-${i}-account`} className="sr-only">
                      Account, line {i + 1}
                    </Label>
                    <Controller
                      control={control}
                      name={`lines.${i}.account_id`}
                      render={({ field: f }) => (
                        <Select value={f.value} onValueChange={f.onChange}>
                          <SelectTrigger
                            id={`line-${i}-account`}
                            className="w-full"
                            aria-invalid={!!lineErr?.account_id}
                          >
                            <SelectValue placeholder="Choose account" />
                          </SelectTrigger>
                          <SelectContent>
                            {postable.map((a) => (
                              <SelectItem key={a.id} value={String(a.id)}>
                                {a.code} · {a.name}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      )}
                    />
                  </div>
                  <div>
                    <Label htmlFor={`line-${i}-dept`} className="sr-only">
                      Department, line {i + 1}
                    </Label>
                    <Controller
                      control={control}
                      name={`lines.${i}.department_id`}
                      render={({ field: f }) => (
                        <Select value={f.value || NONE} onValueChange={f.onChange}>
                          <SelectTrigger id={`line-${i}-dept`} className="w-full">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value={NONE}>No department</SelectItem>
                            {departments.map((d) => (
                              <SelectItem key={d.id} value={String(d.id)}>
                                {d.name}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      )}
                    />
                  </div>
                  <Input
                    aria-label={`Debit, line ${i + 1}`}
                    inputMode="decimal"
                    placeholder="0.00"
                    className="text-right tabular-nums"
                    aria-invalid={!!lineErr?.debit}
                    {...register(`lines.${i}.debit`)}
                  />
                  <Input
                    aria-label={`Credit, line ${i + 1}`}
                    inputMode="decimal"
                    placeholder="0.00"
                    className="text-right tabular-nums"
                    aria-invalid={!!lineErr?.credit}
                    {...register(`lines.${i}.credit`)}
                  />
                  <Input aria-label={`Description, line ${i + 1}`} {...register(`lines.${i}.description`)} />
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    aria-label={`Remove line ${i + 1}`}
                    disabled={fields.length <= 2}
                    onClick={() => remove(i)}
                  >
                    <Trash2 />
                  </Button>
                  {(lineErr?.account_id || lineErr?.debit || lineErr?.credit) && (
                    <p className="text-destructive text-sm lg:col-span-6">
                      {lineErr.account_id?.message ?? lineErr.debit?.message ?? lineErr.credit?.message}
                    </p>
                  )}
                </fieldset>
              );
            })}
            <div className="flex flex-wrap items-center justify-between gap-3 border-t pt-3">
              <Button type="button" variant="outline" size="sm" onClick={() => append(emptyLine())}>
                <Plus /> Add line
              </Button>
              <dl className="flex gap-6 text-sm" aria-live="polite">
                <div>
                  <dt className="text-muted-foreground text-xs">Total debit</dt>
                  <dd className="font-medium">
                    <Money value={totalDebit} />
                  </dd>
                </div>
                <div>
                  <dt className="text-muted-foreground text-xs">Total credit</dt>
                  <dd className="font-medium">
                    <Money value={totalCredit} />
                  </dd>
                </div>
                <div>
                  <dt className="text-muted-foreground text-xs">Difference</dt>
                  <dd className={balanced ? "font-medium text-emerald-600" : "text-destructive font-medium"}>
                    {balanced ? "Balanced" : <Money value={difference} />}
                  </dd>
                </div>
              </dl>
            </div>
            {errors.lines?.root?.message || errors.lines?.message ? (
              <Alert variant="destructive">
                <AlertDescription>{errors.lines?.root?.message ?? errors.lines?.message}</AlertDescription>
              </Alert>
            ) : null}
          </CardContent>
        </Card>

        <div className="flex gap-2">
          <Button type="submit" disabled={isSubmitting}>
            {isSubmitting ? "Posting…" : "Post entry"}
          </Button>
          <Button type="button" variant="outline" onClick={() => router.push("/journal")}>
            Cancel
          </Button>
        </div>
      </form>
    </>
  );
}
