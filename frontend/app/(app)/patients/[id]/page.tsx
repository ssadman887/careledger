"use client";

import { ArrowLeft, FilePlus2, Plus, Wallet } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { PaymentDialog } from "@/components/billing/money-dialogs";
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
import { useDepartments } from "@/lib/api/hooks";
import { useAuth } from "@/lib/auth/auth-context";
import { humanize } from "@/lib/format";
import { can } from "@/lib/permissions";

type Patient = Schemas["PatientDetailOut"];
type Visit = Schemas["VisitOut"];
type Invoice = Schemas["InvoiceSummaryOut"];

function NewVisitDialog({
  open,
  onClose,
  onDone,
  patientId,
}: {
  open: boolean;
  onClose: () => void;
  onDone: () => void;
  patientId: number;
}) {
  const departments = useDepartments().filter((d) => d.code !== "ADMIN");
  const [deptId, setDeptId] = useState("");
  const [type, setType] = useState<Schemas["VisitType"]>("outpatient");
  const [admit, setAdmit] = useState(new Date().toISOString().slice(0, 10));
  const [discharge, setDischarge] = useState("");
  const [physician, setPhysician] = useState("");
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    if (!deptId) return setError("Choose a department");
    const { data, error: apiError } = await api.POST("/api/v1/visits", {
      body: {
        patient_id: patientId,
        department_id: Number(deptId),
        visit_type: type,
        admit_date: admit,
        discharge_date: discharge || null,
        attending_physician: physician,
      },
    });
    if (!data) return setError(errorMessage(apiError, "Could not create visit"));
    toast.success(`Visit ${data.visit_number} created`);
    onDone();
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New visit</DialogTitle>
          <DialogDescription>
            An admission or outpatient encounter that charges are captured against.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="flex flex-col gap-2">
            <Label htmlFor="nv-dept">Department</Label>
            <Select value={deptId} onValueChange={setDeptId}>
              <SelectTrigger id="nv-dept" className="w-full">
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
          <div className="flex flex-col gap-2">
            <Label htmlFor="nv-type">Type</Label>
            <Select value={type} onValueChange={(v) => setType(v as Schemas["VisitType"])}>
              <SelectTrigger id="nv-type" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {(["outpatient", "inpatient", "emergency"] as const).map((t) => (
                  <SelectItem key={t} value={t}>
                    {humanize(t)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="nv-admit">Admit date</Label>
            <Input id="nv-admit" type="date" value={admit} onChange={(e) => setAdmit(e.target.value)} />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="nv-discharge">Discharge date (optional)</Label>
            <Input
              id="nv-discharge"
              type="date"
              value={discharge}
              onChange={(e) => setDischarge(e.target.value)}
            />
          </div>
          <div className="flex flex-col gap-2 sm:col-span-2">
            <Label htmlFor="nv-doc">Attending physician</Label>
            <Input id="nv-doc" value={physician} onChange={(e) => setPhysician(e.target.value)} />
          </div>
        </div>
        {error && (
          <p role="alert" className="text-destructive text-sm">
            {error}
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={() => void submit()}>Create visit</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default function PatientPage() {
  const { id } = useParams<{ id: string }>();
  const patientId = Number(id);
  const { roles } = useAuth();
  const canBill = can(roles, "bill");
  const [patient, setPatient] = useState<Patient | null>(null);
  const [visits, setVisits] = useState<Visit[]>([]);
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [visitOpen, setVisitOpen] = useState(false);
  const [depositOpen, setDepositOpen] = useState(false);

  const load = useCallback(async () => {
    const [p, v, i] = await Promise.all([
      api.GET("/api/v1/patients/{patient_id}", { params: { path: { patient_id: patientId } } }),
      api.GET("/api/v1/visits", { params: { query: { patient_id: patientId, page_size: 100 } } }),
      api.GET("/api/v1/invoices", { params: { query: { patient_id: patientId, page_size: 100 } } }),
    ]);
    if (!p.data) return void toast.error(errorMessage(p.error, "Patient not found"));
    setPatient(p.data);
    setVisits(v.data?.items ?? []);
    setInvoices(i.data?.items ?? []);
  }, [patientId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (!patient) return <p className="text-muted-foreground">Loading…</p>;

  return (
    <>
      <Button asChild variant="ghost" size="sm" className="mb-2 -ml-2">
        <Link href="/patients">
          <ArrowLeft /> Patients
        </Link>
      </Button>
      <PageHeader
        title={patient.full_name}
        description={`${patient.mrn} · born ${patient.date_of_birth} · ${humanize(patient.sex)}`}
        actions={
          canBill ? (
            <>
              <Button variant="outline" onClick={() => setDepositOpen(true)}>
                <Wallet /> Record deposit
              </Button>
              <Button variant="outline" onClick={() => setVisitOpen(true)}>
                <Plus /> New visit
              </Button>
              <Button asChild>
                <Link href={`/invoices/new?patient=${patient.id}`}>
                  <FilePlus2 /> New invoice
                </Link>
              </Button>
            </>
          ) : undefined
        }
      />
      <div className="mb-6 grid gap-4 sm:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle className="text-muted-foreground text-sm font-normal">Unapplied deposit</CardTitle>
          </CardHeader>
          <CardContent className="text-2xl font-semibold">
            <Money value={patient.deposit_balance} />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-muted-foreground text-sm font-normal">Visits</CardTitle>
          </CardHeader>
          <CardContent className="text-2xl font-semibold">{visits.length}</CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-muted-foreground text-sm font-normal">Invoices</CardTitle>
          </CardHeader>
          <CardContent className="text-2xl font-semibold">{invoices.length}</CardContent>
        </Card>
      </div>

      <div className="grid gap-6 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Visits</CardTitle>
          </CardHeader>
          <CardContent className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Visit</TableHead>
                  <TableHead>Department</TableHead>
                  <TableHead>Admitted</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {visits.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={5} className="text-muted-foreground text-center">
                      No visits
                    </TableCell>
                  </TableRow>
                )}
                {visits.map((v) => (
                  <TableRow key={v.id}>
                    <TableCell className="font-mono text-sm">{v.visit_number}</TableCell>
                    <TableCell>
                      {v.department_name}
                      <span className="text-muted-foreground block text-xs">{humanize(v.visit_type)}</span>
                    </TableCell>
                    <TableCell>{v.admit_date}</TableCell>
                    <TableCell>
                      <StatusBadge status={v.status} />
                    </TableCell>
                    <TableCell className="text-right">
                      {canBill && v.status !== "cancelled" && (
                        <Button asChild size="sm" variant="ghost">
                          <Link href={`/invoices/new?patient=${patient.id}&visit=${v.id}`}>Bill</Link>
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Invoices</CardTitle>
          </CardHeader>
          <CardContent className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Invoice</TableHead>
                  <TableHead>Date</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Total</TableHead>
                  <TableHead className="text-right">Balance</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {invoices.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={5} className="text-muted-foreground text-center">
                      No invoices
                    </TableCell>
                  </TableRow>
                )}
                {invoices.map((i) => (
                  <TableRow key={i.id}>
                    <TableCell>
                      <Link href={`/invoices/${i.id}`} className="font-mono text-sm hover:underline">
                        {i.invoice_number}
                      </Link>
                    </TableCell>
                    <TableCell>{i.invoice_date ?? "—"}</TableCell>
                    <TableCell>
                      <StatusBadge status={i.status} />
                    </TableCell>
                    <TableCell className="text-right">
                      <Money value={i.total} />
                    </TableCell>
                    <TableCell className="text-right">
                      <Money value={i.balance_due} />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>
      <NewVisitDialog
        open={visitOpen}
        patientId={patient.id}
        onClose={() => setVisitOpen(false)}
        onDone={() => {
          setVisitOpen(false);
          void load();
        }}
      />
      <PaymentDialog
        open={depositOpen}
        patientId={patient.id}
        onClose={() => setDepositOpen(false)}
        onDone={() => {
          setDepositOpen(false);
          void load();
        }}
      />
    </>
  );
}
