"use client";

import { Plus } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
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
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api, errorMessage, type Schemas } from "@/lib/api/client";
import { useAuth } from "@/lib/auth/auth-context";
import { can } from "@/lib/permissions";

type Insurer = Schemas["InsurerOut"];
const RATE = /^(0(\.\d{1,4})?|1(\.0{1,4})?)$/;
const pct = (v: string) => `${Math.round(Number(v) * 100)}%`;

function InsurerDialog({
  open,
  insurer,
  onClose,
  onSaved,
}: {
  open: boolean;
  insurer: Insurer | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [form, setForm] = useState({
    code: "",
    name: "",
    payer_id: "",
    contact_email: "",
    a: "0.7",
    p: "0.2",
    d: "0.1",
  });
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setError(null);
    setForm(
      insurer
        ? {
            code: insurer.code,
            name: insurer.name,
            payer_id: insurer.payer_id,
            contact_email: insurer.contact_email,
            a: String(Number(insurer.approval_rate)),
            p: String(Number(insurer.partial_rate)),
            d: String(Number(insurer.denial_rate)),
          }
        : { code: "", name: "", payer_id: "", contact_email: "", a: "0.7", p: "0.2", d: "0.1" },
    );
  }, [open, insurer]);

  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  const save = async () => {
    if (![form.a, form.p, form.d].every((r) => RATE.test(r)))
      return setError("Rates are fractions between 0 and 1");
    const rates = { approval_rate: form.a, partial_rate: form.p, denial_rate: form.d };
    const result = insurer
      ? await api.PATCH("/api/v1/insurers/{insurer_id}", {
          params: { path: { insurer_id: insurer.id } },
          body: { name: form.name, contact_email: form.contact_email, ...rates },
        })
      : await api.POST("/api/v1/insurers", {
          body: {
            code: form.code,
            name: form.name,
            payer_id: form.payer_id,
            contact_email: form.contact_email,
            ...rates,
          },
        });
    if (!result.data) return setError(errorMessage(result.error, "Could not save insurer"));
    toast.success(`Saved ${result.data.name}`);
    onSaved();
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{insurer ? `Edit ${insurer.name}` : "New insurer"}</DialogTitle>
          <DialogDescription>
            Mock adjudication rates decide how the simulated insurer responds. They must add up to 1.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="flex flex-col gap-2">
            <Label htmlFor="ins-code">Code</Label>
            <Input id="ins-code" value={form.code} onChange={set("code")} disabled={!!insurer} />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="ins-payer">Payer ID</Label>
            <Input id="ins-payer" value={form.payer_id} onChange={set("payer_id")} disabled={!!insurer} />
          </div>
          <div className="flex flex-col gap-2 sm:col-span-2">
            <Label htmlFor="ins-name">Name</Label>
            <Input id="ins-name" value={form.name} onChange={set("name")} />
          </div>
          <div className="flex flex-col gap-2 sm:col-span-2">
            <Label htmlFor="ins-email">Claims email</Label>
            <Input id="ins-email" type="email" value={form.contact_email} onChange={set("contact_email")} />
          </div>
          {(
            [
              ["a", "Approval rate"],
              ["p", "Partial rate"],
              ["d", "Denial rate"],
            ] as const
          ).map(([k, label]) => (
            <div key={k} className="flex flex-col gap-2">
              <Label htmlFor={`ins-${k}`}>{label}</Label>
              <Input id={`ins-${k}`} inputMode="decimal" value={form[k]} onChange={set(k)} />
            </div>
          ))}
        </div>
        {error && (
          <p role="alert" className="text-destructive text-sm">
            {error}
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={() => void save()}>Save</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default function InsurersPage() {
  const { roles } = useAuth();
  const canManage = can(roles, "manageInsurers");
  const [insurers, setInsurers] = useState<Insurer[]>([]);
  const [editing, setEditing] = useState<Insurer | null>(null);
  const [open, setOpen] = useState(false);

  const load = useCallback(async () => {
    const { data } = await api.GET("/api/v1/insurers");
    setInsurers(data ?? []);
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  const toggle = async (i: Insurer) => {
    const { data, error } = await api.PATCH("/api/v1/insurers/{insurer_id}", {
      params: { path: { insurer_id: i.id } },
      body: { is_active: !i.is_active },
    });
    if (!data) return void toast.error(errorMessage(error, "Could not update insurer"));
    void load();
  };

  return (
    <>
      <PageHeader
        title="Insurers"
        description="Payers (fictional) and how the mock insurer adjudicates their claims."
        actions={
          canManage ? (
            <Button
              onClick={() => {
                setEditing(null);
                setOpen(true);
              }}
            >
              <Plus /> New insurer
            </Button>
          ) : undefined
        }
      />
      <div className="bg-card overflow-x-auto rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Code</TableHead>
              <TableHead>Name</TableHead>
              <TableHead>Payer ID</TableHead>
              <TableHead>Approve / partial / deny</TableHead>
              <TableHead>Status</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {insurers.map((i) => (
              <TableRow key={i.id}>
                <TableCell className="font-mono text-sm">{i.code}</TableCell>
                <TableCell>
                  {i.name}
                  <span className="text-muted-foreground block text-xs">{i.contact_email}</span>
                </TableCell>
                <TableCell className="font-mono text-xs">{i.payer_id || "—"}</TableCell>
                <TableCell className="tabular-nums">
                  {pct(i.approval_rate)} / {pct(i.partial_rate)} / {pct(i.denial_rate)}
                </TableCell>
                <TableCell>
                  {i.is_active ? (
                    <Badge variant="outline">Active</Badge>
                  ) : (
                    <Badge variant="secondary">Inactive</Badge>
                  )}
                </TableCell>
                <TableCell className="text-right">
                  {canManage && (
                    <span className="flex justify-end gap-1">
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => {
                          setEditing(i);
                          setOpen(true);
                        }}
                      >
                        Edit
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => void toggle(i)}>
                        {i.is_active ? "Deactivate" : "Activate"}
                      </Button>
                    </span>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <InsurerDialog
        open={open}
        insurer={editing}
        onClose={() => setOpen(false)}
        onSaved={() => {
          setOpen(false);
          void load();
        }}
      />
    </>
  );
}
