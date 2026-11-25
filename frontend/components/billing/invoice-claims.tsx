"use client";

import { ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { Money } from "@/components/money";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { api, errorMessage, type Schemas } from "@/lib/api/client";
import { useAuth } from "@/lib/auth/auth-context";
import { can } from "@/lib/permissions";

type Invoice = Schemas["InvoiceOut"];
type Preview = Schemas["CoveragePreviewOut"];
const OPEN = ["draft", "submitted", "under_review", "approved", "partially_approved", "denied", "appealed"];

function PreviewTable({ p }: { p: Preview }) {
  const rows: [string, string][] = [
    ["Billed", p.billed],
    ["Copay (patient)", p.copay],
    ["Deductible (patient)", p.deductible],
    ["Coinsurance (patient)", p.coinsurance],
    ["Over limit / already paid (patient)", p.over_limit],
  ];
  return (
    <dl className="grid grid-cols-[1fr_auto] gap-x-6 gap-y-1 text-sm">
      {rows.map(([label, value]) => (
        <div key={label} className="contents">
          <dt className="text-muted-foreground">{label}</dt>
          <dd className="text-right">
            <Money value={value} />
          </dd>
        </div>
      ))}
      <dt className="border-t pt-1 font-medium">Insurer pays</dt>
      <dd className="border-t pt-1 text-right font-medium">
        <Money value={p.insurer_amount} />
      </dd>
      <dt className="font-medium">Patient pays</dt>
      <dd className="text-right font-medium">
        <Money value={p.patient_amount} />
      </dd>
    </dl>
  );
}

/** Insurance section of an invoice: its claims and the "create claim" flow with a preview. */
export function InvoiceClaims({ invoice }: { invoice: Invoice }) {
  const router = useRouter();
  const { roles } = useAuth();
  const [claims, setClaims] = useState<Schemas["ClaimSummaryOut"][]>([]);
  const [policies, setPolicies] = useState<Schemas["PolicyOut"][]>([]);
  const [open, setOpen] = useState(false);
  const [policyId, setPolicyId] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const [c, p] = await Promise.all([
      api.GET("/api/v1/claims", { params: { query: { invoice_id: invoice.id, page_size: 20 } } }),
      api.GET("/api/v1/policies", {
        params: { query: { patient_id: invoice.patient_id, active_only: true } },
      }),
    ]);
    setClaims(c.data?.items ?? []);
    setPolicies(p.data?.items ?? []);
  }, [invoice.id, invoice.patient_id]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!open || !policyId) return setPreview(null);
    setPreviewError(null);
    void api
      .GET("/api/v1/claims/preview", {
        params: { query: { invoice_id: invoice.id, policy_id: Number(policyId) } },
      })
      .then(({ data, error }) => {
        setPreview(data ?? null);
        if (!data) setPreviewError(errorMessage(error, "Policy cannot cover this invoice"));
      });
  }, [open, policyId, invoice.id]);

  const claimable =
    (invoice.status === "issued" || invoice.status === "partially_paid") &&
    !claims.some((c) => OPEN.includes(c.status)) &&
    policies.length > 0;

  const create = async () => {
    const { data, error } = await api.POST("/api/v1/claims", {
      body: { invoice_id: invoice.id, policy_id: Number(policyId) },
    });
    if (!data) return void toast.error(errorMessage(error, "Could not create claim"));
    toast.success(`Claim ${data.claim_number} drafted`);
    router.push(`/claims/${data.id}`);
  };

  if (claims.length === 0 && !claimable) return null;

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle className="text-base">Insurance</CardTitle>
        {claimable && can(roles, "draftClaim") && (
          <Button
            size="sm"
            onClick={() => {
              setPolicyId(policies.length === 1 ? String(policies[0]?.id) : "");
              setOpen(true);
            }}
          >
            <ShieldCheck /> Create claim
          </Button>
        )}
      </CardHeader>
      <CardContent>
        {claims.length === 0 ? (
          <p className="text-muted-foreground text-sm">No claims yet. The patient has an active policy.</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {claims.map((c) => (
              <li
                key={c.id}
                className="flex flex-wrap items-center justify-between gap-2 rounded-md border px-3 py-2 text-sm"
              >
                <Link href={`/claims/${c.id}`} className="font-mono hover:underline">
                  {c.claim_number}
                </Link>
                <span className="text-muted-foreground">{c.insurer_name}</span>
                <StatusBadge status={c.status} />
                <span>
                  Insurer <Money value={c.insurer_amount} />
                </span>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
      <Dialog open={open} onOpenChange={(o) => !o && setOpen(false)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create claim for {invoice.invoice_number}</DialogTitle>
            <DialogDescription>
              Copay, deductible, coverage percent and the annual limit decide the split. Nothing is posted
              until submission.
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-2">
            <Label htmlFor="claim-policy">Policy</Label>
            <Select value={policyId} onValueChange={setPolicyId}>
              <SelectTrigger id="claim-policy" className="w-full">
                <SelectValue placeholder="Choose policy" />
              </SelectTrigger>
              <SelectContent>
                {policies.map((p) => (
                  <SelectItem key={p.id} value={String(p.id)}>
                    {p.insurer_name} · {p.plan_name} · {p.policy_number}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          {preview && <PreviewTable p={preview} />}
          {previewError && (
            <p role="alert" className="text-destructive text-sm">
              {previewError}
            </p>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button onClick={() => void create()} disabled={!preview || preview.insurer_amount === "0.00"}>
              Draft claim
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
