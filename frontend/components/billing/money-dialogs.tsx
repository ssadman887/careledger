"use client";

import { useEffect, useState, type ReactNode } from "react";
import { toast } from "sonner";

import { Money } from "@/components/money";
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
import { api, errorMessage, type Schemas } from "@/lib/api/client";
import { useIdempotencyKey } from "@/lib/idempotency";
import { MONEY_INPUT_PATTERN, toCents } from "@/lib/money";

type Method = "cash" | "card" | "bank_transfer";
const METHODS: { value: Method; label: string }[] = [
  { value: "cash", label: "Cash" },
  { value: "card", label: "Card (mock)" },
  { value: "bank_transfer", label: "Bank transfer" },
];
const today = () => new Date().toISOString().slice(0, 10);

function Field({
  id,
  label,
  children,
  hint,
}: {
  id: string;
  label: string;
  children: ReactNode;
  hint?: string;
}) {
  return (
    <div className="flex flex-col gap-2">
      <Label htmlFor={id}>{label}</Label>
      {children}
      {hint && <p className="text-muted-foreground text-xs">{hint}</p>}
    </div>
  );
}

function amountError(amount: string): string | null {
  if (!MONEY_INPUT_PATTERN.test(amount.trim())) return "Enter an amount like 125.00";
  if ((toCents(amount) ?? 0n) <= 0n) return "Amount must be positive";
  return null;
}

