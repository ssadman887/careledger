"use client";

import type { ColumnDef, SortingState } from "@tanstack/react-table";
import { Plus } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { DataTable, toSortParam } from "@/components/data-table";
import { Money } from "@/components/money";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { api, errorMessage, type Schemas } from "@/lib/api/client";
import { useAuth } from "@/lib/auth/auth-context";
import { can } from "@/lib/permissions";

type Entry = Schemas["JournalEntryOut"];
type Status = Schemas["EntryStatus"];
const PAGE_SIZE = 25;
const ALL = "all";

export default function JournalPage() {
  const { roles } = useAuth();
  const [rows, setRows] = useState<Entry[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [sorting, setSorting] = useState<SortingState>([{ id: "entry_number", desc: true }]);
  const [status, setStatus] = useState<string>(ALL);
  const [search, setSearch] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    const { data, error } = await api.GET("/api/v1/journal-entries", {
      params: {
        query: {
          page,
          page_size: PAGE_SIZE,
          sort: toSortParam(sorting),
          status: status === ALL ? undefined : (status as Status),
          search: search || undefined,
          date_from: dateFrom || undefined,
          date_to: dateTo || undefined,
        },
      },
    });
    setLoading(false);
    if (!data) return void toast.error(errorMessage(error, "Could not load journal entries"));
    setRows(data.items);
    setTotal(data.total);
  }, [page, sorting, status, search, dateFrom, dateTo]);

  useEffect(() => {
    void load();
  }, [load]);

  const columns = useMemo<ColumnDef<Entry, unknown>[]>(
    () => [
      {
        accessorKey: "entry_number",
        header: "Entry",
        cell: ({ row }) => (
          <Link href={`/journal/${row.original.id}`} className="font-mono text-sm hover:underline">
            {row.original.entry_number}
          </Link>
        ),
      },
      { accessorKey: "entry_date", header: "Date" },
      {
        accessorKey: "memo",
        header: "Memo",
        enableSorting: false,
        cell: ({ row }) => <span className="line-clamp-1 max-w-md">{row.original.memo}</span>,
      },
      { accessorKey: "source_type", header: "Source", enableSorting: false },
      {
        accessorKey: "status",
        header: "Status",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="flex items-center gap-1">
            <StatusBadge status={row.original.status} />
            {row.original.reversed_by_id && <span className="text-muted-foreground text-xs">reversed</span>}
          </span>
        ),
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
    ],
    [],
  );

  const resetPage =
    <T,>(setter: (v: T) => void) =>
    (v: T) => {
      setPage(1);
      setter(v);
    };

  return (
    <>
      <PageHeader
        title="Journal entries"
        description="Every posting to the general ledger. Posted entries are immutable; corrections are reversing entries."
        actions={
          can(roles, "postJournal") ? (
            <Button asChild>
              <Link href="/journal/new">
                <Plus /> New entry
              </Link>
            </Button>
          ) : undefined
        }
      />
      <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="je-search">Search</Label>
          <Input
            id="je-search"
            placeholder="Entry number or memo"
            value={search}
            onChange={(e) => resetPage(setSearch)(e.target.value)}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="je-status">Status</Label>
          <Select value={status} onValueChange={resetPage(setStatus)}>
            <SelectTrigger id="je-status" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>All statuses</SelectItem>
              <SelectItem value="posted">Posted</SelectItem>
              <SelectItem value="pending_approval">Pending approval</SelectItem>
              <SelectItem value="rejected">Rejected</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="je-from">From</Label>
          <Input
            id="je-from"
            type="date"
            value={dateFrom}
            onChange={(e) => resetPage(setDateFrom)(e.target.value)}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="je-to">To</Label>
          <Input
            id="je-to"
            type="date"
            value={dateTo}
            onChange={(e) => resetPage(setDateTo)(e.target.value)}
          />
        </div>
      </div>
      <DataTable
        columns={columns}
        data={rows}
        total={total}
        page={page}
        pageSize={PAGE_SIZE}
        sorting={sorting}
        onSortingChange={resetPage(setSorting)}
        onPageChange={setPage}
        loading={loading}
        emptyText="No journal entries match these filters."
      />
    </>
  );
}
