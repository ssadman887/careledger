"use client";

import { Plus, Wallet } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { Money } from "@/components/money";
import { PageHeader } from "@/components/page-header";
import { APLineEditor, newAPLine, toPayload, type APDraftLine } from "@/components/payables/ap-line-editor";
import { StatusBadge } from "@/components/status-badge";
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
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api, errorMessage, type Schemas } from "@/lib/api/client";
import { useAccounts } from "@/lib/api/hooks";
import { useAuth } from "@/lib/auth/auth-context";
import { can } from "@/lib/permissions";

type Tab = "bills" | "purchase-orders" | "vendors" | "payments";
type Vendor = Schemas["VendorOut"];
const today = () => new Date().toISOString().slice(0, 10);

function useVendors(): { vendors: Vendor[]; reload: () => Promise<void> } {
  const [vendors, setVendors] = useState<Vendor[]>([]);
  const reload = useCallback(async () => {
    const { data } = await api.GET("/api/v1/vendors", { params: { query: { page_size: 200 } } });
    setVendors(data?.items ?? []);
  }, []);
  useEffect(() => {
    void reload();
  }, [reload]);
  return { vendors, reload };
}

function VendorSelect({
  id,
  value,
  onChange,
  vendors,
}: {
  id: string;
  value: string;
  onChange: (v: string) => void;
  vendors: Vendor[];
}) {
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger id={id} className="w-full">
        <SelectValue placeholder="Choose vendor" />
      </SelectTrigger>
      <SelectContent>
        {vendors
          .filter((v) => v.is_active)
          .map((v) => (
            <SelectItem key={v.id} value={String(v.id)}>
              {v.name}
            </SelectItem>
          ))}
      </SelectContent>
    </Select>
  );
}