/** Record a payment against an invoice, or a deposit on account (no invoice). */
export function PaymentDialog({
  open,
  onClose,
  onDone,
  invoice,
  patientId,
}: {
  open: boolean;
  onClose: () => void;
  onDone: (p: Schemas["PaymentOut"]) => void;
  invoice?: Schemas["InvoiceOut"];
  patientId?: number;
}) {
  const isDeposit = !invoice;
  const idem = useIdempotencyKey();
  const [method, setMethod] = useState<Method>("cash");
  const [amount, setAmount] = useState("");
  const [receivedOn, setReceivedOn] = useState(today());
  const [reference, setReference] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      idem.reset();
      setAmount(invoice ? invoice.patient_due : "");
      setMethod("cash");
      setReference("");
      setReceivedOn(today());
      setError(null);
    }
  }, [open, invoice, idem]);

  const submit = async () => {
    const problem =
      amountError(amount) ??
      (method === "card" && !/^\d{4}$/.test(reference) ? "Enter the card's last 4 digits" : null);
    if (problem) return setError(problem);
    setBusy(true);
    const { data, error: apiError } = await api.POST("/api/v1/payments", {
      params: { header: { "Idempotency-Key": idem.key() } },
      body: {
        invoice_id: invoice?.id ?? null,
        patient_id: isDeposit ? (patientId ?? null) : null,
        method,
        amount: amount.trim(),
        received_on: receivedOn,
        reference,
      },
    });
    setBusy(false);
    if (!data) return setError(errorMessage(apiError, "Payment failed"));
    toast.success(`${data.payment_number} recorded`);
    idem.reset();
    onDone(data);
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {isDeposit ? "Record deposit" : `Record payment for ${invoice.invoice_number}`}
          </DialogTitle>
          <DialogDescription>
            {isDeposit ? (
              "Money received in advance is held as a patient deposit (a liability) until applied."
            ) : (
              <>
                Patient owes: <Money value={invoice.patient_due} />
                {invoice.insurance_pending !== "0.00" && (
                  <>
                    {" "}
                    (plus <Money value={invoice.insurance_pending} /> pending with the insurer)
                  </>
                )}
              </>
            )}
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field id="pay-method" label="Method">
            <Select value={method} onValueChange={(v) => setMethod(v as Method)}>
              <SelectTrigger id="pay-method" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {METHODS.map((m) => (
                  <SelectItem key={m.value} value={m.value}>
                    {m.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          <Field id="pay-amount" label="Amount">
            <Input
              id="pay-amount"
              inputMode="decimal"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
            />
          </Field>
          <Field id="pay-date" label="Received on">
            <Input
              id="pay-date"
              type="date"
              value={receivedOn}
              onChange={(e) => setReceivedOn(e.target.value)}
            />
          </Field>
          {method !== "cash" && (
            <Field
              id="pay-ref"
              label={method === "card" ? "Card last 4 digits" : "Bank reference"}
              hint={method === "card" ? "Mock card payment. Never enter a full card number." : undefined}
            >
              <Input
                id="pay-ref"
                value={reference}
                maxLength={method === "card" ? 4 : 100}
                inputMode={method === "card" ? "numeric" : "text"}
                onChange={(e) => setReference(e.target.value)}
              />
            </Field>
          )}
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
          <Button onClick={() => void submit()} disabled={busy}>
            {busy ? "Saving…" : isDeposit ? "Record deposit" : "Record payment"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function ApplyDepositDialog({
  open,
  onClose,
  onDone,
  invoice,
  depositBalance,
}: {
  open: boolean;
  onClose: () => void;
  onDone: () => void;
  invoice: Schemas["InvoiceOut"];
  depositBalance: string;
}) {
  const idem = useIdempotencyKey();
  const [amount, setAmount] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      idem.reset();
      setError(null);
      setAmount(
        (toCents(depositBalance) ?? 0n) < (toCents(invoice.balance_due) ?? 0n)
          ? depositBalance
          : invoice.balance_due,
      );
    }
  }, [open, depositBalance, invoice, idem]);

  const submit = async () => {
    const problem = amountError(amount);
    if (problem) return setError(problem);
    setBusy(true);
    const { data, error: apiError } = await api.POST("/api/v1/invoices/{invoice_id}/apply-deposit", {
      params: { path: { invoice_id: invoice.id }, header: { "Idempotency-Key": idem.key() } },
      body: { amount: amount.trim() },
    });
    setBusy(false);
    if (!data) return setError(errorMessage(apiError, "Could not apply deposit"));
    toast.success(`Applied ${data.amount} from deposit`);
    idem.reset();
    onDone();
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Apply deposit to {invoice.invoice_number}</DialogTitle>
          <DialogDescription>
            Deposit available: <Money value={depositBalance} /> · Balance due:{" "}
            <Money value={invoice.balance_due} />
          </DialogDescription>
        </DialogHeader>
        <Field id="dep-amount" label="Amount to apply">
          <Input
            id="dep-amount"
            inputMode="decimal"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
          />
        </Field>
        {error && (
          <p role="alert" className="text-destructive text-sm">
            {error}
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={() => void submit()} disabled={busy}>
            Apply deposit
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function RefundDialog({
  open,
  onClose,
  onDone,
  payment,
}: {
  open: boolean;
  onClose: () => void;
  onDone: (r: Schemas["RefundOut"]) => void;
  payment: Schemas["PaymentOut"] | null;
}) {
  const idem = useIdempotencyKey();
  const [amount, setAmount] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      idem.reset();
      setAmount("");
      setReason("");
      setError(null);
    }
  }, [open, idem]);

  if (!payment) return null;
  const submit = async () => {
    const problem = amountError(amount) ?? (reason.trim() ? null : "A reason is required");
    if (problem) return setError(problem);
    setBusy(true);
    const { data, error: apiError } = await api.POST("/api/v1/payments/{payment_id}/refunds", {
      params: { path: { payment_id: payment.id }, header: { "Idempotency-Key": idem.key() } },
      body: { amount: amount.trim(), reason },
    });
    setBusy(false);
    if (!data) return setError(errorMessage(apiError, "Refund failed"));
    toast.success(
      data.status === "pending_approval"
        ? `${data.refund_number} sent for finance-manager approval`
        : `${data.refund_number} refunded`,
    );
    idem.reset();
    onDone(data);
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Refund {payment.payment_number}</DialogTitle>
          <DialogDescription>
            Paid <Money value={payment.amount} />, already refunded <Money value={payment.refunded_amount} />.
            Large refunds need finance-manager approval.
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-4">
          <Field id="refund-amount" label="Amount">
            <Input
              id="refund-amount"
              inputMode="decimal"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
            />
          </Field>
          <Field id="refund-reason" label="Reason">
            <Textarea
              id="refund-reason"
              rows={2}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          </Field>
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
          <Button onClick={() => void submit()} disabled={busy}>
            Request refund
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
