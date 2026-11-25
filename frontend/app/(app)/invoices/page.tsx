"use client";

import type { ColumnDef, SortingState } from "@tanstack/react-table";
import { Plus } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { DataTable, toSortParam } from "@/components/data-table";
import { Money } from "@/components/money";
import { ExportMenu } from "@/components/export-menu";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { api, errorMessage, type Schemas } from "@/lib/api/client";
import { downloadExport } from "@/lib/api/exports";
import { useAuth } from "@/lib/auth/auth-context";
import { can } from "@/lib/permissions";

type Invoice = Schemas["InvoiceSummaryOut"];
type Status = Schemas["InvoiceStatus"];
const PAGE_SIZE = 25;
const ALL = "all";
const STATUSES: Status[] = ["draft", "issued", "partially_paid", "paid", "void"];

export default function InvoicesPage() {
  const { roles } = useAuth();
  const [rows, setRows] = useState<Invoice[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [sorting, setSorting] = useState<SortingState>([{ id: "created_at", desc: true }]);
  const [status, setStatus] = useState<string>(ALL);
  const [search, setSearch] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [overdue, setOverdue] = useState(false);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    const { data, error } = await api.GET("/api/v1/invoices", {
      params: {
        query: {
          page,
          page_size: PAGE_SIZE,
          sort: toSortParam(sorting),
          status: status === ALL ? undefined : (status as Status),
          search: search || undefined,
          date_from: dateFrom || undefined,
          date_to: dateTo || undefined,
          overdue: overdue || undefined,
        },
      },
    });
    setLoading(false);
    if (!data) return void toast.error(errorMessage(error, "Could not load invoices"));
    setRows(data.items);
    setTotal(data.total);
  }, [page, sorting, status, search, dateFrom, dateTo, overdue]);

  useEffect(() => {
    void load();
  }, [load]);

  const columns = useMemo<ColumnDef<Invoice, unknown>[]>(
    () => [
      {
        accessorKey: "invoice_number",
        header: "Invoice",
        cell: ({ row }) => (
          <Link href={`/invoices/${row.original.id}`} className="font-mono text-sm hover:underline">
            {row.original.invoice_number}
          </Link>
        ),
      },
      {
        id: "patient",
        header: "Patient",
        enableSorting: false,
        cell: ({ row }) => (
          <Link href={`/patients/${row.original.patient_id}`} className="hover:underline">
            {row.original.patient_name}
            <span className="text-muted-foreground block font-mono text-xs">{row.original.patient_mrn}</span>
          </Link>
        ),
      },
      { accessorKey: "invoice_date", header: "Date", cell: ({ row }) => row.original.invoice_date ?? "—" },
      { accessorKey: "due_date", header: "Due", cell: ({ row }) => row.original.due_date ?? "—" },
      {
        accessorKey: "status",
        header: "Status",
        enableSorting: false,
        cell: ({ row }) => <StatusBadge status={row.original.status} />,
      },
      {
        accessorKey: "total",
        header: () => <span className="block text-right">Total</span>,
        cell: ({ row }) => (
          <span className="block text-right">
            <Money value={row.original.total} />
          </span>
        ),
      },
      {
        id: "balance_due",
        header: () => <span className="block text-right">Balance due</span>,
        enableSorting: false,
        cell: ({ row }) => (
          <span className="block text-right">
            <Money value={row.original.balance_due} />
          </span>
        ),
      },
    ],
    [],
  );

  const reset =
    <T,>(setter: (v: T) => void) =>
    (v: T) => {
      setPage(1);
      setter(v);
    };

  return (
    <>
      <PageHeader
        title="Invoices"
        description="Draft invoices capture charges; issuing posts revenue to the ledger."
        actions={
          <>
            <ExportMenu
              formats={["csv"]}
              onExport={(fmt) =>
                downloadExport("/api/v1/exports/invoices", fmt, {
                  status: status === ALL ? undefined : status,
                  date_from: dateFrom || undefined,
                  date_to: dateTo || undefined,
                  overdue: overdue || undefined,
                })
              }
            />
            {can(roles, "bill") && (
              <Button asChild>
                <Link href="/invoices/new">
                  <Plus /> New invoice
                </Link>
              </Button>
            )}
          </>
        }
      />
      <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <div className="flex flex-col gap-1.5 lg:col-span-2">
          <Label htmlFor="inv-search">Search</Label>
          <Input
            id="inv-search"
            placeholder="Invoice number, MRN or patient name"
            value={search}
            onChange={(e) => reset(setSearch)(e.target.value)}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="inv-status">Status</Label>
          <Select value={status} onValueChange={reset(setStatus)}>
            <SelectTrigger id="inv-status" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>All statuses</SelectItem>
              {STATUSES.map((s) => (
                <SelectItem key={s} value={s}>
                  <StatusBadge status={s} />
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="inv-from">From</Label>
          <Input
            id="inv-from"
            type="date"
            value={dateFrom}
            onChange={(e) => reset(setDateFrom)(e.target.value)}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="inv-to">To</Label>
          <Input id="inv-to" type="date" value={dateTo} onChange={(e) => reset(setDateTo)(e.target.value)} />
        </div>
      </div>
      <label className="mb-4 flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          className="size-4"
          checked={overdue}
          onChange={(e) => reset(setOverdue)(e.target.checked)}
        />
        Overdue only
      </label>
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
        emptyText="No invoices match these filters."
      />
    </>
  );
}
