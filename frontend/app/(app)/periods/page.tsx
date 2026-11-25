"use client";

import { Lock } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { Money } from "@/components/money";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api, errorMessage, type Schemas } from "@/lib/api/client";
import { useAuth } from "@/lib/auth/auth-context";
import { formatDateTime } from "@/lib/format";
import { can } from "@/lib/permissions";

type Period = Schemas["FiscalPeriodOut"];
type Check = Schemas["CloseCheckOut"];

export default function PeriodsPage() {
  const { roles } = useAuth();
  const canManage = can(roles, "managePeriods");
  const [periods, setPeriods] = useState<Period[]>([]);
  const [selected, setSelected] = useState<Period | null>(null);
  const [check, setCheck] = useState<Check | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const { data } = await api.GET("/api/v1/fiscal-periods");
    setPeriods(data ?? []);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const openClose = async (p: Period) => {
    setSelected(p);
    setCheck(null);
    const { data, error } = await api.GET("/api/v1/fiscal-periods/{period_id}/close-check", {
      params: { path: { period_id: p.id } },
    });
    if (!data) toast.error(errorMessage(error, "Could not run the pre-close check"));
    setCheck(data ?? null);
  };

  const close = async () => {
    if (!selected) return;
    setBusy(true);
    const { data, error } = await api.POST("/api/v1/fiscal-periods/{period_id}/close", {
      params: { path: { period_id: selected.id } },
    });
    setBusy(false);
    if (!data) return void toast.error(errorMessage(error, "Could not close period"));
    toast.success(`${data.name} closed. Postings into it are now rejected.`);
    setSelected(null);
    void load();
  };

  return (
    <>
      <PageHeader
        title="Fiscal periods"
        description="Monthly periods. Closing runs a pre-close check (balanced trial balance, no pending entries, earlier periods closed). Closed periods are locked permanently."
      />
      <div className="bg-card overflow-x-auto rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Period</TableHead>
              <TableHead>Start</TableHead>
              <TableHead>End</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Closed at</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {periods.map((p) => (
              <TableRow key={p.id}>
                <TableCell className="font-medium">{p.name}</TableCell>
                <TableCell>{p.start_date}</TableCell>
                <TableCell>{p.end_date}</TableCell>
                <TableCell>
                  <StatusBadge status={p.status} />
                </TableCell>
                <TableCell>{formatDateTime(p.closed_at)}</TableCell>
                <TableCell className="text-right">
                  {canManage && p.status === "open" && (
                    <Button size="sm" variant="outline" onClick={() => void openClose(p)}>
                      <Lock /> Close…
                    </Button>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <Dialog open={selected !== null} onOpenChange={(o) => !o && setSelected(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Close {selected?.name}</DialogTitle>
            <DialogDescription>
              This cannot be undone. No further postings will be accepted for this period.
            </DialogDescription>
          </DialogHeader>
          {!check ? (
            <p className="text-muted-foreground text-sm" aria-busy="true">
              Running pre-close check…
            </p>
          ) : (
            <div className="flex flex-col gap-3 text-sm">
              <dl className="grid grid-cols-2 gap-2">
                <dt className="text-muted-foreground">Period debits</dt>
                <dd className="text-right">
                  <Money value={check.total_debits} />
                </dd>
                <dt className="text-muted-foreground">Period credits</dt>
                <dd className="text-right">
                  <Money value={check.total_credits} />
                </dd>
                <dt className="text-muted-foreground">Pending entries</dt>
                <dd className="text-right">{check.pending_entries}</dd>
              </dl>
              {check.can_close ? (
                <Alert>
                  <AlertTitle>Ready to close</AlertTitle>
                  <AlertDescription>The trial balance balances and nothing is pending.</AlertDescription>
                </Alert>
              ) : (
                <Alert variant="destructive">
                  <AlertTitle>Cannot close yet</AlertTitle>
                  <AlertDescription>
                    <ul className="list-disc pl-4">
                      {check.problems.map((p) => (
                        <li key={p}>{p}</li>
                      ))}
                    </ul>
                  </AlertDescription>
                </Alert>
              )}
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setSelected(null)}>
              Cancel
            </Button>
            <Button onClick={() => void close()} disabled={busy || !check?.can_close}>
              Close period
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
