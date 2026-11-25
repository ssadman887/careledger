"use client";

import type { ColumnDef, SortingState } from "@tanstack/react-table";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { RefundDialog } from "@/components/billing/money-dialogs";
import { DataTable, toSortParam } from "@/components/data-table";
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
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { api, errorMessage, type Schemas } from "@/lib/api/client";
import { openReceiptPdf } from "@/lib/api/download";
import { useAuth } from "@/lib/auth/auth-context";
import { formatDateTime, humanize } from "@/lib/format";
import { toCents } from "@/lib/money";
import { can } from "@/lib/permissions";

type Payment = Schemas["PaymentOut"];
type Refund = Schemas["RefundOut"];
const PAGE_SIZE = 25;
const ALL = "all";

function PaymentsTab() {
  const { roles } = useAuth();
  const [rows, setRows] = useState<Payment[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [sorting, setSorting] = useState<SortingState>([{ id: "created_at", desc: true }]);
  const [method, setMethod] = useState<string>(ALL);
  const [kind, setKind] = useState<string>(ALL);
  const [search, setSearch] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [loading, setLoading] = useState(true);
  const [refundFor, setRefundFor] = useState<Payment | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    const { data, error } = await api.GET("/api/v1/payments", {
      params: {
        query: {
          page,
          page_size: PAGE_SIZE,
          sort: toSortParam(sorting),
          method: method === ALL ? undefined : (method as Schemas["PaymentMethod"]),
          kind: kind === ALL ? undefined : (kind as Schemas["PaymentKind"]),
          search: search || undefined,
          date_from: dateFrom || undefined,
          date_to: dateTo || undefined,
        },
      },
    });
    setLoading(false);
    if (!data) return void toast.error(errorMessage(error, "Could not load payments"));
    setRows(data.items);
    setTotal(data.total);
  }, [page, sorting, method, kind, search, dateFrom, dateTo]);

  useEffect(() => {
    void load();
  }, [load]);

  const columns = useMemo<ColumnDef<Payment, unknown>[]>(
    () => [
      {
        accessorKey: "payment_number",
        header: "Payment",
        cell: ({ row }) => <span className="font-mono text-sm">{row.original.payment_number}</span>,
      },
      { accessorKey: "received_on", header: "Date" },
      {
        id: "patient",
        header: "Patient",
        enableSorting: false,
        cell: ({ row }) => (
          <Link href={`/patients/${row.original.patient_id}`} className="hover:underline">
            {row.original.patient_name}
          </Link>
        ),
      },
      {
        id: "for",
        header: "For",
        enableSorting: false,
        cell: ({ row }) =>
          row.original.invoice_id ? (
            <Link href={`/invoices/${row.original.invoice_id}`} className="font-mono text-sm hover:underline">
              {row.original.invoice_number}
            </Link>
          ) : (
            <span className="text-muted-foreground">Deposit</span>
          ),
      },
      {
        accessorKey: "method",
        header: "Method",
        enableSorting: false,
        cell: ({ row }) => humanize(row.original.method),
      },
      {
        accessorKey: "reference",
        header: "Reference",
        enableSorting: false,
        cell: ({ row }) => <span className="font-mono text-xs">{row.original.reference || "—"}</span>,
      },
      {
        accessorKey: "amount",
        header: () => <span className="block text-right">Amount</span>,
        cell: ({ row }) => (
          <span className="block text-right">
            <Money value={row.original.amount} />
            {(toCents(row.original.refunded_amount) ?? 0n) > 0n && (
              <span className="text-muted-foreground block text-xs">
                refunded <Money value={row.original.refunded_amount} />
              </span>
            )}
          </span>
        ),
      },
      {
        id: "actions",
        header: "",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="flex justify-end gap-1">
            <Button
              size="sm"
              variant="ghost"
              onClick={() => void openReceiptPdf(row.original.id, row.original.payment_number)}
            >
              Receipt
            </Button>
            {can(roles, "bill") &&
              row.original.method !== "insurance" &&
              (toCents(row.original.refunded_amount) ?? 0n) < (toCents(row.original.amount) ?? 0n) && (
                <Button size="sm" variant="ghost" onClick={() => setRefundFor(row.original)}>
                  Refund
                </Button>
              )}
          </span>
        ),
      },
    ],
    [roles],
  );

  const reset =
    <T,>(setter: (v: T) => void) =>
    (v: T) => {
      setPage(1);
      setter(v);
    };

  return (
    <>
      <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="pay-search">Search</Label>
          <Input
            id="pay-search"
            placeholder="Payment no., MRN, name"
            value={search}
            onChange={(e) => reset(setSearch)(e.target.value)}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="pay-method-filter">Method</Label>
          <Select value={method} onValueChange={reset(setMethod)}>
            <SelectTrigger id="pay-method-filter" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>All methods</SelectItem>
              {["cash", "card", "bank_transfer", "deposit", "insurance"].map((m) => (
                <SelectItem key={m} value={m}>
                  {humanize(m)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="pay-kind">Type</Label>
          <Select value={kind} onValueChange={reset(setKind)}>
            <SelectTrigger id="pay-kind" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>All</SelectItem>
              <SelectItem value="invoice">Invoice payments</SelectItem>
              <SelectItem value="deposit">Deposits</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="pay-from">From</Label>
          <Input
            id="pay-from"
            type="date"
            value={dateFrom}
            onChange={(e) => reset(setDateFrom)(e.target.value)}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="pay-to">To</Label>
          <Input id="pay-to" type="date" value={dateTo} onChange={(e) => reset(setDateTo)(e.target.value)} />
        </div>
      </div>
      <DataTable
        columns={columns}
        data={rows}
        total={total}
        page={page}
        pageSize={PAGE_SIZE}
        sorting={sorting}
        onSortingChange={reset(setSorting)}
        onPageChange={setPage}
        loading={loading}
        emptyText="No payments match these filters."
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
    </>
  );
}

function RefundsTab() {
  const { roles } = useAuth();
  const canApprove = can(roles, "approveRefund");
  const [rows, setRows] = useState<Refund[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState<string>("pending_approval");
  const [deciding, setDeciding] = useState<{ refund: Refund; approve: boolean } | null>(null);
  const [note, setNote] = useState("");

  const load = useCallback(async () => {
    const { data, error } = await api.GET("/api/v1/refunds", {
      params: {
        query: {
          page,
          page_size: PAGE_SIZE,
          status: status === ALL ? undefined : (status as Schemas["RefundStatus"]),
        },
      },
    });
    if (!data) return void toast.error(errorMessage(error, "Could not load refunds"));
    setRows(data.items);
    setTotal(data.total);
  }, [page, status]);

  useEffect(() => {
    void load();
  }, [load]);

  const decide = async () => {
    if (!deciding) return;
    const opts = { params: { path: { refund_id: deciding.refund.id } }, body: { note } };
    const result = deciding.approve
      ? await api.POST("/api/v1/refunds/{refund_id}/approve", opts)
      : await api.POST("/api/v1/refunds/{refund_id}/reject", opts);
    if (!result.data) return void toast.error(errorMessage(result.error, "Decision failed"));
    toast.success(
      deciding.approve
        ? `${result.data.refund_number} approved and posted`
        : `${result.data.refund_number} rejected`,
    );
    setDeciding(null);
    setNote("");
    void load();
  };

  const columns = useMemo<ColumnDef<Refund, unknown>[]>(
    () => [
      {
        accessorKey: "refund_number",
        header: "Refund",
        enableSorting: false,
        cell: ({ row }) => <span className="font-mono text-sm">{row.original.refund_number}</span>,
      },
      {
        accessorKey: "created_at",
        header: "Requested",
        enableSorting: false,
        cell: ({ row }) => formatDateTime(row.original.created_at),
      },
      { accessorKey: "patient_name", header: "Patient", enableSorting: false },
      {
        accessorKey: "payment_number",
        header: "Payment",
        enableSorting: false,
        cell: ({ row }) => <span className="font-mono text-sm">{row.original.payment_number}</span>,
      },
      {
        accessorKey: "reason",
        header: "Reason",
        enableSorting: false,
        cell: ({ row }) => <span className="line-clamp-2 max-w-xs">{row.original.reason}</span>,
      },
      {
        accessorKey: "status",
        header: "Status",
        enableSorting: false,
        cell: ({ row }) => <StatusBadge status={row.original.status} />,
      },
      {
        accessorKey: "amount",
        header: () => <span className="block text-right">Amount</span>,
        enableSorting: false,
        cell: ({ row }) => (
          <span className="block text-right">
            <Money value={row.original.amount} />
          </span>
        ),
      },
      {
        id: "actions",
        header: "",
        enableSorting: false,
        cell: ({ row }) =>
          canApprove && row.original.status === "pending_approval" ? (
            <span className="flex justify-end gap-1">
              <Button size="sm" onClick={() => setDeciding({ refund: row.original, approve: true })}>
                Approve
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => setDeciding({ refund: row.original, approve: false })}
              >
                Reject
              </Button>
            </span>
          ) : null,
      },
    ],
    [canApprove],
  );

  return (
    <>
      <div className="mb-4 w-56">
        <Label htmlFor="refund-status" className="mb-1.5 block">
          Status
        </Label>
        <Select
          value={status}
          onValueChange={(v) => {
            setPage(1);
            setStatus(v);
          }}
        >
          <SelectTrigger id="refund-status" className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="pending_approval">Pending approval</SelectItem>
            <SelectItem value="completed">Completed</SelectItem>
            <SelectItem value="rejected">Rejected</SelectItem>
            <SelectItem value={ALL}>All</SelectItem>
          </SelectContent>
        </Select>
      </div>
      <DataTable
        columns={columns}
        data={rows}
        total={total}
        page={page}
        pageSize={PAGE_SIZE}
        sorting={[]}
        onSortingChange={() => undefined}
        onPageChange={setPage}
        emptyText="No refunds."
      />
      <Dialog open={deciding !== null} onOpenChange={(o) => !o && setDeciding(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {deciding?.approve ? "Approve" : "Reject"} {deciding?.refund.refund_number}
            </DialogTitle>
            <DialogDescription>
              {deciding?.approve
                ? "The refund posts to the ledger and money leaves the hospital."
                : "The refund will not be paid. The requester sees your note."}
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-2">
            <Label htmlFor="decision-note">Note</Label>
            <Textarea id="decision-note" rows={2} value={note} onChange={(e) => setNote(e.target.value)} />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeciding(null)}>
              Cancel
            </Button>
            <Button onClick={() => void decide()} disabled={!deciding?.approve && !note.trim()}>
              {deciding?.approve ? "Approve refund" : "Reject refund"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

function PaymentsInner() {
  const router = useRouter();
  const params = useSearchParams();
  const tab = params.get("tab") === "refunds" ? "refunds" : "payments";
  return (
    <>
      <PageHeader
        title="Payments"
        description="Patient payments, deposits on account and refunds. Refunds above the threshold need finance-manager approval."
      />
      <Tabs value={tab} onValueChange={(t) => router.replace(`/payments?tab=${t}`)} className="mb-4">
        <TabsList>
          <TabsTrigger value="payments">Payments</TabsTrigger>
          <TabsTrigger value="refunds">Refunds</TabsTrigger>
        </TabsList>
      </Tabs>
      {tab === "payments" ? <PaymentsTab /> : <RefundsTab />}
    </>
  );
}

export default function PaymentsPage() {
  return (
    <Suspense fallback={<p className="text-muted-foreground">Loading…</p>}>
      <PaymentsInner />
    </Suspense>
  );
}
