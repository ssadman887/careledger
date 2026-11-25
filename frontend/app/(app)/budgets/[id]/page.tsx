"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { toast } from "sonner";

import { AlertsTable } from "@/components/budgets/alerts-table";
import { Money } from "@/components/money";
import { ExportMenu } from "@/components/export-menu";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableFooter,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { api, errorMessage, type Schemas } from "@/lib/api/client";
import { downloadExport } from "@/lib/api/exports";
import { useAuth } from "@/lib/auth/auth-context";
import { formatMoney } from "@/lib/format";
import { MONTHS } from "@/lib/payroll";
import { can } from "@/lib/permissions";

type Variance = Schemas["VarianceOut"];

function Totals({ label, t }: { label: string; t: Schemas["VarianceTotals"] }) {
  return (
    <TableRow>
      <TableCell>{label}</TableCell>
      <TableCell className="text-right">
        <Money value={t.annual_budget} />
      </TableCell>
      <TableCell className="text-right">
        <Money value={t.budget_ytd} />
      </TableCell>
      <TableCell className="text-right">
        <Money value={t.actual_ytd} />
      </TableCell>
      <TableCell className="text-right">
        <Money value={t.variance_ytd} />
      </TableCell>
      <TableCell colSpan={2} />
    </TableRow>
  );
}

