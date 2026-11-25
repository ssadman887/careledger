"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { toast } from "sonner";

import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api, errorMessage, type Schemas } from "@/lib/api/client";
import { useAccounts } from "@/lib/api/hooks";

import { AccountLedgerView, BalanceSheetView, IncomeStatementView, TrialBalanceTable } from "./statements";

const TABS = [
  { id: "trial-balance", label: "Trial balance" },
  { id: "income", label: "Income statement" },
  { id: "balance-sheet", label: "Balance sheet" },
  { id: "ledger", label: "Account ledger" },
] as const;
type Tab = (typeof TABS)[number]["id"];

type Report =
  | { tab: "trial-balance"; data: Schemas["TrialBalanceOut"] }
  | { tab: "income"; data: Schemas["IncomeStatementOut"] }
  | { tab: "balance-sheet"; data: Schemas["BalanceSheetOut"] }
  | { tab: "ledger"; data: Schemas["AccountLedgerOut"] };

const today = () => new Date().toISOString().slice(0, 10);
const startOfYear = () => `${new Date().getFullYear()}-01-01`;
const LEDGER_PAGE = 100;

function ReportsInner() {
  const router = useRouter();
  const params = useSearchParams();
  const tab = (TABS.find((t) => t.id === params.get("tab"))?.id ?? "trial-balance") as Tab;
  const { accounts } = useAccounts();
  const postable = accounts.filter((a) => !a.is_header);

  const [dateFrom, setDateFrom] = useState(startOfYear());
  const [dateTo, setDateTo] = useState(today());
  const [accountId, setAccountId] = useState(params.get("account") ?? "");
  const [page, setPage] = useState(1);
  const [report, setReport] = useState<Report | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const fromUrl = params.get("account");
    if (fromUrl) setAccountId(fromUrl);
  }, [params]);

  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      setLoading(true);
      const range = { date_from: dateFrom || undefined, date_to: dateTo || undefined };
      let next: Report | null = null;
      let error: unknown = null;
      if (tab === "trial-balance") {
        const r = await api.GET("/api/v1/reports/trial-balance", { params: { query: range } });
        if (r.data) next = { tab, data: r.data };
        error = r.error;
      } else if (tab === "income") {
        const r = await api.GET("/api/v1/reports/income-statement", { params: { query: range } });
        if (r.data) next = { tab, data: r.data };
        error = r.error;
      } else if (tab === "balance-sheet") {
        const r = await api.GET("/api/v1/reports/balance-sheet", {
          params: { query: { as_of: dateTo || undefined } },
        });
        if (r.data) next = { tab, data: r.data };
        error = r.error;
      } else if (accountId) {
        const r = await api.GET("/api/v1/reports/account-ledger/{account_id}", {
          params: {
            path: { account_id: Number(accountId) },
            query: { ...range, page, page_size: LEDGER_PAGE },
          },
        });
        if (r.data) next = { tab, data: r.data };
        error = r.error;
      }
      if (cancelled) return;
      setLoading(false);
      setReport(next);
      if (!next && error) toast.error(errorMessage(error, "Could not load report"));
    };
    void run();
    return () => {
      cancelled = true;
    };
  }, [tab, dateFrom, dateTo, accountId, page]);

  const setTab = (t: string) => {
    setReport(null);
    setPage(1);
    const qs = new URLSearchParams({ tab: t });
    if (t === "ledger" && accountId) qs.set("account", accountId);
    router.replace(`/reports?${qs.toString()}`);
  };

  const ledgerPages = report?.tab === "ledger" ? Math.max(1, Math.ceil(report.data.total / LEDGER_PAGE)) : 1;

  return (
    <>
      <PageHeader
        title="Financial reports"
        description="Built from posted journal lines only. Pending and rejected entries are excluded."
      />
      <Tabs value={tab} onValueChange={setTab} className="mb-4">
        <TabsList className="flex-wrap">
          {TABS.map((t) => (
            <TabsTrigger key={t.id} value={t.id}>
              {t.label}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>

      <div className="mb-4 flex flex-wrap items-end gap-3">
        {tab !== "balance-sheet" && (
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="rep-from">From</Label>
            <Input id="rep-from" type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
          </div>
        )}
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="rep-to">{tab === "balance-sheet" ? "As of" : "To"}</Label>
          <Input id="rep-to" type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
        </div>
        {tab === "ledger" && (
          <div className="flex min-w-72 flex-col gap-1.5">
            <Label htmlFor="rep-account">Account</Label>
            <Select
              value={accountId}
              onValueChange={(v) => {
                setPage(1);
                setAccountId(v);
                router.replace(`/reports?tab=ledger&account=${v}`);
              }}
            >
              <SelectTrigger id="rep-account" className="w-full">
                <SelectValue placeholder="Choose an account" />
              </SelectTrigger>
              <SelectContent>
                {postable.map((a) => (
                  <SelectItem key={a.id} value={String(a.id)}>
                    {a.code} · {a.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}
      </div>

      <Card>
        <CardContent className="overflow-x-auto" aria-busy={loading}>
          {tab === "ledger" && !accountId && (
            <p className="text-muted-foreground py-8 text-center text-sm">
              Choose an account to see its ledger.
            </p>
          )}
          {!report && loading && <p className="text-muted-foreground py-8 text-center text-sm">Loading…</p>}
          {report?.tab === "trial-balance" && <TrialBalanceTable data={report.data} />}
          {report?.tab === "income" && <IncomeStatementView data={report.data} />}
          {report?.tab === "balance-sheet" && <BalanceSheetView data={report.data} />}
          {report?.tab === "ledger" && (
            <>
              <p className="mb-2 text-sm font-medium">
                {report.data.code} · {report.data.name}
              </p>
              <AccountLedgerView data={report.data} />
              {ledgerPages > 1 && (
                <div className="mt-3 flex items-center justify-end gap-2 text-sm">
                  <span className="text-muted-foreground">
                    Page {page} of {ledgerPages}
                  </span>
                  <Button size="sm" variant="outline" disabled={page <= 1} onClick={() => setPage(page - 1)}>
                    Previous
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={page >= ledgerPages}
                    onClick={() => setPage(page + 1)}
                  >
                    Next
                  </Button>
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>
    </>
  );
}

export default function ReportsPage() {
  return (
    <Suspense fallback={<p className="text-muted-foreground">Loading…</p>}>
      <ReportsInner />
    </Suspense>
  );
}
