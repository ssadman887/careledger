"use client";

import { Calculator, FileText, Plus, UserMinus } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

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
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api, errorMessage, type Schemas } from "@/lib/api/client";
import { openPayslipPdf } from "@/lib/api/download";
import { useDepartments } from "@/lib/api/hooks";
import { useAuth } from "@/lib/auth/auth-context";
import { MONEY_INPUT_PATTERN } from "@/lib/money";
import { can } from "@/lib/permissions";
import {
  MONTHS,
  periodLabel,
  rateToPercent,
  slabsToPayload,
  percentToRate,
  type SlabDraft,
} from "@/lib/payroll";

type Tab = "runs" | "employees" | "tax";
const TABS: { id: Tab; label: string }[] = [
  { id: "runs", label: "Payroll runs" },
  { id: "employees", label: "Employees" },
  { id: "tax", label: "Tax slabs" },
];
type Employee = Schemas["EmployeeOut"];
const today = () => new Date().toISOString().slice(0, 10);

// ------------------------------------------------------------------ runs

function Runs() {
  const router = useRouter();
  const { roles } = useAuth();
  const [rows, setRows] = useState<Schemas["PayrollRunOut"][]>([]);
  const [open, setOpen] = useState(false);
  const now = new Date();
  const [year, setYear] = useState(String(now.getFullYear()));
  const [month, setMonth] = useState(String(now.getMonth() + 1));
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void api
      .GET("/api/v1/payroll/runs", { params: { query: { page_size: 50 } } })
      .then(({ data }) => setRows(data?.items ?? []));
  }, []);

  const create = async () => {
    setBusy(true);
    const { data, error } = await api.POST("/api/v1/payroll/runs", {
      body: { year: Number(year), month: Number(month), background: true },
    });
    setBusy(false);
    if (!data) return void toast.error(errorMessage(error, "Could not start the run"));
    toast.success(`${data.run_number} queued for calculation`);
    router.push(`/payroll/runs/${data.id}`);
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-muted-foreground text-sm">
          Accountants prepare the monthly run (calculated by the background job); a finance manager approves
          it, which posts salaries to the ledger; payment clears salaries payable.
        </p>
        {can(roles, "managePayroll") && (
          <Button onClick={() => setOpen(true)}>
            <Plus /> New payroll run
          </Button>
        )}
      </div>
      <div className="bg-card overflow-x-auto rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Run</TableHead>
              <TableHead>Period</TableHead>
              <TableHead>Status</TableHead>
              <TableHead className="text-right">Employees</TableHead>
              <TableHead className="text-right">Gross</TableHead>
              <TableHead className="text-right">Tax</TableHead>
              <TableHead className="text-right">Net pay</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.length === 0 && (
              <TableRow>
                <TableCell colSpan={7} className="text-muted-foreground h-20 text-center">
                  No payroll runs yet.
                </TableCell>
              </TableRow>
            )}
            {rows.map((r) => (
              <TableRow key={r.id}>
                <TableCell>
                  <Link href={`/payroll/runs/${r.id}`} className="font-mono text-sm hover:underline">
                    {r.run_number}
                  </Link>
                </TableCell>
                <TableCell>{periodLabel(r.year, r.month)}</TableCell>
                <TableCell>
                  <StatusBadge status={r.status} />
                </TableCell>
                <TableCell className="text-right tabular-nums">{r.employee_count}</TableCell>
                <TableCell className="text-right">
                  <Money value={r.gross_total} />
                </TableCell>
                <TableCell className="text-right">
                  <Money value={r.tax_total} />
                </TableCell>
                <TableCell className="text-right font-medium">
                  <Money value={r.net_total} />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>New payroll run</DialogTitle>
            <DialogDescription>
              Payslips are calculated in the background from current employee records and the year&apos;s tax
              slabs. You can recalculate until the run is submitted.
            </DialogDescription>
          </DialogHeader>
          <div className="grid grid-cols-2 gap-3">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="run-month">Month</Label>
              <Select value={month} onValueChange={setMonth}>
                <SelectTrigger id="run-month">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {MONTHS.map((m, i) => (
                    <SelectItem key={m} value={String(i + 1)}>
                      {m}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="run-year">Year</Label>
              <Input
                id="run-year"
                inputMode="numeric"
                value={year}
                onChange={(e) => setYear(e.target.value)}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button onClick={() => void create()} disabled={busy}>
              Start run
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

// ------------------------------------------------------------------ employees

interface EmployeeDraft {
  first_name: string;
  last_name: string;
  department_id: string;
  position: string;
  hire_date: string;
  basic_salary: string;
  housing_allowance: string;
  transport_allowance: string;
  other_allowance: string;
  pension_percent: string;
  other_deduction: string;
  bank_reference: string;
}

const EMPTY_DRAFT: EmployeeDraft = {
  first_name: "",
  last_name: "",
  department_id: "",
  position: "",
  hire_date: today(),
  basic_salary: "",
  housing_allowance: "0.00",
  transport_allowance: "0.00",
  other_allowance: "0.00",
  pension_percent: "5",
  other_deduction: "0.00",
  bank_reference: "",
};

function draftFrom(e: Employee): EmployeeDraft {
  return {
    first_name: e.first_name,
    last_name: e.last_name,
    department_id: String(e.department_id),
    position: e.position,
    hire_date: e.hire_date,
    basic_salary: e.basic_salary,
    housing_allowance: e.housing_allowance,
    transport_allowance: e.transport_allowance,
    other_allowance: e.other_allowance,
    pension_percent: rateToPercent(e.pension_rate),
    other_deduction: e.other_deduction,
    bank_reference: e.bank_reference,
  };
}

const MONEY_FIELDS = [
  ["basic_salary", "Basic salary"],
  ["housing_allowance", "Housing allowance"],
  ["transport_allowance", "Transport allowance"],
  ["other_allowance", "Other allowance"],
  ["other_deduction", "Other deduction"],
] as const;

function EmployeeForm({ draft, set }: { draft: EmployeeDraft; set: (d: EmployeeDraft) => void }) {
  const departments = useDepartments();
  const field = (key: keyof EmployeeDraft, label: string, props: Record<string, string> = {}) => (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={`emp-${key}`}>{label}</Label>
      <Input
        id={`emp-${key}`}
        value={draft[key]}
        onChange={(e) => set({ ...draft, [key]: e.target.value })}
        {...props}
      />
    </div>
  );
  return (
    <div className="grid grid-cols-2 gap-3">
      {field("first_name", "First name")}
      {field("last_name", "Last name")}
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="emp-department">Department</Label>
        <Select value={draft.department_id} onValueChange={(v) => set({ ...draft, department_id: v })}>
          <SelectTrigger id="emp-department">
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
      {field("position", "Position")}
      {field("hire_date", "Hire date", { type: "date" })}
      {field("bank_reference", "Bank reference")}
      {MONEY_FIELDS.map(([key, label]) => (
        <div key={key}>{field(key, label, { inputMode: "decimal" })}</div>
      ))}
      {field("pension_percent", "Pension %", { inputMode: "decimal" })}
    </div>
  );
}

function toEmployeeBody(d: EmployeeDraft): Schemas["EmployeeCreate"] | string {
  if (!d.first_name.trim() || !d.last_name.trim() || !d.position.trim())
    return "Name and position are required";
  if (!d.department_id) return "Choose a department";
  for (const [key, label] of MONEY_FIELDS)
    if (!MONEY_INPUT_PATTERN.test(d[key])) return `${label}: enter an amount like 1250.00`;
  const pension = percentToRate(d.pension_percent);
  if (pension === null || Number(pension) > 0.2) return "Pension must be 0-20%";
  return {
    first_name: d.first_name.trim(),
    last_name: d.last_name.trim(),
    department_id: Number(d.department_id),
    position: d.position.trim(),
    hire_date: d.hire_date,
    basic_salary: d.basic_salary,
    housing_allowance: d.housing_allowance,
    transport_allowance: d.transport_allowance,
    other_allowance: d.other_allowance,
    pension_rate: pension,
    other_deduction: d.other_deduction,
    bank_reference: d.bank_reference.trim(),
  };
}

function Employees() {
  const { roles } = useAuth();
  const canManage = can(roles, "managePayroll");
  const departments = useDepartments();
  const [rows, setRows] = useState<Employee[]>([]);
  const [search, setSearch] = useState("");
  const [dept, setDept] = useState("all");
  const [mode, setMode] = useState<"create" | "edit" | null>(null);
  const [draft, setDraft] = useState<EmployeeDraft>(EMPTY_DRAFT);
  const [selected, setSelected] = useState<Employee | null>(null);
  const [slips, setSlips] = useState<Schemas["PayslipOut"][]>([]);
  const [terminateOn, setTerminateOn] = useState(today());

  const load = useCallback(async () => {
    const { data } = await api.GET("/api/v1/payroll/employees", {
      params: {
        query: {
          page_size: 100,
          search: search || undefined,
          department_id: dept === "all" ? undefined : Number(dept),
        },
      },
    });
    setRows(data?.items ?? []);
  }, [search, dept]);
  useEffect(() => {
    void load();
  }, [load]);

  const openEmployee = async (e: Employee) => {
    setSelected(e);
    setTerminateOn(today());
    const { data } = await api.GET("/api/v1/payroll/employees/{employee_id}/payslips", {
      params: { path: { employee_id: e.id } },
    });
    setSlips(data ?? []);
  };

  const save = async () => {
    const body = toEmployeeBody(draft);
    if (typeof body === "string") return void toast.error(body);
    if (mode === "create") {
      const { data, error } = await api.POST("/api/v1/payroll/employees", { body });
      if (!data) return void toast.error(errorMessage(error, "Could not add employee"));
      toast.success(`${data.employee_number} ${data.full_name} added`);
    } else if (selected) {
      const { hire_date: _hire, ...changes } = body;
      void _hire;
      const { data, error } = await api.PATCH("/api/v1/payroll/employees/{employee_id}", {
        params: { path: { employee_id: selected.id } },
        body: changes,
      });
      if (!data) return void toast.error(errorMessage(error, "Could not save"));
      toast.success("Employee updated; recalculate open runs to apply");
      setSelected(data);
    }
    setMode(null);
    void load();
  };

  const terminate = async () => {
    if (!selected) return;
    const { data, error } = await api.POST("/api/v1/payroll/employees/{employee_id}/terminate", {
      params: { path: { employee_id: selected.id } },
      body: { termination_date: terminateOn },
    });
    if (!data) return void toast.error(errorMessage(error, "Could not terminate"));
    toast.success(`${data.full_name} terminated from ${data.termination_date}`);
    setSelected(data);
    void load();
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="emp-search">Search</Label>
          <Input
            id="emp-search"
            placeholder="Name, number or position"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-64"
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="emp-dept-filter">Department</Label>
          <Select value={dept} onValueChange={setDept}>
            <SelectTrigger id="emp-dept-filter" className="w-48">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All departments</SelectItem>
              {departments.map((d) => (
                <SelectItem key={d.id} value={String(d.id)}>
                  {d.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        {canManage && (
          <Button
            className="ml-auto"
            onClick={() => {
              setDraft(EMPTY_DRAFT);
              setMode("create");
            }}
          >
            <Plus /> Add employee
          </Button>
        )}
      </div>
      <div className="bg-card overflow-x-auto rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Employee</TableHead>
              <TableHead>Department</TableHead>
              <TableHead>Position</TableHead>
              <TableHead>Status</TableHead>
              <TableHead className="text-right">Basic</TableHead>
              <TableHead className="text-right">Monthly gross</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((e) => (
              <TableRow key={e.id}>
                <TableCell>
                  <button
                    type="button"
                    className="text-left hover:underline"
                    onClick={() => void openEmployee(e)}
                  >
                    {e.full_name}
                  </button>
                  <span className="text-muted-foreground block font-mono text-xs">{e.employee_number}</span>
                </TableCell>
                <TableCell>{e.department_name}</TableCell>
                <TableCell>{e.position}</TableCell>
                <TableCell>
                  <StatusBadge status={e.status} />
                </TableCell>
                <TableCell className="text-right">
                  <Money value={e.basic_salary} />
                </TableCell>
                <TableCell className="text-right font-medium">
                  <Money value={e.monthly_gross} />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <Dialog open={mode !== null} onOpenChange={(o) => !o && setMode(null)}>
        <DialogContent className="sm:max-w-xl">
          <DialogHeader>
            <DialogTitle>{mode === "create" ? "Add employee" : "Edit employee"}</DialogTitle>
            <DialogDescription>
              Synthetic data only. Salary components are monthly amounts; changes apply to runs calculated
              afterwards.
            </DialogDescription>
          </DialogHeader>
          <EmployeeForm draft={draft} set={setDraft} />
          <DialogFooter>
            <Button variant="outline" onClick={() => setMode(null)}>
              Cancel
            </Button>
            <Button onClick={() => void save()}>{mode === "create" ? "Add employee" : "Save changes"}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={selected !== null && mode === null} onOpenChange={(o) => !o && setSelected(null)}>
        <DialogContent className="sm:max-w-2xl">
          {selected && (
            <>
              <DialogHeader>
                <DialogTitle>
                  {selected.full_name}{" "}
                  <span className="text-muted-foreground font-mono text-sm">{selected.employee_number}</span>
                </DialogTitle>
                <DialogDescription>
                  {selected.position}, {selected.department_name} · hired {selected.hire_date}
                  {selected.termination_date ? ` · left ${selected.termination_date}` : ""} · bank{" "}
                  {selected.bank_reference || "—"}
                </DialogDescription>
              </DialogHeader>
              <div className="grid grid-cols-3 gap-3 text-sm">
                {(
                  [
                    ["Basic", selected.basic_salary],
                    ["Housing", selected.housing_allowance],
                    ["Transport", selected.transport_allowance],
                    ["Other allowance", selected.other_allowance],
                    ["Other deduction", selected.other_deduction],
                  ] as const
                ).map(([label, v]) => (
                  <div key={label}>
                    <span className="text-muted-foreground block text-xs">{label}</span>
                    <Money value={v} />
                  </div>
                ))}
                <div>
                  <span className="text-muted-foreground block text-xs">Pension</span>
                  {rateToPercent(selected.pension_rate)}%
                </div>
              </div>
              <h3 className="mt-2 text-sm font-medium">Payslips</h3>
              <div className="max-h-64 overflow-y-auto rounded border">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Run</TableHead>
                      <TableHead className="text-right">Days</TableHead>
                      <TableHead className="text-right">Gross</TableHead>
                      <TableHead className="text-right">Net</TableHead>
                      <TableHead />
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {slips.length === 0 && (
                      <TableRow>
                        <TableCell colSpan={5} className="text-muted-foreground text-center">
                          No payslips yet.
                        </TableCell>
                      </TableRow>
                    )}
                    {slips.map((s) => (
                      <TableRow key={s.id}>
                        <TableCell>
                          <Link href={`/payroll/runs/${s.payroll_run_id}`} className="hover:underline">
                            Run #{s.payroll_run_id}
                          </Link>
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {s.days_worked}/{s.days_in_month}
                        </TableCell>
                        <TableCell className="text-right">
                          <Money value={s.gross} />
                        </TableCell>
                        <TableCell className="text-right">
                          <Money value={s.net} />
                        </TableCell>
                        <TableCell className="text-right">
                          <Button
                            variant="ghost"
                            size="sm"
                            aria-label={`Payslip PDF for run ${s.payroll_run_id}`}
                            onClick={() =>
                              void openPayslipPdf(
                                s.id,
                                `payslip-${s.employee_number}-${s.payroll_run_id}.pdf`,
                              )
                            }
                          >
                            <FileText />
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
              {canManage && (
                <DialogFooter className="items-end gap-2 sm:justify-between">
                  {selected.status === "active" ? (
                    <div className="flex items-end gap-2">
                      <div className="flex flex-col gap-1.5">
                        <Label htmlFor="terminate-on">Last working day</Label>
                        <Input
                          id="terminate-on"
                          type="date"
                          value={terminateOn}
                          onChange={(e) => setTerminateOn(e.target.value)}
                        />
                      </div>
                      <Button variant="outline" onClick={() => void terminate()}>
                        <UserMinus /> Terminate
                      </Button>
                    </div>
                  ) : (
                    <span />
                  )}
                  <Button
                    onClick={() => {
                      setDraft(draftFrom(selected));
                      setMode("edit");
                    }}
                  >
                    Edit salary and details
                  </Button>
                </DialogFooter>
              )}
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}

// ------------------------------------------------------------------ tax slabs

function TaxSlabs() {
  const { roles } = useAuth();
  const [year, setYear] = useState(String(new Date().getFullYear()));
  const [table, setTable] = useState<Schemas["TaxTableOut"] | null>(null);
  const [drafts, setDrafts] = useState<SlabDraft[]>([]);
  const [editing, setEditing] = useState(false);
  const [taxable, setTaxable] = useState("5000.00");
  const [preview, setPreview] = useState<Schemas["TaxPreviewOut"] | null>(null);

  const load = useCallback(async () => {
    const { data } = await api.GET("/api/v1/payroll/tax-slabs/{year}", {
      params: { path: { year: Number(year) } },
    });
    setTable(data ?? null);
    setDrafts(
      (data?.slabs ?? []).map((s) => ({
        lower_bound: s.lower_bound,
        upper_bound: s.upper_bound ?? "",
        rate_percent: rateToPercent(s.rate),
      })),
    );
    setEditing(false);
  }, [year]);
  useEffect(() => {
    void load();
  }, [load]);

  const save = async () => {
    const payload = slabsToPayload(drafts);
    if ("error" in payload) return void toast.error(payload.error);
    const { data, error } = await api.PUT("/api/v1/payroll/tax-slabs/{year}", {
      params: { path: { year: Number(year) } },
      body: payload,
    });
    if (!data) return void toast.error(errorMessage(error, "Could not save slabs"));
    toast.success(`${year} tax slabs saved`);
    void load();
  };

  const runPreview = async () => {
    if (!MONEY_INPUT_PATTERN.test(taxable)) return void toast.error("Enter an amount like 5000.00");
    const { data, error } = await api.POST("/api/v1/payroll/tax-preview", {
      body: { year: Number(year), monthly_taxable: taxable },
    });
    if (!data) return void toast.error(errorMessage(error, "Preview failed"));
    setPreview(data);
  };

  const canEdit = can(roles, "editTaxSlabs") && table !== null && !table.locked;
  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_340px] [&>*]:min-w-0">
      <Card>
        <CardHeader className="flex flex-row flex-wrap items-end justify-between gap-3">
          <div>
            <CardTitle className="text-base">Annual income-tax bands</CardTitle>
            <p className="text-muted-foreground text-xs">
              Monthly tax = tax on (taxable pay × 12) using these bands, ÷ 12, rounded half-up.
              {table?.locked && " Locked: this year already has submitted or posted runs."}
            </p>
          </div>
          <div className="flex items-end gap-2">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="tax-year">Year</Label>
              <Input id="tax-year" className="w-24" value={year} onChange={(e) => setYear(e.target.value)} />
            </div>
            {canEdit && !editing && (
              <Button variant="outline" onClick={() => setEditing(true)}>
                Edit bands
              </Button>
            )}
          </div>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>From</TableHead>
                <TableHead>Up to</TableHead>
                <TableHead className="text-right">Rate</TableHead>
                {editing && <TableHead />}
              </TableRow>
            </TableHeader>
            <TableBody>
              {drafts.length === 0 && !editing && (
                <TableRow>
                  <TableCell colSpan={3} className="text-muted-foreground text-center">
                    No bands defined for {year}.
                  </TableCell>
                </TableRow>
              )}
              {drafts.map((d, i) =>
                editing ? (
                  <TableRow key={i}>
                    {(["lower_bound", "upper_bound", "rate_percent"] as const).map((k) => (
                      <TableCell key={k}>
                        <Input
                          aria-label={`${k.replace("_", " ")}, band ${i + 1}`}
                          value={d[k]}
                          placeholder={k === "upper_bound" ? "No limit" : ""}
                          onChange={(e) =>
                            setDrafts(drafts.map((x, j) => (j === i ? { ...x, [k]: e.target.value } : x)))
                          }
                        />
                      </TableCell>
                    ))}
                    <TableCell>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setDrafts(drafts.filter((_, j) => j !== i))}
                      >
                        Remove
                      </Button>
                    </TableCell>
                  </TableRow>
                ) : (
                  <TableRow key={i}>
                    <TableCell>
                      <Money value={d.lower_bound} />
                    </TableCell>
                    <TableCell>{d.upper_bound ? <Money value={d.upper_bound} /> : "No limit"}</TableCell>
                    <TableCell className="text-right tabular-nums">{d.rate_percent}%</TableCell>
                  </TableRow>
                ),
              )}
            </TableBody>
          </Table>
          {editing && (
            <div className="mt-3 flex gap-2">
              <Button
                variant="outline"
                onClick={() =>
                  setDrafts([
                    ...drafts,
                    { lower_bound: drafts.at(-1)?.upper_bound ?? "0.00", upper_bound: "", rate_percent: "0" },
                  ])
                }
              >
                <Plus /> Add band
              </Button>
              <Button onClick={() => void save()}>Save bands</Button>
              <Button variant="ghost" onClick={() => void load()}>
                Cancel
              </Button>
            </div>
          )}
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Tax calculator</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <div className="flex items-end gap-2">
            <div className="flex flex-1 flex-col gap-1.5">
              <Label htmlFor="tax-taxable">Monthly taxable pay</Label>
              <Input
                id="tax-taxable"
                inputMode="decimal"
                value={taxable}
                onChange={(e) => setTaxable(e.target.value)}
              />
            </div>
            <Button variant="outline" onClick={() => void runPreview()}>
              <Calculator /> Calculate
            </Button>
          </div>
          {preview && (
            <dl className="grid grid-cols-2 gap-y-1 text-sm">
              <dt className="text-muted-foreground">Annual taxable</dt>
              <dd className="text-right">
                <Money value={preview.annual_taxable} />
              </dd>
              <dt className="text-muted-foreground">Annual tax</dt>
              <dd className="text-right">
                <Money value={preview.annual_tax} />
              </dd>
              <dt className="text-muted-foreground">Monthly tax</dt>
              <dd className="text-right font-semibold">
                <Money value={preview.monthly_tax} />
              </dd>
              <dt className="text-muted-foreground">Effective rate</dt>
              <dd className="text-right tabular-nums">{preview.effective_rate_percent}%</dd>
            </dl>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function PayrollInner() {
  const router = useRouter();
  const params = useSearchParams();
  const tab = (TABS.find((t) => t.id === params.get("tab"))?.id ?? "runs") as Tab;
  return (
    <>
      <PageHeader
        title="Payroll"
        description="Employees, salary structures, income-tax slabs and monthly payroll runs."
      />
      <Tabs value={tab} onValueChange={(t) => router.replace(`/payroll?tab=${t}`)} className="mb-4">
        <TabsList>
          {TABS.map((t) => (
            <TabsTrigger key={t.id} value={t.id}>
              {t.label}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>
      {tab === "runs" && <Runs />}
      {tab === "employees" && <Employees />}
      {tab === "tax" && <TaxSlabs />}
    </>
  );
}

export default function PayrollPage() {
  return (
    <Suspense fallback={<p className="text-muted-foreground">Loading…</p>}>
      <PayrollInner />
    </Suspense>
  );
}
