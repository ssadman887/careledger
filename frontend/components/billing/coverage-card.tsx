"use client";

import { Plus } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { Money } from "@/components/money";
import { Badge } from "@/components/ui/badge";
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
import { api, errorMessage, type Schemas } from "@/lib/api/client";
import { useAuth } from "@/lib/auth/auth-context";
import { MONEY_INPUT_PATTERN } from "@/lib/money";
import { can } from "@/lib/permissions";

type Policy = Schemas["PolicyOut"];

function AddPolicyDialog({
  open,
  patientId,
  onClose,
  onSaved,
}: {
  open: boolean;
  patientId: number;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [insurers, setInsurers] = useState<Schemas["InsurerOut"][]>([]);
  const year = new Date().getFullYear();
  const blank = {
    insurer_id: "",
    policy_number: "",
    plan_name: "Silver PPO",
    coverage_percent: "80",
    copay: "40.00",
    deductible: "500.00",
    annual_limit: "100000.00",
    effective_from: `${year}-01-01`,
    effective_to: `${year}-12-31`,
  };
  const [form, setForm] = useState(blank);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setForm(blank);
    setError(null);
    void api
      .GET("/api/v1/insurers", { params: { query: { active_only: true } } })
      .then(({ data }) => setInsurers(data ?? []));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const set = (k: keyof typeof form) => (v: string) => setForm((f) => ({ ...f, [k]: v }));
  const save = async () => {
    if (!form.insurer_id || !form.policy_number.trim())
      return setError("Insurer and policy number are required");
    if (![form.copay, form.deductible, form.annual_limit].every((v) => MONEY_INPUT_PATTERN.test(v)))
      return setError("Amounts must look like 1250.00");
    const { data, error: apiError } = await api.POST("/api/v1/policies", {
      body: {
        patient_id: patientId,
        insurer_id: Number(form.insurer_id),
        policy_number: form.policy_number.trim(),
        plan_name: form.plan_name,
        coverage_percent: form.coverage_percent,
        copay: form.copay,
        deductible: form.deductible,
        annual_limit: form.annual_limit,
        effective_from: form.effective_from,
        effective_to: form.effective_to || null,
      },
    });
    if (!data) return setError(errorMessage(apiError, "Could not add policy"));
    toast.success(`Policy ${data.policy_number} added`);
    onSaved();
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Add insurance policy</DialogTitle>
          <DialogDescription>Fictional insurers and synthetic policy numbers only.</DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="flex flex-col gap-2">
            <Label htmlFor="pol-insurer">Insurer</Label>
            <Select value={form.insurer_id} onValueChange={set("insurer_id")}>
              <SelectTrigger id="pol-insurer" className="w-full">
                <SelectValue placeholder="Choose" />
              </SelectTrigger>
              <SelectContent>
                {insurers.map((i) => (
                  <SelectItem key={i.id} value={String(i.id)}>
                    {i.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          {(
            [
              ["policy_number", "Policy number", "text"],
              ["plan_name", "Plan", "text"],
              ["coverage_percent", "Coverage %", "text"],
              ["copay", "Copay per claim", "text"],
              ["deductible", "Annual deductible", "text"],
              ["annual_limit", "Annual limit", "text"],
              ["effective_from", "Effective from", "date"],
              ["effective_to", "Effective to", "date"],
            ] as const
          ).map(([k, label, type]) => (
            <div key={k} className="flex flex-col gap-2">
              <Label htmlFor={`pol-${k}`}>{label}</Label>
              <Input
                id={`pol-${k}`}
                type={type}
                inputMode={
                  type === "text" && k !== "policy_number" && k !== "plan_name" ? "decimal" : undefined
                }
                value={form[k]}
                onChange={(e) => set(k)(e.target.value)}
              />
            </div>
          ))}
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
          <Button onClick={() => void save()}>Add policy</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** Patient insurance coverage (policies), shown on the patient page. */
export function CoverageCard({ patientId }: { patientId: number }) {
  const { roles } = useAuth();
  const [policies, setPolicies] = useState<Policy[]>([]);
  const [open, setOpen] = useState(false);

  const load = useCallback(async () => {
    const { data } = await api.GET("/api/v1/policies", {
      params: { query: { patient_id: patientId, page_size: 20 } },
    });
    setPolicies(data?.items ?? []);
  }, [patientId]);
  useEffect(() => {
    void load();
  }, [load]);

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle className="text-base">Insurance coverage</CardTitle>
        {can(roles, "managePolicies") && (
          <Button size="sm" variant="outline" onClick={() => setOpen(true)}>
            <Plus /> Add policy
          </Button>
        )}
      </CardHeader>
      <CardContent>
        {policies.length === 0 ? (
          <p className="text-muted-foreground text-sm">Self-pay: no insurance on file.</p>
        ) : (
          <ul className="flex flex-col gap-3">
            {policies.map((p) => (
              <li key={p.id} className="rounded-md border p-3 text-sm">
                <div className="flex items-center justify-between">
                  <span className="font-medium">{p.insurer_name}</span>
                  {p.is_active ? (
                    <Badge variant="outline">Active</Badge>
                  ) : (
                    <Badge variant="secondary">Inactive</Badge>
                  )}
                </div>
                <p className="text-muted-foreground font-mono text-xs">{p.policy_number}</p>
                <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-4">
                  <div>
                    <dt className="text-muted-foreground">Plan</dt>
                    <dd>
                      {p.plan_name} · {Number(p.coverage_percent)}%
                    </dd>
                  </div>
                  <div>
                    <dt className="text-muted-foreground">Copay</dt>
                    <dd>
                      <Money value={p.copay} />
                    </dd>
                  </div>
                  <div>
                    <dt className="text-muted-foreground">Deductible</dt>
                    <dd>
                      <Money value={p.deductible} />
                    </dd>
                  </div>
                  <div>
                    <dt className="text-muted-foreground">Annual limit</dt>
                    <dd>
                      <Money value={p.annual_limit} />
                    </dd>
                  </div>
                </dl>
                <p className="text-muted-foreground mt-1 text-xs">
                  {p.effective_from} → {p.effective_to ?? "open"}
                </p>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
      <AddPolicyDialog
        open={open}
        patientId={patientId}
        onClose={() => setOpen(false)}
        onSaved={() => {
          setOpen(false);
          void load();
        }}
      />
    </Card>
  );
}
