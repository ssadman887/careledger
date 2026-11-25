"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { Money } from "@/components/money";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api, errorMessage, type Schemas } from "@/lib/api/client";
import { useAuth } from "@/lib/auth/auth-context";
import { formatDateTime, humanize } from "@/lib/format";
import { useIdempotencyKey } from "@/lib/idempotency";
import { can } from "@/lib/permissions";

type Remittance = Schemas["RemittanceOut"];
const POSTABLE = new Set(["matched", "short_paid"]);

export default function RemittancePage() {
  const { id } = useParams<{ id: string }>();
  const { roles } = useAuth();
  const idem = useIdempotencyKey();
  const [remittance, setRemittance] = useState<Remittance | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const { data, error } = await api.GET("/api/v1/remittances/{remittance_id}", {
      params: { path: { remittance_id: Number(id) } },
    });
    if (!data) return void toast.error(errorMessage(error, "Remittance not found"));
    setRemittance(data);
  }, [id]);
  useEffect(() => {
    void load();
  }, [load]);

  if (!remittance) return <p className="text-muted-foreground">Loading…</p>;

  const postable = remittance.lines.filter((l) => POSTABLE.has(l.match_status));
  const post = async () => {
    setBusy(true);
    const { data, error } = await api.POST("/api/v1/remittances/{remittance_id}/post", {
      params: { path: { remittance_id: remittance.id }, header: { "Idempotency-Key": idem.key() } },
    });
    setBusy(false);
    if (!data) return void toast.error(errorMessage(error, "Posting failed"));
    idem.reset();
    toast.success(`Posted ${data.posted_amount} to the ledger`);
    setRemittance(data);
  };

  return (
    <>
      <Button asChild variant="ghost" size="sm" className="mb-2 -ml-2">
        <Link href="/remittances">
          <ArrowLeft /> Remittances
        </Link>
      </Button>
      <PageHeader
        title={remittance.remittance_number}
        description={`${remittance.insurer_name} · ${remittance.reference} · paid ${remittance.payment_date}`}
        actions={
          can(roles, "workClaims") && remittance.status === "imported" ? (
            <Button onClick={() => void post()} disabled={busy || postable.length === 0}>
              Post {postable.length} line(s) to ledger
            </Button>
          ) : undefined
        }
      />
      <div className="mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {(
          [
            ["Status", <StatusBadge key="s" status={remittance.status} />],
            ["Remittance total", <Money key="t" value={remittance.total_amount} />],
            ["Posted", <Money key="p" value={remittance.posted_amount} />],
            [
              "Reconciliation",
              <span key="c" className="text-sm">
                {Object.entries(remittance.counts)
                  .filter(([, n]) => n > 0)
                  .map(([k, n]) => `${n} ${humanize(k).toLowerCase()}`)
                  .join(" · ")}
              </span>,
            ],
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
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Lines</CardTitle>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>#</TableHead>
                <TableHead>Claim</TableHead>
                <TableHead>Match</TableHead>
                <TableHead>Message</TableHead>
                <TableHead>Remark</TableHead>
                <TableHead className="text-right">Expected</TableHead>
                <TableHead className="text-right">Paid</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {remittance.lines.map((l) => (
                <TableRow key={l.line_no} className={POSTABLE.has(l.match_status) ? "" : "bg-destructive/5"}>
                  <TableCell>{l.line_no}</TableCell>
                  <TableCell>
                    {l.claim_id ? (
                      <Link href={`/claims/${l.claim_id}`} className="font-mono text-sm hover:underline">
                        {l.claim_number}
                      </Link>
                    ) : (
                      <span className="font-mono text-sm">{l.claim_number}</span>
                    )}
                  </TableCell>
                  <TableCell>
                    <StatusBadge status={l.match_status} />
                    {l.payment_id && <span className="text-muted-foreground ml-1 text-xs">posted</span>}
                  </TableCell>
                  <TableCell className="text-sm">{l.message}</TableCell>
                  <TableCell className="text-muted-foreground text-sm">{l.remark}</TableCell>
                  <TableCell className="text-right">
                    {l.expected_amount ? <Money value={l.expected_amount} /> : "—"}
                  </TableCell>
                  <TableCell className="text-right">
                    <Money value={l.paid_amount} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <p className="text-muted-foreground mt-3 text-xs">
            Imported from {remittance.source_filename || "upload"}
            {remittance.posted_at && ` · posted ${formatDateTime(remittance.posted_at)}`}. Overpaid and
            unmatched lines are never posted automatically.
          </p>
        </CardContent>
      </Card>
    </>
  );
}
