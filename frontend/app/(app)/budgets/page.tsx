"use client";

import { BellRing, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { AlertsTable } from "@/components/budgets/alerts-table";
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
import { useAccounts, useDepartments } from "@/lib/api/hooks";
import { useAuth } from "@/lib/auth/auth-context";
import { budgetLinesToPayload, type BudgetLineDraft } from "@/lib/payroll";
import { can } from "@/lib/permissions";

const emptyLine = (): BudgetLineDraft => ({ account_id: "", annual: "" });

export default function BudgetsPage() {
  const { roles } = useAuth();
  const canManage = can(roles, "manageBudgets");
  const departments = useDepartments();
  const { accounts } = useAccounts();
  const budgetable = accounts.filter(
    (a) => !a.is_header && a.is_active && (a.type === "expense" || a.type === "revenue"),
  );
  const [year, setYear] = useState(String(new Date().getFullYear()));
  const [rows, setRows] = useState<Schemas["BudgetOut"][]>([]);
  const [alerts, setAlerts] = useState<Schemas["BudgetAlertOut"][]>([]);
  const [open, setOpen] = useState(false);
  const [dept, setDept] = useState("");
  const [threshold, setThreshold] = useState("90");
  const [lines, setLines] = useState<BudgetLineDraft[]>([emptyLine()]);

  const load = useCallback(async () => {
    const y = /^\d{4}$/.test(year) ? Number(year) : undefined;
    const [b, a] = await Promise.all([
      api.GET("/api/v1/budgets", { params: { query: { year: y, page_size: 50 } } }),
      api.GET("/api/v1/budgets/alerts", { params: { query: { year: y, page_size: 50 } } }),
    ]);
    setRows(b.data?.items ?? []);
    setAlerts(a.data?.items ?? []);
  }, [year]);
  useEffect(() => {
    void load();
  }, [load]);

  const create = async () => {
    if (!dept) return void toast.error("Choose a department");
    if (!/^\d{1,3}(\.\d{1,2})?$/.test(threshold)) return void toast.error("Threshold like 90");
    const payload = budgetLinesToPayload(lines);
    if ("error" in payload) return void toast.error(payload.error);
    const { data, error } = await api.POST("/api/v1/budgets", {
      body: {
        year: Number(year),
        department_id: Number(dept),
        alert_threshold_percent: threshold,
        lines: payload.lines,
      },
    });
    if (!data) return void toast.error(errorMessage(error, "Could not create budget"));
    toast.success(`${data.name} created as a draft`);
    setOpen(false);
    void load();
  };

  const check = async () => {
    const { data, error } = await api.POST("/api/v1/budgets/alerts/check", { body: {} });
    if (!data) return void toast.error(errorMessage(error, "Alert check failed"));
    toast.success(data.created ? `${data.created} new alert(s)` : "No new alerts");
    void load();
  };

  return (
    <>
      <PageHeader
        title="Budgets"
        description="Annual budgets per department and account, compared with the ledger. Alerts fire at the threshold and when a budget is exceeded."
        actions={
          canManage && (
            <>
              <Button variant="outline" onClick={() => void check()}>
                <BellRing /> Check alerts now
              </Button>
              <Button
                onClick={() => {
                  setDept("");
                  setThreshold("90");
                  setLines([emptyLine()]);
                  setOpen(true);
                }}
              >
                <Plus /> New budget
              </Button>
            </>
          )
        }
      />
      <div className="mb-4 flex items-end gap-3">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="budget-year">Year</Label>
          <Input id="budget-year" className="w-24" value={year} onChange={(e) => setYear(e.target.value)} />
        </div>
      </div>
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2 [&>*]:min-w-0">
        <div className="bg-card overflow-x-auto rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Budget</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">Accounts</TableHead>
                <TableHead className="text-right">Alert at</TableHead>
                <TableHead className="text-right">Annual total</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.length === 0 && (
                <TableRow>
                  <TableCell colSpan={5} className="text-muted-foreground h-20 text-center">
                    No budgets for {year}.
                  </TableCell>
                </TableRow>
              )}
              {rows.map((b) => (
                <TableRow key={b.id}>
                  <TableCell>
                    <Link href={`/budgets/${b.id}`} className="font-medium hover:underline">
                      {b.name}
                    </Link>
                    <span className="text-muted-foreground block text-xs">{b.department_name}</span>
                  </TableCell>
                  <TableCell>
                    <StatusBadge status={b.status} />
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{b.accounts}</TableCell>
                  <TableCell className="text-right tabular-nums">
                    {Number(b.alert_threshold_percent)}%
                  </TableCell>
                  <TableCell className="text-right">
                    <Money value={b.annual_total} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Budget alerts</CardTitle>
          </CardHeader>
          <CardContent className="overflow-x-auto">
            <AlertsTable alerts={alerts} />
          </CardContent>
        </Card>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-xl">
          <DialogHeader>
            <DialogTitle>New {year} budget</DialogTitle>
            <DialogDescription>
              Annual amounts are split evenly across months (remainder in December). Budgets start as drafts;
              activate one to monitor it.
            </DialogDescription>
          </DialogHeader>
          <div className="grid grid-cols-2 gap-3">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="new-budget-dept">Department</Label>
              <Select value={dept} onValueChange={setDept}>
                <SelectTrigger id="new-budget-dept">
                  <SelectValue placeholder="Choose" />
                </SelectTrigger>
                <SelectContent>
                  {departments.map((d) => (
                    <SelectItem key={d.id} value={String(d.id)}>
                      {d.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="new-budget-threshold">Alert threshold %</Label>
              <Input
                id="new-budget-threshold"
                value={threshold}
                onChange={(e) => setThreshold(e.target.value)}
              />
            </div>
          </div>
          <div className="flex flex-col gap-2">
            {lines.map((ln, i) => (
              <div key={i} className="flex items-end gap-2">
                <div className="flex flex-1 flex-col gap-1.5">
                  <Label htmlFor={`bl-acct-${i}`}>Account, line {i + 1}</Label>
                  <Select
                    value={ln.account_id}
                    onValueChange={(v) =>
                      setLines(lines.map((x, j) => (j === i ? { ...x, account_id: v } : x)))
                    }
                  >
                    <SelectTrigger id={`bl-acct-${i}`}>
                      <SelectValue placeholder="Account" />
                    </SelectTrigger>
                    <SelectContent>
                      {budgetable.map((a) => (
                        <SelectItem key={a.id} value={String(a.id)}>
                          {a.code} · {a.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="flex w-40 flex-col gap-1.5">
                  <Label htmlFor={`bl-amt-${i}`}>Annual amount, line {i + 1}</Label>
                  <Input
                    id={`bl-amt-${i}`}
                    inputMode="decimal"
                    value={ln.annual}
                    onChange={(e) =>
                      setLines(lines.map((x, j) => (j === i ? { ...x, annual: e.target.value } : x)))
                    }
                  />
                </div>
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={`Remove line ${i + 1}`}
                  onClick={() => setLines(lines.filter((_, j) => j !== i))}
                >
                  <Trash2 />
                </Button>
              </div>
            ))}
            <Button
              variant="outline"
              className="self-start"
              onClick={() => setLines([...lines, emptyLine()])}
            >
              <Plus /> Add account
            </Button>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button onClick={() => void create()}>Create budget</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
