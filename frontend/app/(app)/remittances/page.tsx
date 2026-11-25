"use client";

import { FileDown, Upload } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { Money } from "@/components/money";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status-badge";
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
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api, errorMessage, type Schemas } from "@/lib/api/client";
import { useAuth } from "@/lib/auth/auth-context";
import { can } from "@/lib/permissions";

type Remittance = Schemas["RemittanceSummaryOut"];
const SAMPLE =
  "claim_number,paid_amount,remark\nCLM-000001,840.00,Paid per contract\nCLM-000002,120.50,Reduced per fee schedule\n";

function ImportDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const router = useRouter();
  const [insurers, setInsurers] = useState<Schemas["InsurerOut"][]>([]);
  const [insurerId, setInsurerId] = useState("");
  const [reference, setReference] = useState("");
  const [paymentDate, setPaymentDate] = useState(new Date().toISOString().slice(0, 10));
  const [expected, setExpected] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open) void api.GET("/api/v1/insurers").then(({ data }) => setInsurers(data ?? []));
  }, [open]);

  const submit = async () => {
    if (!insurerId || !reference.trim() || !file)
      return setError("Insurer, payer reference and CSV file are required");
    setBusy(true);
    const { data, error: apiError } = await api.POST("/api/v1/remittances", {
      body: {
        insurer_id: Number(insurerId),
        reference: reference.trim(),
        payment_date: paymentDate,
        expected_total: expected.trim() || null,
        file: file as unknown as string,
      },
      bodySerializer: (body) => {
        const form = new FormData();
        form.append("insurer_id", String(body.insurer_id));
        form.append("reference", body.reference);
        form.append("payment_date", body.payment_date);
        if (body.expected_total) form.append("expected_total", body.expected_total);
        form.append("file", body.file as unknown as Blob, file.name);
        return form;
      },
    });
    setBusy(false);
    if (!data) {
      const details = (apiError as { error?: { details?: { errors?: string[] } } } | undefined)?.error
        ?.details?.errors;
      return setError(
        `${errorMessage(apiError, "Import failed")}${details ? `: ${details.slice(0, 3).join("; ")}` : ""}`,
      );
    }
    toast.success(
      `${data.remittance_number} imported: ${data.counts.matched ?? 0} matched, ${data.counts.unmatched ?? 0} unmatched`,
    );
    router.push(`/remittances/${data.id}`);
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Import remittance</DialogTitle>
          <DialogDescription>
            Upload the insurer&apos;s payment advice as CSV (<code>claim_number,paid_amount,remark</code>).
            Lines are reconciled against claims; nothing posts until you review and post.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="flex flex-col gap-2 sm:col-span-2">
            <Label htmlFor="rem-insurer">Insurer</Label>
            <Select value={insurerId} onValueChange={setInsurerId}>
              <SelectTrigger id="rem-insurer" className="w-full">
                <SelectValue placeholder="Choose insurer" />
              </SelectTrigger>
              <SelectContent>
                {insurers.map((i) => (
                  <SelectItem key={i.id} value={String(i.id)}>
                    {i.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="rem-ref">Payer reference (EFT / cheque)</Label>
            <Input id="rem-ref" value={reference} onChange={(e) => setReference(e.target.value)} />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="rem-date">Payment date</Label>
            <Input
              id="rem-date"
              type="date"
              value={paymentDate}
              onChange={(e) => setPaymentDate(e.target.value)}
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="rem-total">EFT total (optional check)</Label>
            <Input
              id="rem-total"
              inputMode="decimal"
              value={expected}
              onChange={(e) => setExpected(e.target.value)}
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="rem-file">CSV file</Label>
            <Input
              id="rem-file"
              type="file"
              accept=".csv,text/csv"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </div>
        </div>
        {error && (
          <p role="alert" className="text-destructive text-sm">
            {error}
          </p>
        )}
        <DialogFooter>
          <Button
            variant="ghost"
            onClick={() => {
              const url = URL.createObjectURL(new Blob([SAMPLE], { type: "text/csv" }));
              const a = document.createElement("a");
              a.href = url;
              a.download = "remittance-sample.csv";
              a.click();
              setTimeout(() => URL.revokeObjectURL(url), 10_000);
            }}
          >
            <FileDown /> Sample CSV
          </Button>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={() => void submit()} disabled={busy}>
            Import and reconcile
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default function RemittancesPage() {
  const { roles } = useAuth();
  const [rows, setRows] = useState<Remittance[]>([]);
  const [open, setOpen] = useState(false);

  const load = useCallback(async () => {
    const { data, error } = await api.GET("/api/v1/remittances", { params: { query: { page_size: 100 } } });
    if (!data) return void toast.error(errorMessage(error, "Could not load remittances"));
    setRows(data.items);
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  return (
    <>
      <PageHeader
        title="Remittances"
        description="Insurer payment advices: import, reconcile against claims, then post to the ledger."
        actions={
          can(roles, "workClaims") ? (
            <Button onClick={() => setOpen(true)}>
              <Upload /> Import CSV
            </Button>
          ) : undefined
        }
      />
      <div className="bg-card overflow-x-auto rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Remittance</TableHead>
              <TableHead>Insurer</TableHead>
              <TableHead>Reference</TableHead>
              <TableHead>Payment date</TableHead>
              <TableHead>Lines</TableHead>
              <TableHead>Status</TableHead>
              <TableHead className="text-right">Total</TableHead>
              <TableHead className="text-right">Posted</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.length === 0 && (
              <TableRow>
                <TableCell colSpan={8} className="text-muted-foreground h-20 text-center">
                  No remittances yet.
                </TableCell>
              </TableRow>
            )}
            {rows.map((r) => (
              <TableRow key={r.id}>
                <TableCell>
                  <Link href={`/remittances/${r.id}`} className="font-mono text-sm hover:underline">
                    {r.remittance_number}
                  </Link>
                </TableCell>
                <TableCell>{r.insurer_name}</TableCell>
                <TableCell className="font-mono text-xs">{r.reference}</TableCell>
                <TableCell>{r.payment_date}</TableCell>
                <TableCell className="text-xs">
                  {r.line_count} · {r.counts.matched ?? 0} matched
                  {(r.counts.short_paid ?? 0) > 0 && ` · ${r.counts.short_paid} short`}
                  {(r.counts.unmatched ?? 0) + (r.counts.overpaid ?? 0) > 0 && (
                    <span className="text-destructive">
                      {" "}
                      · {(r.counts.unmatched ?? 0) + (r.counts.overpaid ?? 0)} flagged
                    </span>
                  )}
                </TableCell>
                <TableCell>
                  <StatusBadge status={r.status} />
                </TableCell>
                <TableCell className="text-right">
                  <Money value={r.total_amount} />
                </TableCell>
                <TableCell className="text-right">
                  <Money value={r.posted_amount} />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <ImportDialog open={open} onClose={() => setOpen(false)} />
    </>
  );
}