function NewDocumentDialog({
  kind,
  open,
  onClose,
}: {
  kind: "po" | "bill";
  open: boolean;
  onClose: () => void;
}) {
  const router = useRouter();
  const { vendors } = useVendors();
  const { accounts } = useAccounts();
  const [vendorId, setVendorId] = useState("");
  const [docDate, setDocDate] = useState(today());
  const [invoiceNo, setInvoiceNo] = useState("");
  const [lines, setLines] = useState<APDraftLine[]>([newAPLine()]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setVendorId("");
    setInvoiceNo("");
    setDocDate(today());
    setLines([newAPLine()]);
    setError(null);
  }, [open]);

  useEffect(() => {
    const v = vendors.find((x) => String(x.id) === vendorId);
    if (v?.default_expense_account_id) {
      setLines((ls) =>
        ls.map((l) => (l.account_id ? l : { ...l, account_id: String(v.default_expense_account_id) })),
      );
    }
  }, [vendorId, vendors]);

  const save = async () => {
    if (!vendorId) return setError("Choose a vendor");
    const payload = toPayload(lines);
    if ("error" in payload) return setError(payload.error);
    if (kind === "po") {
      const { data, error: apiError } = await api.POST("/api/v1/purchase-orders", {
        body: { vendor_id: Number(vendorId), order_date: docDate, lines: payload.lines },
      });
      if (!data) return setError(errorMessage(apiError, "Could not create purchase order"));
      toast.success(`${data.po_number} created`);
      router.push(`/payables/purchase-orders/${data.id}`);
    } else {
      if (!invoiceNo.trim()) return setError("Enter the vendor's invoice number");
      const { data, error: apiError } = await api.POST("/api/v1/vendor-bills", {
        body: {
          vendor_id: Number(vendorId),
          vendor_invoice_number: invoiceNo.trim(),
          bill_date: docDate,
          lines: payload.lines,
        },
      });
      if (!data) return setError(errorMessage(apiError, "Could not create bill"));
      toast.success(`${data.bill_number} created`);
      router.push(`/payables/bills/${data.id}`);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>{kind === "po" ? "New purchase order" : "New vendor bill (no PO)"}</DialogTitle>
          <DialogDescription>
            {kind === "po"
              ? "Issue it to the vendor, then record receipt when the goods or services arrive."
              : "To bill against a purchase order, open the PO and use “Create bill from PO”."}
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 sm:grid-cols-3">
          <div className="flex flex-col gap-2">
            <Label htmlFor="doc-vendor">Vendor</Label>
            <VendorSelect id="doc-vendor" value={vendorId} onChange={setVendorId} vendors={vendors} />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="doc-date">{kind === "po" ? "Order date" : "Bill date"}</Label>
            <Input id="doc-date" type="date" value={docDate} onChange={(e) => setDocDate(e.target.value)} />
          </div>
          {kind === "bill" && (
            <div className="flex flex-col gap-2">
              <Label htmlFor="doc-invoice">Vendor invoice number</Label>
              <Input id="doc-invoice" value={invoiceNo} onChange={(e) => setInvoiceNo(e.target.value)} />
            </div>
          )}
        </div>
        <APLineEditor lines={lines} onChange={setLines} accounts={accounts} />
        {error && (
          <p role="alert" className="text-destructive text-sm">
            {error}
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={() => void save()}>
            {kind === "po" ? "Create purchase order" : "Create bill"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Bills() {
  const { roles } = useAuth();
  const [rows, setRows] = useState<Schemas["VendorBillOut"][]>([]);
  const [status, setStatus] = useState("all");
  const [creating, setCreating] = useState(false);
  const load = useCallback(async () => {
    const { data } = await api.GET("/api/v1/vendor-bills", {
      params: {
        query: { page_size: 100, status: status === "all" ? undefined : (status as Schemas["BillStatus"]) },
      },
    });
    setRows(data?.items ?? []);
  }, [status]);
  useEffect(() => {
    void load();
  }, [load]);
  const runPayments = async () => {
    const { data, error } = await api.POST("/api/v1/vendor-bills/payment-run", { body: {} });
    if (!data) return void toast.error(errorMessage(error, "Payment run failed"));
    toast.success(data.paid ? `Paid ${data.paid} scheduled bill(s)` : "No scheduled bills are due");
    void load();
  };
  return (
    <>
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div className="flex w-56 flex-col gap-1.5">
          <Label htmlFor="bill-status">Status</Label>
          <Select value={status} onValueChange={setStatus}>
            <SelectTrigger id="bill-status" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All</SelectItem>
              {["draft", "pending_approval", "approved", "partially_paid", "paid", "rejected", "void"].map(
                (s) => (
                  <SelectItem key={s} value={s}>
                    <StatusBadge status={s} />
                  </SelectItem>
                ),
              )}
            </SelectContent>
          </Select>
        </div>
        {can(roles, "managePayables") && (
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => void runPayments()}>
              <Wallet /> Run scheduled payments
            </Button>
            <Button onClick={() => setCreating(true)}>
              <Plus /> New bill
            </Button>
          </div>
        )}
      </div>
      <div className="bg-card overflow-x-auto rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Bill</TableHead>
              <TableHead>Vendor</TableHead>
              <TableHead>Due</TableHead>
              <TableHead>Match</TableHead>
              <TableHead>Status</TableHead>
              <TableHead className="text-right">Total</TableHead>
              <TableHead className="text-right">Balance</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((b) => (
              <TableRow key={b.id}>
                <TableCell>
                  <Link href={`/payables/bills/${b.id}`} className="font-mono text-sm hover:underline">
                    {b.bill_number}
                  </Link>
                  <span className="text-muted-foreground block text-xs">#{b.vendor_invoice_number}</span>
                </TableCell>
                <TableCell>{b.vendor_name}</TableCell>
                <TableCell>
                  {b.due_date}
                  {b.scheduled_payment_date && (
                    <span className="text-muted-foreground block text-xs">
                      pay {b.scheduled_payment_date}
                    </span>
                  )}
                </TableCell>
                <TableCell>
                  <StatusBadge status={b.match_status} />
                </TableCell>
                <TableCell>
                  <StatusBadge status={b.status} />
                </TableCell>
                <TableCell className="text-right">
                  <Money value={b.total} />
                </TableCell>
                <TableCell className="text-right">
                  <Money value={b.balance_due} hideZero />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <NewDocumentDialog kind="bill" open={creating} onClose={() => setCreating(false)} />
    </>
  );
}

function PurchaseOrders() {
  const { roles } = useAuth();
  const [rows, setRows] = useState<Schemas["PurchaseOrderOut"][]>([]);
  const [creating, setCreating] = useState(false);
  useEffect(() => {
    void api
      .GET("/api/v1/purchase-orders", { params: { query: { page_size: 100 } } })
      .then(({ data }) => setRows(data?.items ?? []));
  }, []);
  return (
    <>
      {can(roles, "managePayables") && (
        <div className="mb-4 flex justify-end">
          <Button onClick={() => setCreating(true)}>
            <Plus /> New purchase order
          </Button>
        </div>
      )}
      <div className="bg-card overflow-x-auto rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>PO</TableHead>
              <TableHead>Vendor</TableHead>
              <TableHead>Ordered</TableHead>
              <TableHead>Received</TableHead>
              <TableHead>Status</TableHead>
              <TableHead className="text-right">Total</TableHead>
              <TableHead className="text-right">Billed</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((po) => (
              <TableRow key={po.id}>
                <TableCell>
                  <Link
                    href={`/payables/purchase-orders/${po.id}`}
                    className="font-mono text-sm hover:underline"
                  >
                    {po.po_number}
                  </Link>
                </TableCell>
                <TableCell>{po.vendor_name}</TableCell>
                <TableCell>{po.order_date}</TableCell>
                <TableCell>{po.received_on ?? "—"}</TableCell>
                <TableCell>
                  <StatusBadge status={po.status} />
                </TableCell>
                <TableCell className="text-right">
                  <Money value={po.total} />
                </TableCell>
                <TableCell className="text-right">
                  <Money value={po.billed} hideZero />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <NewDocumentDialog kind="po" open={creating} onClose={() => setCreating(false)} />
    </>
  );
}

function Vendors() {
  const { roles } = useAuth();
  const { vendors, reload } = useVendors();
  const { accounts } = useAccounts();
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({
    code: "",
    name: "",
    email: "",
    bank_reference: "",
    payment_terms_days: "30",
    account: "",
  });
  const [error, setError] = useState<string | null>(null);
  const save = async () => {
    const { data, error: apiError } = await api.POST("/api/v1/vendors", {
      body: {
        code: form.code.trim().toUpperCase(),
        name: form.name.trim(),
        email: form.email,
        bank_reference: form.bank_reference,
        payment_terms_days: Number(form.payment_terms_days) || 30,
        default_expense_account_id: form.account ? Number(form.account) : null,
      },
    });
    if (!data) return setError(errorMessage(apiError, "Could not create vendor"));
    toast.success(`${data.name} added`);
    setOpen(false);
    void reload();
  };
  return (
    <>
      {can(roles, "managePayables") && (
        <div className="mb-4 flex justify-end">
          <Button
            onClick={() => {
              setForm({
                code: "",
                name: "",
                email: "",
                bank_reference: "",
                payment_terms_days: "30",
                account: "",
              });
              setError(null);
              setOpen(true);
            }}
          >
            <Plus /> New vendor
          </Button>
        </div>
      )}
      <div className="bg-card overflow-x-auto rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Code</TableHead>
              <TableHead>Name</TableHead>
              <TableHead>Terms</TableHead>
              <TableHead>Bank reference</TableHead>
              <TableHead>Status</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {vendors.map((v) => (
              <TableRow key={v.id}>
                <TableCell className="font-mono text-sm">{v.code}</TableCell>
                <TableCell>
                  {v.name}
                  <span className="text-muted-foreground block text-xs">{v.email}</span>
                </TableCell>
                <TableCell>Net {v.payment_terms_days}</TableCell>
                <TableCell className="font-mono text-xs">{v.bank_reference || "—"}</TableCell>
                <TableCell>
                  {v.is_active ? (
                    <Badge variant="outline">Active</Badge>
                  ) : (
                    <Badge variant="secondary">Inactive</Badge>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <Dialog open={open} onOpenChange={(o) => !o && setOpen(false)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>New vendor</DialogTitle>
            <DialogDescription>Fictional suppliers only.</DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 sm:grid-cols-2">
            {(
              [
                ["code", "Code"],
                ["name", "Name"],
                ["email", "Email"],
                ["bank_reference", "Bank reference"],
                ["payment_terms_days", "Payment terms (days)"],
              ] as const
            ).map(([k, label]) => (
              <div key={k} className="flex flex-col gap-2">
                <Label htmlFor={`v-${k}`}>{label}</Label>
                <Input
                  id={`v-${k}`}
                  value={form[k]}
                  onChange={(e) => setForm((f) => ({ ...f, [k]: e.target.value }))}
                />
              </div>
            ))}
            <div className="flex flex-col gap-2">
              <Label htmlFor="v-account">Default expense account</Label>
              <Select value={form.account} onValueChange={(v) => setForm((f) => ({ ...f, account: v }))}>
                <SelectTrigger id="v-account" className="w-full">
                  <SelectValue placeholder="Optional" />
                </SelectTrigger>
                <SelectContent>
                  {accounts
                    .filter((a) => !a.is_header && a.type === "expense")
                    .map((a) => (
                      <SelectItem key={a.id} value={String(a.id)}>
                        {a.code} · {a.name}
                      </SelectItem>
                    ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          {error && (
            <p role="alert" className="text-destructive text-sm">
              {error}
            </p>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button onClick={() => void save()}>Add vendor</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

function Payments() {
  const [rows, setRows] = useState<Schemas["VendorPaymentOut"][]>([]);
  useEffect(() => {
    void api
      .GET("/api/v1/vendor-payments", { params: { query: { page_size: 100 } } })
      .then(({ data }) => setRows(data?.items ?? []));
  }, []);
  return (
    <div className="bg-card overflow-x-auto rounded-lg border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Payment</TableHead>
            <TableHead>Paid on</TableHead>
            <TableHead>Vendor</TableHead>
            <TableHead>Bill</TableHead>
            <TableHead>Method</TableHead>
            <TableHead className="text-right">Amount</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((p) => (
            <TableRow key={p.id}>
              <TableCell className="font-mono text-sm">{p.payment_number}</TableCell>
              <TableCell>{p.paid_on}</TableCell>
              <TableCell>{p.vendor_name}</TableCell>
              <TableCell>
                <Link
                  href={`/payables/bills/${p.vendor_bill_id}`}
                  className="font-mono text-sm hover:underline"
                >
                  {p.bill_number}
                </Link>
              </TableCell>
              <TableCell className="text-sm">
                {p.method === "cheque" ? "Cheque" : "Bank transfer"}{" "}
                {p.reference && <span className="text-muted-foreground">· {p.reference}</span>}
              </TableCell>
              <TableCell className="text-right">
                <Money value={p.amount} />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function PayablesInner() {
  const router = useRouter();
  const params = useSearchParams();
  const tab = (
    ["bills", "purchase-orders", "vendors", "payments"].includes(params.get("tab") ?? "")
      ? params.get("tab")
      : "bills"
  ) as Tab;
  return (
    <>
      <PageHeader
        title="Payables"
        description="Vendors, purchase orders, bills with three-way match (PO · receipt · bill), approvals and payments."
      />
      <Tabs value={tab} onValueChange={(t) => router.replace(`/payables?tab=${t}`)} className="mb-4">
        <TabsList>
          <TabsTrigger value="bills">Bills</TabsTrigger>
          <TabsTrigger value="purchase-orders">Purchase orders</TabsTrigger>
          <TabsTrigger value="vendors">Vendors</TabsTrigger>
          <TabsTrigger value="payments">Payments</TabsTrigger>
        </TabsList>
      </Tabs>
      {tab === "bills" && <Bills />}
      {tab === "purchase-orders" && <PurchaseOrders />}
      {tab === "vendors" && <Vendors />}
      {tab === "payments" && <Payments />}
    </>
  );
}

export default function PayablesPage() {
  return (
    <Suspense fallback={<p className="text-muted-foreground">Loading…</p>}>
      <PayablesInner />
    </Suspense>
  );
}
