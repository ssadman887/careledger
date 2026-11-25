"use client";

import { ArrowLeft, FileDown, Wallet } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { InvoiceClaims } from "@/components/billing/invoice-claims";
import { ApplyDepositDialog, PaymentDialog, RefundDialog } from "@/components/billing/money-dialogs";
import { Money } from "@/components/money";
import { PageHeader } from "@/components/page-header";
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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { api, errorMessage, type Schemas } from "@/lib/api/client";
import { openInvoicePdf, openReceiptPdf } from "@/lib/api/download";
import { useAuth } from "@/lib/auth/auth-context";
import { formatDateTime, humanize } from "@/lib/format";
import { toCents } from "@/lib/money";
import { can } from "@/lib/permissions";

import { LineEditor } from "./line-editor";

type Invoice = Schemas["InvoiceOut"];
type Payment = Schemas["PaymentOut"];

export default function InvoicePage() {
  const { id } = useParams<{ id: string }>();
  const invoiceId = Number(id);
  const { roles } = useAuth();
  const canBill = can(roles, "bill");
  const [invoice, setInvoice] = useState<Invoice | null>(null);
  const [payments, setPayments] = useState<Payment[]>([]);
  const [depositBalance, setDepositBalance] = useState("0.00");
  const [dialog, setDialog] = useState<"pay" | "deposit" | "void" | "issue" | "writeoff" | null>(null);
  const [woAmount, setWoAmount] = useState("");
  const [refundFor, setRefundFor] = useState<Payment | null>(null);
  const [reason, setReason] = useState("");
  const [issueDate, setIssueDate] = useState(new Date().toISOString().slice(0, 10));
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const inv = await api.GET("/api/v1/invoices/{invoice_id}", {
      params: { path: { invoice_id: invoiceId } },
    });
    if (!inv.data) return void toast.error(errorMessage(inv.error, "Invoice not found"));
    setInvoice(inv.data);
    const [pays, patient] = await Promise.all([
      api.GET("/api/v1/invoices/{invoice_id}/payments", { params: { path: { invoice_id: invoiceId } } }),
      api.GET("/api/v1/patients/{patient_id}", { params: { path: { patient_id: inv.data.patient_id } } }),
    ]);
    setPayments(pays.data ?? []);
    setDepositBalance(patient.data?.deposit_balance ?? "0.00");
  }, [invoiceId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (!invoice) return <p className="text-muted-foreground">Loading…</p>;

  const path = { params: { path: { invoice_id: invoice.id } } };
  const isDraft = invoice.status === "draft";
  const payable = invoice.status === "issued" || invoice.status === "partially_paid";
  const hasDeposit = (toCents(depositBalance) ?? 0n) > 0n;

  const issue = async () => {
    setBusy(true);
    const { data, error } = await api.POST("/api/v1/invoices/{invoice_id}/issue", {
      ...path,
      body: { invoice_date: issueDate },
    });
    setBusy(false);
    if (!data) return void toast.error(errorMessage(error, "Could not issue invoice"));
    toast.success(`${data.invoice_number} issued and posted to the ledger`);
    setDialog(null);
    setInvoice(data);
  };
  const writeOff = async () => {
    setBusy(true);
    const { data, error } = await api.POST("/api/v1/ar/write-offs", {
      body: { invoice_id: invoice.id, amount: woAmount.trim(), reason },
    });
    setBusy(false);
    if (!data) return void toast.error(errorMessage(error, "Write-off failed"));
    toast.success(
      data.status === "pending_approval"
        ? `${data.write_off_number} sent for finance-manager approval`
        : `${data.write_off_number} posted`,
    );
    setDialog(null);
    setReason("");
    void load();
  };
  const voidInvoice = async () => {
    setBusy(true);
    const { data, error } = await api.POST("/api/v1/invoices/{invoice_id}/void", {
      ...path,
      body: { reason },
    });
    setBusy(false);
    if (!data) return void toast.error(errorMessage(error, "Could not void invoice"));
    toast.success(data.void_entry_id ? "Invoice voided; reversing entry posted" : "Draft voided");
    setDialog(null);
    setReason("");
    void load();
  };

  return (
    <>
      <Button asChild variant="ghost" size="sm" className="mb-2 -ml-2">
        <Link href="/invoices">
          <ArrowLeft /> Invoices
        </Link>
      </Button>
      <PageHeader
        title={invoice.invoice_number}
        description={`${invoice.patient_name} · ${invoice.patient_mrn}${invoice.visit_number ? ` · visit ${invoice.visit_number}` : ""}`}
        actions={
          <>
            <Button variant="outline" onClick={() => void openInvoicePdf(invoice.id, invoice.invoice_number)}>
              <FileDown /> PDF
            </Button>
            {canBill && isDraft && (
              <Button onClick={() => setDialog("issue")} disabled={(toCents(invoice.total) ?? 0n) <= 0n}>
                Issue invoice
              </Button>
            )}
            {canBill && payable && (
              <>
                {hasDeposit && (
                  <Button variant="outline" onClick={() => setDialog("deposit")}>
                    <Wallet /> Apply deposit
                  </Button>
                )}
                <Button onClick={() => setDialog("pay")}>Record payment</Button>
              </>
            )}
            {can(roles, "collections") && payable && (toCents(invoice.patient_due) ?? 0n) > 0n && (
              <Button
                variant="outline"
                onClick={() => {
                  setWoAmount(invoice.patient_due);
                  setReason("");
                  setDialog("writeoff");
                }}
              >
                Write off
              </Button>
            )}
            {can(roles, "voidInvoice") && invoice.status !== "void" && (
              <Button variant="outline" onClick={() => setDialog("void")}>
                Void
              </Button>
            )}
          </>
        }
      />

      <div className="mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
        {(
          [
            ["Status", <StatusBadge key="s" status={invoice.status} />],
            ["Total", <Money key="t" value={invoice.total} />],
            [
              "Paid / adjusted",
              <span key="p">
                <Money value={invoice.amount_paid} /> / <Money value={invoice.adjusted_amount} />
              </span>,
            ],
            ["Pending with insurer", <Money key="i" value={invoice.insurance_pending} />],
            ["Patient owes", <Money key="b" value={invoice.patient_due} className="font-semibold" />],
          ] as const
        ).map(([label, value]) => (
          <Card key={label}>
            <CardHeader>
              <CardTitle className="text-muted-foreground text-sm font-normal">{label}</CardTitle>
            </CardHeader>
            <CardContent className="text-xl">{value}</CardContent>
          </Card>
        ))}
      </div>

      <div className="grid gap-6 xl:grid-cols-[1fr_320px]">
        <div className="flex flex-col gap-6">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">{isDraft ? "Charge capture" : "Charges"}</CardTitle>
            </CardHeader>
            <CardContent className="overflow-x-auto">
              {isDraft && canBill && <LineEditor invoice={invoice} onSaved={setInvoice} />}
              <Table className={isDraft && canBill ? "mt-6" : ""}>
                <TableHeader>
                  <TableRow>
                    <TableHead>#</TableHead>
                    <TableHead>Description</TableHead>
                    <TableHead>Date</TableHead>
                    <TableHead className="text-right">Qty</TableHead>
                    <TableHead className="text-right">Unit</TableHead>
                    <TableHead className="text-right">Discount</TableHead>
                    <TableHead className="text-right">Tax</TableHead>
                    <TableHead className="text-right">Total</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {invoice.lines.length === 0 && (
                    <TableRow>
                      <TableCell colSpan={8} className="text-muted-foreground text-center">
                        No saved charges
                      </TableCell>
                    </TableRow>
                  )}
                  {invoice.lines.map((l) => (
                    <TableRow key={l.line_no}>
                      <TableCell>{l.line_no}</TableCell>
                      <TableCell>{l.description}</TableCell>
                      <TableCell>{l.service_date}</TableCell>
                      <TableCell className="text-right tabular-nums">{String(Number(l.quantity))}</TableCell>
                      <TableCell className="text-right">
                        <Money value={l.unit_price} />
                      </TableCell>
                      <TableCell className="text-right">
                        <Money value={l.discount_amount} hideZero />
                      </TableCell>
                      <TableCell className="text-right">
                        <Money value={l.tax_amount} hideZero />
                      </TableCell>
                      <TableCell className="text-right">
                        <Money value={l.line_total} />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              <dl className="mt-4 ml-auto grid w-64 grid-cols-2 gap-1 text-sm">
                <dt className="text-muted-foreground">Subtotal</dt>
                <dd className="text-right">
                  <Money value={invoice.subtotal} />
                </dd>
                <dt className="text-muted-foreground">Discounts</dt>
                <dd className="text-right">
                  <Money value={invoice.discount_total} />
                </dd>
                <dt className="text-muted-foreground">Tax</dt>
                <dd className="text-right">
                  <Money value={invoice.tax_total} />
                </dd>
                <dt className="font-medium">Total</dt>
                <dd className="text-right font-medium">
                  <Money value={invoice.total} />
                </dd>
              </dl>
            </CardContent>
          </Card>

          <InvoiceClaims invoice={invoice} />

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Payments</CardTitle>
            </CardHeader>
            <CardContent className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Payment</TableHead>
                    <TableHead>Date</TableHead>
                    <TableHead>Method</TableHead>
                    <TableHead>Reference</TableHead>
                    <TableHead className="text-right">Amount</TableHead>
                    <TableHead className="text-right">Refunded</TableHead>
                    <TableHead />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {payments.length === 0 && (
                    <TableRow>
                      <TableCell colSpan={7} className="text-muted-foreground text-center">
                        No payments yet
                      </TableCell>
                    </TableRow>
                  )}
                  {payments.map((p) => (
                    <TableRow key={p.id}>
                      <TableCell className="font-mono text-sm">{p.payment_number}</TableCell>
                      <TableCell>{p.received_on}</TableCell>
                      <TableCell>{humanize(p.method)}</TableCell>
                      <TableCell className="font-mono text-xs">{p.reference || "—"}</TableCell>
                      <TableCell className="text-right">
                        <Money value={p.amount} />
                      </TableCell>
                      <TableCell className="text-right">
                        <Money value={p.refunded_amount} hideZero />
                      </TableCell>
                      <TableCell className="text-right whitespace-nowrap">
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => void openReceiptPdf(p.id, p.payment_number)}
                        >
                          Receipt
                        </Button>
                        {canBill && (toCents(p.refunded_amount) ?? 0n) < (toCents(p.amount) ?? 0n) && (
                          <Button size="sm" variant="ghost" onClick={() => setRefundFor(p)}>
                            Refund
                          </Button>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </div>

        <Card className="h-fit">
          <CardHeader>
            <CardTitle className="text-base">Details</CardTitle>
          </CardHeader>
          <CardContent>
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
              <dt className="text-muted-foreground">Patient</dt>
              <dd>
                <Link className="hover:underline" href={`/patients/${invoice.patient_id}`}>
                  {invoice.patient_name}
                </Link>
              </dd>
              <dt className="text-muted-foreground">Invoice date</dt>
              <dd>{invoice.invoice_date ?? "—"}</dd>
              <dt className="text-muted-foreground">Due date</dt>
              <dd>{invoice.due_date ?? "—"}</dd>
              <dt className="text-muted-foreground">Issued</dt>
              <dd>{formatDateTime(invoice.issued_at)}</dd>
              <dt className="text-muted-foreground">Deposit available</dt>
              <dd>
                <Money value={depositBalance} />
              </dd>
              {invoice.issue_entry_id && (
                <>
                  <dt className="text-muted-foreground">Ledger</dt>
                  <dd>
                    {can(roles, "readLedger") ? (
                      <>
                        <Link className="hover:underline" href={`/journal/${invoice.issue_entry_id}`}>
                          Issue entry
                        </Link>
                        {invoice.void_entry_id && (
                          <>
                            {" · "}
                            <Link className="hover:underline" href={`/journal/${invoice.void_entry_id}`}>
                              Reversal
                            </Link>
                          </>
                        )}
                      </>
                    ) : (
                      <span>{invoice.void_entry_id ? "Posted and reversed" : "Posted to ledger"}</span>
                    )}
                  </dd>
                </>
              )}
              {invoice.void_reason && (
                <>
                  <dt className="text-muted-foreground">Void reason</dt>
                  <dd>{invoice.void_reason}</dd>
                </>
              )}
              {invoice.notes && (
                <>
                  <dt className="text-muted-foreground">Notes</dt>
                  <dd>{invoice.notes}</dd>
                </>
              )}
            </dl>
          </CardContent>
        </Card>
      </div>

      <PaymentDialog
        open={dialog === "pay"}
        invoice={invoice}
        onClose={() => setDialog(null)}
        onDone={() => {
          setDialog(null);
          void load();
        }}
      />
      <ApplyDepositDialog
        open={dialog === "deposit"}
        invoice={invoice}
        depositBalance={depositBalance}
        onClose={() => setDialog(null)}
        onDone={() => {
          setDialog(null);
          void load();
        }}
      />
      <RefundDialog
        open={refundFor !== null}
        payment={refundFor}
        onClose={() => setRefundFor(null)}
        onDone={() => {
          setRefundFor(null);
          void load();
        }}
      />
      <Dialog open={dialog === "issue"} onOpenChange={(o) => !o && setDialog(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Issue {invoice.invoice_number}</DialogTitle>
            <DialogDescription>
              Posts <Money value={invoice.total} /> to Accounts Receivable and departmental revenue. Charges
              are then frozen.
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-2">
            <Label htmlFor="issue-date">Invoice date</Label>
            <Input
              id="issue-date"
              type="date"
              value={issueDate}
              onChange={(e) => setIssueDate(e.target.value)}
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialog(null)}>
              Cancel
            </Button>
            <Button onClick={() => void issue()} disabled={busy}>
              Issue and post
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <Dialog open={dialog === "writeoff"} onOpenChange={(o) => !o && setDialog(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Write off patient balance</DialogTitle>
            <DialogDescription>
              Posts Dr Bad Debt Expense / Cr AR-Patients once a finance manager approves. Patient owes{" "}
              <Money value={invoice.patient_due} />.
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-3">
            <div className="flex flex-col gap-2">
              <Label htmlFor="wo-amount">Amount</Label>
              <Input
                id="wo-amount"
                inputMode="decimal"
                value={woAmount}
                onChange={(e) => setWoAmount(e.target.value)}
              />
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="wo-reason">Reason</Label>
              <Textarea id="wo-reason" rows={2} value={reason} onChange={(e) => setReason(e.target.value)} />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialog(null)}>
              Cancel
            </Button>
            <Button onClick={() => void writeOff()} disabled={busy || !reason.trim() || !woAmount.trim()}>
              Request write-off
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <Dialog open={dialog === "void"} onOpenChange={(o) => !o && setDialog(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Void {invoice.invoice_number}</DialogTitle>
            <DialogDescription>
              {isDraft
                ? "The draft will be cancelled."
                : "A reversing journal entry will be posted. Refund any payments first."}
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-2">
            <Label htmlFor="void-reason">Reason</Label>
            <Textarea id="void-reason" rows={2} value={reason} onChange={(e) => setReason(e.target.value)} />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialog(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={() => void voidInvoice()}
              disabled={busy || !reason.trim()}
            >
              Void invoice
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