export default function BudgetPage() {
  const { id } = useParams<{ id: string }>();
  const { roles } = useAuth();
  const canManage = can(roles, "manageBudgets");
  const [through, setThrough] = useState<string>("");
  const [report, setReport] = useState<Variance | null>(null);
  const [alerts, setAlerts] = useState<Schemas["BudgetAlertOut"][]>([]);
  const [threshold, setThreshold] = useState("");

  const load = useCallback(async () => {
    const [v, a] = await Promise.all([
      api.GET("/api/v1/budgets/{budget_id}/variance", {
        params: {
          path: { budget_id: Number(id) },
          query: { through_month: through ? Number(through) : undefined },
        },
      }),
      api.GET("/api/v1/budgets/alerts", { params: { query: { budget_id: Number(id), page_size: 50 } } }),
    ]);
    if (!v.data) return void toast.error(errorMessage(v.error, "Budget not found"));
    setReport(v.data);
    setThreshold(String(Number(v.data.budget.alert_threshold_percent)));
    if (!through) setThrough(String(v.data.through_month));
    setAlerts(a.data?.items ?? []);
  }, [id, through]);
  useEffect(() => {
    void load();
  }, [load]);

  // Display-only numeric conversions of exact decimal strings for the chart.
  const chart = useMemo(() => {
    if (!report) return [];
    const expenses = report.rows.filter((r) => r.account_type === "expense");
    return MONTHS.map((m, i) => ({
      month: m,
      budget: expenses.reduce((s, r) => s + Number(r.monthly_budget[i] ?? "0"), 0),
      actual:
        i < report.through_month
          ? expenses.reduce((s, r) => s + Number(r.monthly_actual[i] ?? "0"), 0)
          : null,
    }));
  }, [report]);

  if (!report) return <p className="text-muted-foreground">Loading…</p>;
  const b = report.budget;

  const setStatus = async (status: "active" | "archived") => {
    const { data, error } = await api.POST("/api/v1/budgets/{budget_id}/status", {
      params: { path: { budget_id: b.id } },
      body: { status },
    });
    if (!data) return void toast.error(errorMessage(error, "Could not change status"));
    toast.success(status === "active" ? "Budget activated; alerts are now monitored" : "Budget archived");
    void load();
  };
  const saveThreshold = async () => {
    if (!/^\d{1,3}(\.\d{1,2})?$/.test(threshold)) return void toast.error("Threshold like 90");
    const { data, error } = await api.PATCH("/api/v1/budgets/{budget_id}", {
      params: { path: { budget_id: b.id } },
      body: { alert_threshold_percent: threshold },
    });
    if (!data) return void toast.error(errorMessage(error, "Could not save threshold"));
    toast.success(`Alert threshold set to ${Number(data.alert_threshold_percent)}%`);
    void load();
  };

  const exp = report.expense_totals;
  const used = Number(exp.budget_ytd) > 0 ? (Number(exp.actual_ytd) / Number(exp.budget_ytd)) * 100 : null;

  return (
    <>
      <Button asChild variant="ghost" size="sm" className="mb-2 -ml-2">
        <Link href="/budgets">
          <ArrowLeft /> Budgets
        </Link>
      </Button>
      <PageHeader
        title={b.name}
        description={`${b.department_name} · ${b.year} · actuals are posted ledger lines tagged with this department`}
        actions={
          canManage && (
            <>
              {b.status === "draft" && <Button onClick={() => void setStatus("active")}>Activate</Button>}
              {b.status === "active" && (
                <Button variant="outline" onClick={() => void setStatus("archived")}>
                  Archive
                </Button>
              )}
            </>
          )
        }
      />
      <div className="mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardHeader>
            <CardTitle className="text-muted-foreground text-sm font-normal">Status</CardTitle>
          </CardHeader>
          <CardContent>
            <StatusBadge status={b.status} />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-muted-foreground text-sm font-normal">
              Expense budget to date
            </CardTitle>
          </CardHeader>
          <CardContent className="text-xl">
            <Money value={exp.budget_ytd} />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-muted-foreground text-sm font-normal">
              Expense actual to date
            </CardTitle>
          </CardHeader>
          <CardContent className="text-xl">
            <Money value={exp.actual_ytd} />
            {used !== null && (
              <span className="text-muted-foreground ml-2 text-sm">{used.toFixed(1)}% used</span>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-muted-foreground text-sm font-normal">
              Expense variance (+ = under)
            </CardTitle>
          </CardHeader>
          <CardContent className="text-xl">
            <Money value={exp.variance_ytd} className="font-semibold" />
          </CardContent>
        </Card>
      </div>

      <div className="mb-4 flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="through-month">Year to date through</Label>
          <Select value={through} onValueChange={setThrough}>
            <SelectTrigger id="through-month" className="w-36">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {MONTHS.map((m, i) => (
                <SelectItem key={m} value={String(i + 1)}>
                  {m} {b.year}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <ExportMenu
          onExport={(fmt) =>
            downloadExport(
              "/api/v1/exports/budgets/{budget_id}/variance",
              fmt,
              { through_month: report.through_month },
              { budget_id: b.id },
            )
          }
        />
        {canManage && b.status !== "archived" && (
          <div className="flex items-end gap-2">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="threshold">Alert threshold %</Label>
              <Input
                id="threshold"
                className="w-24"
                value={threshold}
                onChange={(e) => setThreshold(e.target.value)}
              />
            </div>
            <Button variant="outline" onClick={() => void saveThreshold()}>
              Save
            </Button>
          </div>
        )}
      </div>

      <Card className="mb-6">
        <CardHeader>
          <CardTitle className="text-base">Monthly expenses: budget vs actual</CardTitle>
        </CardHeader>
        <CardContent className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={chart} margin={{ left: 8, right: 8 }}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="month" tickLine={false} axisLine={false} />
              <YAxis
                tickFormatter={(v: number) => formatMoney(String(v)).replace(".00", "")}
                width={88}
                tickLine={false}
                axisLine={false}
              />
              <Tooltip formatter={(v) => formatMoney(String(v))} />
              <Legend />
              <Bar dataKey="actual" name="Actual" fill="var(--color-primary)" radius={[4, 4, 0, 0]} />
              <Line
                dataKey="budget"
                name="Budget"
                stroke="var(--color-chart-4, #d97706)"
                strokeWidth={2}
                dot={false}
              />
            </ComposedChart>
          </ResponsiveContainer>
        </CardContent>
      </Card>

      <Card className="mb-6">
        <CardHeader>
          <CardTitle className="text-base">Variance by account</CardTitle>
          <p className="text-muted-foreground text-xs">
            Variance is favourable when positive: under budget for expenses, above budget for revenue.
            Accounts with department activity but no budget are shown as unbudgeted.
          </p>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Account</TableHead>
                <TableHead className="text-right">Annual budget</TableHead>
                <TableHead className="text-right">Budget to date</TableHead>
                <TableHead className="text-right">Actual to date</TableHead>
                <TableHead className="text-right">Variance</TableHead>
                <TableHead className="text-right">Used</TableHead>
                <TableHead>Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {report.rows.map((r) => (
                <TableRow key={r.account_id}>
                  <TableCell>
                    <span className="font-mono text-sm">{r.account_code}</span> {r.account_name}
                    <span className="text-muted-foreground block text-xs capitalize">{r.account_type}</span>
                  </TableCell>
                  <TableCell className="text-right">
                    <Money value={r.annual_budget} />
                  </TableCell>
                  <TableCell className="text-right">
                    <Money value={r.budget_ytd} />
                  </TableCell>
                  <TableCell className="text-right">
                    <Money value={r.actual_ytd} />
                  </TableCell>
                  <TableCell className="text-right">
                    <Money value={r.variance_ytd} />
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {r.percent_used !== null ? `${r.percent_used}%` : "—"}
                  </TableCell>
                  <TableCell>
                    <StatusBadge status={r.status} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
            <TableFooter>
              <Totals label="Expenses" t={report.expense_totals} />
              <Totals label="Revenue" t={report.revenue_totals} />
            </TableFooter>
          </Table>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Alerts for this budget</CardTitle>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          <AlertsTable alerts={alerts} />
        </CardContent>
      </Card>
    </>
  );
}
