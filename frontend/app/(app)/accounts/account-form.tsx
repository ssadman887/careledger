"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Controller, useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { api, errorMessage } from "@/lib/api/client";
import type { Account } from "@/lib/api/hooks";

const TYPES = ["asset", "liability", "equity", "revenue", "expense"] as const;
const NONE = "none";

const schema = z.object({
  code: z
    .string()
    .trim()
    .regex(/^[A-Z0-9][A-Z0-9-]{0,19}$/, "Uppercase letters, digits and dashes"),
  name: z.string().trim().min(1, "Name is required").max(160),
  type: z.enum(TYPES),
  parent: z.string(),
  is_header: z.boolean(),
  description: z.string().max(2000),
});
type Values = z.infer<typeof schema>;

export function AccountForm({
  open,
  account,
  accounts,
  onClose,
  onSaved,
}: {
  open: boolean;
  account: Account | null;
  accounts: Account[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const editing = account !== null;
  const {
    register,
    control,
    handleSubmit,
    watch,
    formState: { errors, isSubmitting },
  } = useForm<Values>({
    resolver: zodResolver(schema),
    values: {
      code: account?.code ?? "",
      name: account?.name ?? "",
      type: account?.type ?? "expense",
      parent: account?.parent_id ? String(account.parent_id) : NONE,
      is_header: account?.is_header ?? false,
      description: account?.description ?? "",
    },
  });
  const type = watch("type");
  const parents = accounts.filter((a) => a.is_header && a.type === type && a.id !== account?.id);

  const onSubmit = handleSubmit(async (v) => {
    const parentId = v.parent === NONE ? null : Number(v.parent);
    const result = editing
      ? await api.PATCH("/api/v1/accounts/{account_id}", {
          params: { path: { account_id: account.id } },
          body: {
            name: v.name,
            description: v.description,
            parent_id: parentId,
            clear_parent: parentId === null,
          },
        })
      : await api.POST("/api/v1/accounts", {
          body: {
            code: v.code,
            name: v.name,
            type: v.type,
            parent_id: parentId,
            is_header: v.is_header,
            description: v.description,
          },
        });
    if (!result.data) {
      toast.error(errorMessage(result.error, "Could not save account"));
      return;
    }
    toast.success(`Saved ${result.data.code} ${result.data.name}`);
    onSaved();
  });

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{editing ? `Edit ${account.code}` : "New account"}</DialogTitle>
          <DialogDescription>
            {editing
              ? "Code and type are fixed once created."
              : "Header accounts group others and cannot be posted to."}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={onSubmit} noValidate className="grid gap-4 sm:grid-cols-2">
          <div className="flex flex-col gap-2">
            <Label htmlFor="acc-code">Code</Label>
            <Input id="acc-code" disabled={editing} aria-invalid={!!errors.code} {...register("code")} />
            {errors.code && <p className="text-destructive text-sm">{errors.code.message}</p>}
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="acc-type">Type</Label>
            <Controller
              control={control}
              name="type"
              render={({ field }) => (
                <Select value={field.value} onValueChange={field.onChange} disabled={editing}>
                  <SelectTrigger id="acc-type" className="w-full capitalize">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {TYPES.map((t) => (
                      <SelectItem key={t} value={t} className="capitalize">
                        {t}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            />
          </div>
          <div className="flex flex-col gap-2 sm:col-span-2">
            <Label htmlFor="acc-name">Name</Label>
            <Input id="acc-name" aria-invalid={!!errors.name} {...register("name")} />
            {errors.name && <p className="text-destructive text-sm">{errors.name.message}</p>}
          </div>
          <div className="flex flex-col gap-2 sm:col-span-2">
            <Label htmlFor="acc-parent">Parent (header account)</Label>
            <Controller
              control={control}
              name="parent"
              render={({ field }) => (
                <Select value={field.value} onValueChange={field.onChange}>
                  <SelectTrigger id="acc-parent" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={NONE}>No parent (top level)</SelectItem>
                    {parents.map((p) => (
                      <SelectItem key={p.id} value={String(p.id)}>
                        {p.code} · {p.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            />
          </div>
          {!editing && (
            <label className="flex items-center gap-2 text-sm sm:col-span-2">
              <input type="checkbox" className="size-4" {...register("is_header")} />
              Header account (summary only)
            </label>
          )}
          <div className="flex flex-col gap-2 sm:col-span-2">
            <Label htmlFor="acc-desc">Description</Label>
            <Textarea id="acc-desc" rows={2} {...register("description")} />
          </div>
          <DialogFooter className="sm:col-span-2">
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={isSubmitting}>
              {isSubmitting ? "Saving…" : "Save"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
