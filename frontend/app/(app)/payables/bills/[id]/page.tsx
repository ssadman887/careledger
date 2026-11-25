"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

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
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api, errorMessage, type Schemas } from "@/lib/api/client";
import { useAuth } from "@/lib/auth/auth-context";
import { useIdempotencyKey } from "@/lib/idempotency";
import { MONEY_INPUT_PATTERN } from "@/lib/money";
import { can } from "@/lib/permissions";

type Bill = Schemas["VendorBillOut"];
type Dialogs = "pay" | "schedule" | "void" | null;

export default function BillPage() {
  const { id } = useParams<{ id: string }>();
  const { roles } = useAuth();
  const canManage = can(roles, "managePayables");
  const idem = useIdempotencyKey();
  const [bill, setBill] = useState<Bill | null>(null);
  const [payments, setPayments] = useState<Schemas["VendorPaymentOut"][]>([]);
  const [dialog, setDialog] = useState<Dialogs>(null);
  const [amount, setAmount] = useState("");
  const [method, setMethod] = useState<"bank_transfer" | "cheque">("bank_transfer");
  const [reference, setReference] = useState("");
  const [dateValue, setDateValue] = useState(new Date().toISOString().slice(0, 10));
  const [reason, setReason] = useState("");

  const load = useCallback(async () => {
    const [b, p] = await Promise.all([
      api.GET("/api/v1/vendor-bills/{bill_id}", { params: { path: { bill_id: Number(id) } } }),
      api.GET("/api/v1/vendor-payments", { params: { query: { bill_id: Number(id) } } }),
    ]);
    if (!b.data) return void toast.error(errorMessage(b.error, "Bill not found"));
    setBill(b.data);
    setPayments(p.data?.items ?? []);
  }, [id]);
  useEffect(() => {
    void load();
  }, [load]);
  if (!bill) return <p className="text-muted-foreground">Loading…</p>;

  const path = { params: { path: { bill_id: bill.id } } };
  const payable = bill.status === "approved" || bill.status === "partially_paid";

  const submit = async () => {
    const { data, error } = await api.POST("/api/v1/vendor-bills/{bill_id}/submit", path);
    if (!data) return void toast.error(errorMessage(error, "Could not submit"));
    toast.success(
      data.status === "approved"
        ? `${data.bill_number} approved and posted`
        : `${data.bill_number} sent for approval`,
    );
    setBill(data);
  };
  const confirm = async () => {
    if (dialog === "pay") {
      if (amount && !MONEY_INPUT_PATTERN.test(amount)) return void toast.error("Amount like 120.00");
      const { data, error } = await api.POST("/api/v1/vendor-bills/{bill_id}/pay", {
        params: { path: { bill_id: bill.id }, header: { "Idempotency-Key": idem.key() } },
        body: { amount: amount || null, paid_on: dateValue, method, reference },
      });
      if (!data) return void toast.error(errorMessage(error, "Payment failed"));
      idem.reset();
      toast.success(`${data.payment_number} paid`);
    } else if (dialog === "schedule") {
      const { data, error } = await api.POST("/api/v1/vendor-bills/{bill_id}/schedule", {
        ...path,
        body: { pay_on: dateValue },
      });
      if (!data) return void toast.error(errorMessage(error, "Could not schedule"));
      toast.success(`Scheduled for ${data.scheduled_payment_date}`);
    } else if (dialog === "void") {
      const { data, error } = await api.POST("/api/v1/vendor-bills/{bill_id}/void", {
        ...path,
        body: { reason },
      });
      if (!data) return void toast.error(errorMessage(error, "Could not void"));
      toast.success("Bill voided");
    }
    setDialog(null);
    void load();
  };

  return (
    <>
      <Button asChild variant="ghost" size="sm" className="mb-2 -ml-2">
        <Link href="/payables?tab=bills">
          <ArrowLeft /> Bills
        </Link>
      </Button>
      <PageHeader
        title={bill.bill_number}
        description={`${bill.vendor_name} invoice #${bill.vendor_invoice_number} · billed ${bill.bill_date} · due ${bill.due_date}`}
        actions={
          canManage ? (
            <>
              {bill.status === "draft" && <Button onClick={() => void submit()}>Submit for approval</Button>}
              {payable && (
                <>
                  <Button
                    onClick={() => {
                      setAmount("");
                      setReference("");
                      setDateValue(new Date().toISOString().slice(0, 10));
                      setDialog("pay");
                    }}
                  >
                    Pay
                  </Button>
                  <Button variant="outline" onClick={() => setDialog("schedule")}>
                    Schedule payment
                  </Button>
                </>
              )}
              {(bill.status === "draft" || bill.status === "rejected") && (
                <Button variant="outline" onClick={() => setDialog("void")}>
                  Void
                </Button>
              )}
            </>
          ) : undefined
        }
      />
      <div className="mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {(
          [
            ["Status", <StatusBadge key="s" status={bill.status} />],
            [
              "Three-way match",
              <span key="m" className="flex flex-col gap-1">
                <StatusBadge status={bill.match_status} />
                <span className="text-muted-foreground text-xs">{bill.match_note}</span>
              </span>,
            ],
            ["Total", <Money key="t" value={bill.total} />],
            ["Balance due", <Money key="b" value={bill.balance_due} className="font-semibold" />],
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
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Lines</CardTitle>
          </CardHeader>
          <CardContent className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>#</TableHead>
                  <TableHead>Description</TableHead>
                  <TableHead className="text-right">Qty</TableHead>
                  <TableHead className="text-right">Unit</TableHead>
                  <TableHead className="text-right">Amount</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {bill.lines.map((l) => (
                  <TableRow key={l.line_no}>
                    <TableCell>{l.line_no}</TableCell>
                    <TableCell>{l.description}</TableCell>
                    <TableCell className="text-right tabular-nums">{String(Number(l.quantity))}</TableCell>
                    <TableCell className="text-right">
                      <Money value={l.unit_price} />
                    </TableCell>
                    <TableCell className="text-right">
                      <Money value={l.amount} />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
        <Card className="h-fit">
          <CardHeader>
            <CardTitle className="text-base">Details</CardTitle>
          </CardHeader>
          <CardContent>
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
              <dt className="text-muted-foreground">Purchase order</dt>
              <dd>
                {bill.purchase_order_id ? (
                  <Link
                    className="hover:underline"
                    href={`/payables/purchase-orders/${bill.purchase_order_id}`}
                  >
                    {bill.po_number}
                  </Link>
                ) : (
                  "None"
                )}
              </dd>
              <dt className="text-muted-foreground">Scheduled</dt>
              <dd>{bill.scheduled_payment_date ?? "—"}</dd>
              <dt className="text-muted-foreground">Paid</dt>
              <dd>
                <Money value={bill.amount_paid} />
              </dd>
              {bill.approval_entry_id && can(roles, "readLedger") && (
                <>
                  <dt className="text-muted-foreground">Ledger</dt>
                  <dd>
                    <Link className="hover:underline" href={`/journal/${bill.approval_entry_id}`}>
                      Approval entry
                    </Link>
                  </dd>
                </>
              )}
              {bill.status === "pending_approval" && (
                <>
                  <dt className="text-muted-foreground">Approval</dt>
                  <dd>
                    <Link className="hover:underline" href="/approvals">
                      Waiting in the approvals inbox
                    </Link>
                  </dd>
                </>
              )}
            </dl>
            {payments.length > 0 && (
              <ul className="mt-4 flex flex-col gap-1 border-t pt-3 text-sm">
                {payments.map((p) => (
                  <li key={p.id} className="flex justify-between">
                    <span>
                      {p.payment_number} · {p.paid_on}
                    </span>
                    <Money value={p.amount} />
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>
      <Dialog open={dialog !== null} onOpenChange={(o) => !o && setDialog(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {dialog === "pay" ? "Pay bill" : dialog === "schedule" ? "Schedule payment" : "Void bill"}
            </DialogTitle>
            <DialogDescription>
              {dialog === "pay"
                ? "Posts Dr Accounts Payable / Cr Bank. Leave the amount empty to pay the full balance."
                : dialog === "schedule"
                  ? "The daily payment run (or “Run scheduled payments”) pays the balance on this date."
                  : "Only draft or rejected bills can be voided."}
            </DialogDescription>
          </DialogHeader>
          {dialog === "void" ? (
            <div className="flex flex-col gap-2">
              <Label htmlFor="void-reason">Reason</Label>
              <Input id="void-reason" value={reason} onChange={(e) => setReason(e.target.value)} />
            </div>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="flex flex-col gap-2">
                <Label htmlFor="pay-date">{dialog === "pay" ? "Paid on" : "Pay on"}</Label>
                <Input
                  id="pay-date"
                  type="date"
                  value={dateValue}
                  onChange={(e) => setDateValue(e.target.value)}
                />
              </div>
              {dialog === "pay" && (
                <>
                  <div className="flex flex-col gap-2">
                    <Label htmlFor="pay-amount">Amount</Label>
                    <Input
                      id="pay-amount"
                      inputMode="decimal"
                      placeholder={bill.balance_due}
                      value={amount}
                      onChange={(e) => setAmount(e.target.value)}
                    />
                  </div>
                  <div className="flex flex-col gap-2">
                    <Label htmlFor="pay-method">Method</Label>
                    <Select value={method} onValueChange={(v) => setMethod(v as typeof method)}>
                      <SelectTrigger id="pay-method" className="w-full">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="bank_transfer">Bank transfer</SelectItem>
                        <SelectItem value="cheque">Cheque</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="flex flex-col gap-2">
                    <Label htmlFor="pay-ref">Reference</Label>
                    <Input id="pay-ref" value={reference} onChange={(e) => setReference(e.target.value)} />
                  </div>
                </>
              )}
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialog(null)}>
              Cancel
            </Button>
            <Button onClick={() => void confirm()} disabled={dialog === "void" && !reason.trim()}>
              {dialog === "pay" ? "Record payment" : dialog === "schedule" ? "Schedule" : "Void bill"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
