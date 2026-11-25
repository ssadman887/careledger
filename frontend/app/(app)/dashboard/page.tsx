"use client";

import { RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { DashboardSection } from "@/components/dashboard/section";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api, errorMessage, type Schemas } from "@/lib/api/client";
import { useAuth } from "@/lib/auth/auth-context";
import { ROLE_LABELS } from "@/lib/roles";

const today = () => new Date().toISOString().slice(0, 10);

export default function DashboardPage() {
  const { user, roles } = useAuth();
  const [asOf, setAsOf] = useState(today());
  const [board, setBoard] = useState<Schemas["DashboardOut"] | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    const { data, error } = await api.GET("/api/v1/dashboard", {
      params: { query: { as_of: asOf || undefined } },
    });
    setLoading(false);
    if (!data) return void toast.error(errorMessage(error, "Could not load the dashboard"));
    setBoard(data);
  }, [asOf]);
  useEffect(() => {
    void load();
  }, [load]);

  return (
    <>
      <PageHeader
        title={`Welcome, ${user?.full_name.split(" ")[0] ?? ""}`}
        description={`Signed in as ${roles.map((r) => ROLE_LABELS[r]).join(", ")}. Figures come straight from the ledger and operational records.`}
        actions={
          <div className="flex items-end gap-2">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="dashboard-as-of">As of</Label>
              <Input
                id="dashboard-as-of"
                type="date"
                value={asOf}
                onChange={(e) => setAsOf(e.target.value)}
              />
            </div>
            <Button variant="outline" size="icon" aria-label="Refresh dashboard" onClick={() => void load()}>
              <RefreshCw className={loading ? "animate-spin" : ""} />
            </Button>
          </div>
        }
      />
      {board?.sections.length === 0 && (
        <p className="text-muted-foreground">No dashboard sections for your role.</p>
      )}
      {board?.sections.map((s) => (
        <DashboardSection key={s.id} section={s} />
      ))}
    </>
  );
}
