"use client";

import { BellRing } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { toast } from "sonner";

import { Money } from "@/components/money";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api, errorMessage, type Schemas } from "@/lib/api/client";
import { useAuth } from "@/lib/auth/auth-context";
import { formatDateTime, formatMoney } from "@/lib/format";
import { can } from "@/lib/permissions";

type Tab = "patients" | "insurers" | "dunning" | "write-offs";
const TABS: { id: Tab; label: string }[] = [
  { id: "patients", label: "Aging by patient" },
  { id: "insurers", label: "Aging by insurer" },
  { id: "dunning", label: "Reminders" },
  { id: "write-offs", label: "Write-offs" },
];
const today = () => new Date().toISOString().slice(0, 10);

function Aging({ by }: { by: "patient" | "insurer" }) {
  const [asOf, setAsOf] = useState(today());
  const [report, setReport] = useState<Schemas["AgingReportOut"] | null>(null);
  useEffect(() => {
    void api.GET("/api/v1/ar/aging", { params: { query: { by, as_of: asOf } } }).then(({ data, error }) => {
      setReport(data ?? null);
      if (!data) toast.error(errorMessage(error, "Could not load aging"));
    });
  }, [by, asOf]);

  // Chart values are display-only conversions of exact decimal strings.
  const chart = (report?.buckets ?? []).map((b) => ({ bucket: b, amount: Number(report?.totals[b] ?? "0") }));

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-end gap-3">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="aging-as-of">As of</Label>
          <Input id="aging-as-of" type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} />
        </div>
        {report && (
          <p className="text-muted-foreground pb-2 text-sm">
            Total outstanding <Money value={report.total} className="text-foreground font-semibold" />
          </p>
        )}
      </div>
      {report && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              Outstanding on {asOf} by age (days since {by === "patient" ? "invoice" : "claim submission"})
            </CardTitle>
            <p className="text-muted-foreground text-xs">
              Computed from the ledger as of that date, so totals equal the{" "}
              {by === "patient" ? "AR-Patients" : "AR-Insurers"} balance. Manual journal entries that cannot
              be traced to a document appear as unallocated.
            </p>
          </CardHeader>
          <CardContent className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chart} margin={{ left: 8, right: 8 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="bucket" tickLine={false} axisLine={false} />
                <YAxis
                  tickFormatter={(v: number) => formatMoney(String(v)).replace(".00", "")}
                  width={80}
                  tickLine={false}
                  axisLine={false}
                />
                <Tooltip formatter={(v) => formatMoney(String(v))} />
                <Bar dataKey="amount" name="Outstanding" fill="var(--color-primary)" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      )}
      <div className="bg-card overflow-x-auto rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{by === "patient" ? "Patient" : "Insurer"}</TableHead>
              {report?.buckets.map((b) => (
                <TableHead key={b} className="text-right">
                  {b} days
                </TableHead>
              ))}
              <TableHead className="text-right">Total</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {report?.rows.length === 0 && (
              <TableRow>
                <TableCell colSpan={6} className="text-muted-foreground h-20 text-center">
                  Nothing outstanding.
                </TableCell>
              </TableRow>
            )}
            {report?.rows.map((r) => (
              <TableRow key={r.party_id}>
                <TableCell>
                  {by === "patient" && r.party_id !== 0 ? (
                    <Link href={`/patients/${r.party_id}`} className="hover:underline">
                      {r.name}
                    </Link>
                  ) : (
                    r.name
                  )}
                  <span className="text-muted-foreground block font-mono text-xs">{r.code}</span>
                </TableCell>
                {report.buckets.map((b) => (
                  <TableCell key={b} className="text-right">
                    <Money value={r.buckets[b] ?? "0"} hideZero />
                  </TableCell>
                ))}
                <TableCell className="text-right font-medium">
                  <Money value={r.total} />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
          {report && (
            <TableFooter>
              <TableRow>
                <TableCell>Totals</TableCell>
                {report.buckets.map((b) => (
                  <TableCell key={b} className="text-right">
                    <Money value={report.totals[b] ?? "0"} />
                  </TableCell>
                ))}
                <TableCell className="text-right">
                  <Money value={report.total} />
                </TableCell>
              </TableRow>
            </TableFooter>
          )}
        </Table>
      </div>
    </div>
  );
}

function Dunning() {
  const { roles } = useAuth();
  const [rows, setRows] = useState<Schemas["DunningNoticeOut"][]>([]);
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    const { data } = await api.GET("/api/v1/ar/dunning", { params: { query: { page_size: 100 } } });
    setRows(data?.items ?? []);
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
  const run = async () => {
    setBusy(true);
    const { data, error } = await api.POST("/api/v1/ar/dunning/run", { body: {} });
    setBusy(false);
    if (!data) return void toast.error(errorMessage(error, "Dunning run failed"));
    toast.success(data.created ? `Sent ${data.created} reminder(s)` : "No new reminders due");
    void load();
  };
  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-muted-foreground text-sm">
          Reminders are simulated (recorded, not emailed). Level 1 at 1-30 days overdue, level 2 at 31-60,
          final notice after 60.
        </p>
        {can(roles, "collections") && (
          <Button onClick={() => void run()} disabled={busy}>
            <BellRing /> Run reminders
          </Button>
        )}
      </div>
      <div className="bg-card overflow-x-auto rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Sent</TableHead>
              <TableHead>Patient</TableHead>
              <TableHead>Invoice</TableHead>
              <TableHead>Level</TableHead>
              <TableHead>Message</TableHead>
              <TableHead className="text-right">Due</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((n) => (
              <TableRow key={n.id}>
                <TableCell className="text-sm">{formatDateTime(n.sent_at)}</TableCell>
                <TableCell>{n.patient_name}</TableCell>
                <TableCell>
                  <Link href={`/invoices/${n.invoice_id}`} className="font-mono text-sm hover:underline">
                    {n.invoice_number}
                  </Link>
                </TableCell>
                <TableCell>
                  {n.level === 3 ? "Final" : `Level ${n.level}`} · {n.days_overdue}d
                </TableCell>
                <TableCell className="max-w-md">
                  <span className="line-clamp-2 text-sm">{n.message}</span>
                </TableCell>
                <TableCell className="text-right">
                  <Money value={n.amount_due} />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

function WriteOffs() {
  const [rows, setRows] = useState<Schemas["WriteOffOut"][]>([]);
  useEffect(() => {
    void api
      .GET("/api/v1/ar/write-offs", { params: { query: { page_size: 100 } } })
      .then(({ data }) => setRows(data?.items ?? []));
  }, []);
  return (
    <div className="bg-card overflow-x-auto rounded-lg border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Write-off</TableHead>
            <TableHead>Invoice</TableHead>
            <TableHead>Patient</TableHead>
            <TableHead>Reason</TableHead>
            <TableHead>Status</TableHead>
            <TableHead className="text-right">Amount</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.length === 0 && (
            <TableRow>
              <TableCell colSpan={6} className="text-muted-foreground h-20 text-center">
                No write-offs.
              </TableCell>
            </TableRow>
          )}
          {rows.map((w) => (
            <TableRow key={w.id}>
              <TableCell className="font-mono text-sm">{w.write_off_number}</TableCell>
              <TableCell>
                <Link href={`/invoices/${w.invoice_id}`} className="font-mono text-sm hover:underline">
                  {w.invoice_number}
                </Link>
              </TableCell>
              <TableCell>{w.patient_name}</TableCell>
              <TableCell className="max-w-sm">
                <span className="line-clamp-2 text-sm">{w.reason}</span>
              </TableCell>
              <TableCell>
                <StatusBadge status={w.status} />
              </TableCell>
              <TableCell className="text-right">
                <Money value={w.amount} />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function ARInner() {
  const router = useRouter();
  const params = useSearchParams();
  const tab = (TABS.find((t) => t.id === params.get("tab"))?.id ?? "patients") as Tab;
  return (
    <>
      <PageHeader
        title="Accounts receivable"
        description="Who owes what and for how long: patients and insurers, reminders and bad-debt write-offs."
      />
      <Tabs value={tab} onValueChange={(t) => router.replace(`/ar?tab=${t}`)} className="mb-4">
        <TabsList className="flex-wrap">
          {TABS.map((t) => (
            <TabsTrigger key={t.id} value={t.id}>
              {t.label}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>
      {tab === "patients" && <Aging by="patient" />}
      {tab === "insurers" && <Aging by="insurer" />}
      {tab === "dunning" && <Dunning />}
      {tab === "write-offs" && <WriteOffs />}
    </>
  );
}

export default function ARPage() {
  return (
    <Suspense fallback={<p className="text-muted-foreground">Loading…</p>}>
      <ARInner />
    </Suspense>
  );
}
