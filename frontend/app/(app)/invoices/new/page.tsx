"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { toast } from "sonner";

import { PatientPicker } from "@/components/billing/patient-picker";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { api, errorMessage, type Schemas } from "@/lib/api/client";

type Patient = Schemas["PatientOut"];
type Visit = Schemas["VisitOut"];
const NO_VISIT = "none";

function NewInvoice() {
  const router = useRouter();
  const params = useSearchParams();
  const [patient, setPatient] = useState<Patient | null>(null);
  const [visits, setVisits] = useState<Visit[]>([]);
  const [visitId, setVisitId] = useState(params.get("visit") ?? NO_VISIT);
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const pid = params.get("patient");
    if (pid) {
      void api
        .GET("/api/v1/patients/{patient_id}", { params: { path: { patient_id: Number(pid) } } })
        .then(({ data }) => data && setPatient(data));
    }
  }, [params]);

  useEffect(() => {
    if (!patient) return setVisits([]);
    void api
      .GET("/api/v1/visits", { params: { query: { patient_id: patient.id, page_size: 50 } } })
      .then(({ data }) => setVisits((data?.items ?? []).filter((v) => v.status !== "cancelled")));
  }, [patient]);

  const create = async () => {
    if (!patient) return;
    setBusy(true);
    const { data, error } = await api.POST("/api/v1/invoices", {
      body: { patient_id: patient.id, visit_id: visitId === NO_VISIT ? null : Number(visitId), notes },
    });
    setBusy(false);
    if (!data) return void toast.error(errorMessage(error, "Could not create invoice"));
    toast.success(`Draft ${data.invoice_number} created. Add charges next.`);
    router.push(`/invoices/${data.id}`);
  };

  return (
    <>
      <PageHeader
        title="New invoice"
        description="Create a draft for a patient (and optionally a visit), then capture charges."
      />
      <Card className="max-w-2xl">
        <CardContent className="flex flex-col gap-5">
          <PatientPicker
            value={patient}
            onChange={(p) => {
              setPatient(p);
              setVisitId(NO_VISIT);
            }}
          />
          {patient && (
            <div className="flex flex-col gap-2">
              <Label htmlFor="new-inv-visit">Visit</Label>
              <Select value={visitId} onValueChange={setVisitId}>
                <SelectTrigger id="new-inv-visit" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={NO_VISIT}>No visit (walk-in charges)</SelectItem>
                  {visits.map((v) => (
                    <SelectItem key={v.id} value={String(v.id)}>
                      {v.visit_number} · {v.department_name} · {v.admit_date}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
          <div className="flex flex-col gap-2">
            <Label htmlFor="new-inv-notes">Notes</Label>
            <Textarea id="new-inv-notes" rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />
          </div>
          <div className="flex gap-2">
            <Button onClick={() => void create()} disabled={!patient || busy}>
              Create draft
            </Button>
            <Button variant="outline" onClick={() => router.push("/invoices")}>
              Cancel
            </Button>
          </div>
        </CardContent>
      </Card>
    </>
  );
}

export default function NewInvoicePage() {
  return (
    <Suspense fallback={<p className="text-muted-foreground">Loading…</p>}>
      <NewInvoice />
    </Suspense>
  );
}
