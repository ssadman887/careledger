"use client";

import { ArrowLeft, FileText, Loader2, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { Money } from "@/components/money";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
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
import {
  Table,
  TableBody,
  TableCell,
  TableFooter,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { api, errorMessage, type Schemas } from "@/lib/api/client";
import { openPayslipPdf } from "@/lib/api/download";
import { useAuth } from "@/lib/auth/auth-context";
import { formatDateTime } from "@/lib/format";
import { useIdempotencyKey } from "@/lib/idempotency";
import { sumMoney } from "@/lib/money";
import { periodLabel } from "@/lib/payroll";
import { can } from "@/lib/permissions";

type Run = Schemas["PayrollRunDetail"];
type DialogKind = "reject" | "pay" | null;
const POLL_MS = 1500;

export default function PayrollRunPage() {
  const { id } = useParams<{ id: string }>();
  const { roles, user } = useAuth();
  const idem = useIdempotencyKey();
  const [run, setRun] = useState<Run | null>(null);
  const [dialog, setDialog] = useState<DialogKind>(null);
  const [note, setNote] = useState("");
  const [paidOn, setPaidOn] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const { data, error } = await api.GET("/api/v1/payroll/runs/{run_id}", {
      params: { path: { run_id: Number(id) } },
    });
    if (!data) return void toast.error(errorMessage(error, "Payroll run not found"));
    setRun(data);
  }, [id]);
  useEffect(() => {
    void load();
  }, [load]);
  // The background job calculates queued runs; poll until it is done.
  useEffect(() => {
    if (run?.status !== "queued") return;
    const t = setTimeout(() => void load(), POLL_MS);
    return () => clearTimeout(t);
  }, [run, load]);

  if (!run) return <p className="text-muted-foreground">Loading…</p>;

  const path = { params: { path: { run_id: run.id } } };
  const canPrepare = can(roles, "managePayroll");
  const canApprove = can(roles, "approvePayroll") && run.created_by_id !== user?.id;
  const readLedger = can(roles, "readLedger");

  const act = async (
    label: string,
    call: () => Promise<{ data?: Run; error?: unknown }>,
    success: (r: Run) => string,
  ) => {
    setBusy(true);
    const { data, error } = await call();
    setBusy(false);
    if (!data) return void toast.error(errorMessage(error, `Could not ${label}`));
    toast.success(success(data));
    setRun(data);
    setDialog(null);
  };

  const recalc = () =>
    act(
      "recalculate",
      () => api.POST("/api/v1/payroll/runs/{run_id}/recalculate", path),
      (r) => `Recalculated: ${r.employee_count} payslips`,
    );
  const submit = () =>
    act(
      "submit",
      () => api.POST("/api/v1/payroll/runs/{run_id}/submit", path),
      (r) =>
        r.status === "posted"
          ? `${r.run_number} posted`
          : `${r.run_number} sent for finance-manager approval`,
    );
  const approve = () =>
    act(
      "approve",
      () => api.POST("/api/v1/payroll/runs/{run_id}/approve", { ...path, body: { note: "" } }),
      (r) => `${r.run_number} approved and posted to the ledger`,
    );
  const reject = () =>
    act(
      "reject",
      () => api.POST("/api/v1/payroll/runs/{run_id}/reject", { ...path, body: { note } }),
      (r) => `${r.run_number} returned to payroll`,
    );
  const pay = async () => {
    await act(
      "pay",
      () =>
        api.POST("/api/v1/payroll/runs/{run_id}/pay", {
          params: { path: { run_id: run.id }, header: { "Idempotency-Key": idem.key() } },
          body: { paid_on: paidOn || null },
        }),
      (r) => `${r.run_number} paid`,
    );
    idem.reset();
  };

  const deductions = sumMoney([run.pension_total, run.other_deduction_total]);
  const rejected = run.status === "calculated" && run.error?.startsWith("Rejected:");

  return (
    <>
      <Button asChild variant="ghost" size="sm" className="mb-2 -ml-2">
        <Link href="/payroll">
          <ArrowLeft /> Payroll runs
        </Link>
      </Button>
      <PageHeader
        title={`${run.run_number} · ${periodLabel(run.year, run.month)}`}
        description={`Period ${run.period_start} to ${run.period_end} · pay date ${run.pay_date}${
          run.calculated_at ? ` · calculated ${formatDateTime(run.calculated_at)}` : ""
        }`}
        actions={
          <>
            {canPrepare && (run.status === "calculated" || run.status === "failed") && (
              <Button variant="outline" onClick={() => void recalc()} disabled={busy}>
                <RefreshCw /> Recalculate
              </Button>
            )}
            {canPrepare && run.status === "calculated" && (
              <Button onClick={() => void submit()} disabled={busy}>
                Submit for approval
              </Button>
            )}
            {canApprove && run.status === "pending_approval" && (
              <>
                <Button
                  variant="outline"
                  onClick={() => {
                    setNote("");
                    setDialog("reject");
                  }}
                >
                  Reject
                </Button>
                <Button onClick={() => void approve()} disabled={busy}>
                  Approve and post
                </Button>
              </>
            )}
            {canPrepare && run.status === "posted" && (
              <Button
                onClick={() => {
                  setPaidOn(run.pay_date);
                  setDialog("pay");
                }}
              >
                Pay salaries
              </Button>
            )}
          </>
        }
      />

      {run.status === "queued" && (
        <Alert className="mb-4">
          <Loader2 className="animate-spin" />
          <AlertTitle>Calculating in the background</AlertTitle>
          <AlertDescription>
            The payroll job is computing payslips. This page refreshes automatically.
          </AlertDescription>
        </Alert>
      )}
      {(run.status === "failed" || rejected) && (
        <Alert variant="destructive" className="mb-4">
          <AlertTitle>{run.status === "failed" ? "Calculation failed" : "Returned by finance"}</AlertTitle>
          <AlertDescription>{run.error}</AlertDescription>
        </Alert>
      )}
      {run.status === "pending_approval" && !canApprove && (
        <Alert className="mb-4">
          <AlertTitle>Awaiting finance-manager approval</AlertTitle>
          <AlertDescription>
            A finance manager who did not prepare this run must approve it.{" "}
            {run.approval_id && (
              <Link href="/approvals" className="underline">
                Open the approvals inbox
              </Link>
            )}
          </AlertDescription>
        </Alert>
      )}

      <div className="mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-5">
        {(
          [
            ["Status", <StatusBadge key="s" status={run.status} />],
            [
              "Employees",
              <span key="e" className="tabular-nums">
                {run.employee_count}
              </span>,
            ],
            ["Gross pay", <Money key="g" value={run.gross_total} />],
            ["Tax and deductions", <Money key="d" value={sumMoney([run.tax_total, deductions])} />],
            ["Net pay", <Money key="n" value={run.net_total} className="font-semibold" />],
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

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[1fr_340px] [&>*]:min-w-0">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Payslips</CardTitle>
          </CardHeader>
          <CardContent className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Employee</TableHead>
                  <TableHead>Department</TableHead>
                  <TableHead className="text-right">Days</TableHead>
                  <TableHead className="text-right">Gross</TableHead>
                  <TableHead className="text-right">Pension</TableHead>
                  <TableHead className="text-right">Tax</TableHead>
                  <TableHead className="text-right">Other</TableHead>
                  <TableHead className="text-right">Net</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {run.payslips.map((s) => (
                  <TableRow key={s.id}>
                    <TableCell>
                      {s.employee_name}
                      <span className="text-muted-foreground block font-mono text-xs">
                        {s.employee_number} · {s.position}
                      </span>
                    </TableCell>
                    <TableCell>{s.department_name}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      {s.days_worked < s.days_in_month ? (
                        <span title="Prorated">
                          {s.days_worked}/{s.days_in_month}*
                        </span>
                      ) : (
                        s.days_in_month
                      )}
                    </TableCell>
                    <TableCell className="text-right">
                      <Money value={s.gross} />
                    </TableCell>
                    <TableCell className="text-right">
                      <Money value={s.pension} hideZero />
                    </TableCell>
                    <TableCell className="text-right">
                      <Money value={s.income_tax} hideZero />
                    </TableCell>
                    <TableCell className="text-right">
                      <Money value={s.other_deduction} hideZero />
                    </TableCell>
                    <TableCell className="text-right font-medium">
                      <Money value={s.net} />
                    </TableCell>
                    <TableCell>
                      <Button
                        variant="ghost"
                        size="sm"
                        aria-label={`Payslip PDF for ${s.employee_name}`}
                        onClick={() =>
                          void openPayslipPdf(s.id, `payslip-${run.run_number}-${s.employee_number}.pdf`)
                        }
                      >
                        <FileText />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
              {run.payslips.length > 0 && (
                <TableFooter>
                  <TableRow>
                    <TableCell colSpan={3}>Totals</TableCell>
                    <TableCell className="text-right">
                      <Money value={run.gross_total} />
                    </TableCell>
                    <TableCell className="text-right">
                      <Money value={run.pension_total} />
                    </TableCell>
                    <TableCell className="text-right">
                      <Money value={run.tax_total} />
                    </TableCell>
                    <TableCell className="text-right">
                      <Money value={run.other_deduction_total} />
                    </TableCell>
                    <TableCell className="text-right">
                      <Money value={run.net_total} />
                    </TableCell>
                    <TableCell />
                  </TableRow>
                </TableFooter>
              )}
            </Table>
            {run.payslips.some((s) => s.days_worked < s.days_in_month) && (
              <p className="text-muted-foreground mt-2 text-xs">
                * Prorated by calendar days employed (joined or left during the month).
              </p>
            )}
          </CardContent>
        </Card>

        <div className="flex flex-col gap-6">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">By department</CardTitle>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Department</TableHead>
                    <TableHead className="text-right">Staff</TableHead>
                    <TableHead className="text-right">Gross</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {run.departments.map((d) => (
                    <TableRow key={d.department_id}>
                      <TableCell>{d.department_name}</TableCell>
                      <TableCell className="text-right tabular-nums">{d.headcount}</TableCell>
                      <TableCell className="text-right">
                        <Money value={d.gross} />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Ledger</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-2 text-sm">
              <p className="text-muted-foreground text-xs">
                Approval posts Dr 5100 Salaries (per department) / Cr 2110 tax, 2120 deductions, 2100 net pay.
                Payment funds 1030 Bank-Payroll from 1020 and clears 2100.
              </p>
              {(
                [
                  ["Salary posting", run.posting_entry_id],
                  ["Payroll account funding", run.funding_entry_id],
                  ["Net pay payment", run.payment_entry_id],
                ] as const
              ).map(([label, entryId]) => (
                <div key={label} className="flex justify-between">
                  <span>{label}</span>
                  {entryId ? (
                    readLedger ? (
                      <Link href={`/journal/${entryId}`} className="hover:underline">
                        View entry
                      </Link>
                    ) : (
                      <span className="text-muted-foreground">Posted</span>
                    )
                  ) : (
                    <span className="text-muted-foreground">—</span>
                  )}
                </div>
              ))}
            </CardContent>
          </Card>
        </div>
      </div>

      <Dialog open={dialog !== null} onOpenChange={(o) => !o && setDialog(null)}>
        <DialogContent>
          {dialog === "reject" ? (
            <>
              <DialogHeader>
                <DialogTitle>Return {run.run_number} to payroll</DialogTitle>
                <DialogDescription>
                  The run goes back to calculated so it can be corrected and resubmitted.
                </DialogDescription>
              </DialogHeader>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="reject-note">Reason</Label>
                <Textarea id="reject-note" value={note} onChange={(e) => setNote(e.target.value)} />
              </div>
              <DialogFooter>
                <Button variant="outline" onClick={() => setDialog(null)}>
                  Cancel
                </Button>
                <Button variant="destructive" onClick={() => void reject()} disabled={busy || !note.trim()}>
                  Reject run
                </Button>
              </DialogFooter>
            </>
          ) : (
            <>
              <DialogHeader>
                <DialogTitle>Pay {run.run_number}</DialogTitle>
                <DialogDescription>
                  Transfers <Money value={run.net_total} /> net pay to {run.employee_count} employees
                  (simulated).
                </DialogDescription>
              </DialogHeader>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="paid-on">Payment date</Label>
                <Input id="paid-on" type="date" value={paidOn} onChange={(e) => setPaidOn(e.target.value)} />
              </div>
              <DialogFooter>
                <Button variant="outline" onClick={() => setDialog(null)}>
                  Cancel
                </Button>
                <Button onClick={() => void pay()} disabled={busy}>
                  Confirm payment
                </Button>
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
