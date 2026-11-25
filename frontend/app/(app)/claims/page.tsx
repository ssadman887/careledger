"use client";

import type { ColumnDef, SortingState } from "@tanstack/react-table";
import { Bot } from "lucide-react";
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
import { humanize } from "@/lib/format";
import { can } from "@/lib/permissions";
import { cn } from "@/lib/utils";

type Claim = Schemas["ClaimSummaryOut"];
type Status = Schemas["ClaimStatus"];
const PAGE_SIZE = 25;
const ALL = "all";
const STATUSES: Status[] = [
  "draft",
  "submitted",
  "under_review",
  "approved",
  "partially_approved",
  "denied",
  "appealed",
  "paid",
  "closed",
  "cancelled",
];

export default function ClaimsPage() {
  const { roles } = useAuth();
  const [rows, setRows] = useState<Claim[]>([]);
  const [total, setTotal] = useState(0);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [insurers, setInsurers] = useState<Schemas["InsurerOut"][]>([]);
  const [page, setPage] = useState(1);
  const [sorting, setSorting] = useState<SortingState>([{ id: "created_at", desc: true }]);
  const [status, setStatus] = useState<string>(ALL);
  const [insurer, setInsurer] = useState<string>(ALL);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    const [list, c] = await Promise.all([
      api.GET("/api/v1/claims", {
        params: {
          query: {
            page,
            page_size: PAGE_SIZE,
            sort: toSortParam(sorting),
            status: status === ALL ? undefined : (status as Status),
            insurer_id: insurer === ALL ? undefined : Number(insurer),
            search: search || undefined,
          },
        },
      }),
      api.GET("/api/v1/claims/counts"),
    ]);
    setLoading(false);
    if (!list.data) return void toast.error(errorMessage(list.error, "Could not load claims"));
    setRows(list.data.items);
    setTotal(list.data.total);
    setCounts(c.data?.counts ?? {});
  }, [page, sorting, status, insurer, search]);

  useEffect(() => {
    void load();
  }, [load]);
  useEffect(() => {
    void api.GET("/api/v1/insurers").then(({ data }) => setInsurers(data ?? []));
  }, []);

  const runMock = async () => {
    setRunning(true);
    const { data, error } = await api.POST("/api/v1/claims/run-mock-insurer");
    setRunning(false);
    if (!data) return void toast.error(errorMessage(error, "Mock insurer failed"));
    const outcomes = data.claims.map((c) => `${c.claim_number}: ${humanize(c.status)}`).join(", ");
    toast.success(
      data.processed
        ? `Adjudicated ${data.processed} claim(s). ${outcomes}`
        : "No claims waiting with insurers",
    );
    void load();
  };

  const columns = useMemo<ColumnDef<Claim, unknown>[]>(
    () => [
      {
        accessorKey: "claim_number",
        header: "Claim",
        cell: ({ row }) => (
          <Link href={`/claims/${row.original.id}`} className="font-mono text-sm hover:underline">
            {row.original.claim_number}
          </Link>
        ),
      },
      {
        id: "patient",
        header: "Patient",
        enableSorting: false,
        cell: ({ row }) => (
          <span>
            {row.original.patient_name}
            <span className="text-muted-foreground block font-mono text-xs">{row.original.patient_mrn}</span>
          </span>
        ),
      },
      { accessorKey: "insurer_name", header: "Insurer", enableSorting: false },
      { accessorKey: "service_date", header: "Service date" },
      {
        accessorKey: "status",
        header: "Status",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="flex items-center gap-1">
            <StatusBadge status={row.original.status} />
            {row.original.denial_code && (
              <span className="text-muted-foreground font-mono text-xs">{row.original.denial_code}</span>
            )}
          </span>
        ),
      },
      {
        accessorKey: "insurer_amount",
        header: () => <span className="block text-right">Claimed</span>,
        cell: ({ row }) => (
          <span className="block text-right">
            <Money value={row.original.insurer_amount} />
          </span>
        ),
      },
      {
        id: "approved",
        header: () => <span className="block text-right">Approved / paid</span>,
        enableSorting: false,
        cell: ({ row }) => (
          <span className="block text-right text-sm">
            <Money value={row.original.approved_amount} hideZero /> /{" "}
            <Money value={row.original.paid_amount} hideZero />
          </span>
        ),
      },
    ],
    [],
  );

  return (
    <>
      <PageHeader
        title="Claims"
        description="Insurance claims worklist. Submitted and appealed claims wait for the (mock) insurer."
        actions={
          can(roles, "workClaims") ? (
            <Button onClick={() => void runMock()} disabled={running}>
              <Bot /> {running ? "Adjudicating…" : "Run mock insurer"}
            </Button>
          ) : undefined
        }
      />
      <div className="mb-4 flex flex-wrap gap-2" role="group" aria-label="Filter by status">
        <button
          type="button"
          onClick={() => {
            setPage(1);
            setStatus(ALL);
          }}
          className={cn(
            "rounded-full border px-3 py-1 text-xs",
            status === ALL && "bg-primary text-primary-foreground",
          )}
          aria-pressed={status === ALL}
        >
          All {Object.values(counts).reduce((a, b) => a + b, 0)}
        </button>
        {STATUSES.map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => {
              setPage(1);
              setStatus(s);
            }}
            className={cn(
              "rounded-full border px-3 py-1 text-xs",
              status === s && "bg-primary text-primary-foreground",
            )}
            aria-pressed={status === s}
          >
            {humanize(s)} {counts[s] ?? 0}
          </button>
        ))}
      </div>
      <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:max-w-2xl">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="claim-search">Search</Label>
          <Input
            id="claim-search"
            placeholder="Claim number, MRN or name"
            value={search}
            onChange={(e) => {
              setPage(1);
              setSearch(e.target.value);
            }}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="claim-insurer">Insurer</Label>
          <Select
            value={insurer}
            onValueChange={(v) => {
              setPage(1);
              setInsurer(v);
            }}
          >
            <SelectTrigger id="claim-insurer" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>All insurers</SelectItem>
              {insurers.map((i) => (
                <SelectItem key={i.id} value={String(i.id)}>
                  {i.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>
      <DataTable
        columns={columns}
        data={rows}
        total={total}
        page={page}
        pageSize={PAGE_SIZE}
        sorting={sorting}
        onSortingChange={(s) => {
          setPage(1);
          setSorting(s);
        }}
        onPageChange={setPage}
        loading={loading}
        emptyText="No claims match."
      />
    </>
  );
}
