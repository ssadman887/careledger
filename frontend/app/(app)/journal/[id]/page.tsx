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
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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
import { useAuth } from "@/lib/auth/auth-context";
import { formatDateTime } from "@/lib/format";
import { sumMoney } from "@/lib/money";
import { can } from "@/lib/permissions";

type Entry = Schemas["JournalEntryOut"];
type Action = "reverse" | "reject";

export default function JournalEntryPage() {
  const { id } = useParams<{ id: string }>();
  const { roles } = useAuth();
  const [entry, setEntry] = useState<Entry | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [action, setAction] = useState<Action | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const { data } = await api.GET("/api/v1/journal-entries/{entry_id}", {
      params: { path: { entry_id: Number(id) } },
    });
    if (data) setEntry(data);
    else setNotFound(true);
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  if (notFound) return <p className="text-muted-foreground">Journal entry not found.</p>;
  if (!entry)
    return (
      <p className="text-muted-foreground" aria-busy="true">
        Loading…
      </p>
    );

  const path = { params: { path: { entry_id: entry.id } } };
  const approve = async () => {
    setBusy(true);
    const { data, error } = await api.POST("/api/v1/journal-entries/{entry_id}/approve", path);
    setBusy(false);
    if (!data) return void toast.error(errorMessage(error, "Could not approve"));
    toast.success(`${data.entry_number} approved and posted`);
    setEntry(data);
  };
  const submitAction = async () => {
    setBusy(true);
    const result =
      action === "reverse"
        ? await api.POST("/api/v1/journal-entries/{entry_id}/reverse", { ...path, body: { reason } })
        : await api.POST("/api/v1/journal-entries/{entry_id}/reject", { ...path, body: { reason } });
    setBusy(false);
    if (!result.data) return void toast.error(errorMessage(result.error, "Action failed"));
    toast.success(action === "reverse" ? `Reversed by ${result.data.entry_number}` : "Entry rejected");
    setAction(null);
    setReason("");
    await load();
  };

  const canReverse =
    can(roles, "postJournal") && entry.status === "posted" && !entry.reversed_by_id && !entry.reversal_of_id;
  const canApprove = can(roles, "approveJournal") && entry.status === "pending_approval";

  return (
    <>
      <Button asChild variant="ghost" size="sm" className="mb-2 -ml-2">
        <Link href="/journal">
          <ArrowLeft /> Journal entries
        </Link>
      </Button>
      <PageHeader
        title={entry.entry_number}
        description={entry.memo}
        actions={
          <>
            {canApprove && (
              <>
                <Button onClick={() => void approve()} disabled={busy}>
                  Approve and post
                </Button>
                <Button variant="outline" onClick={() => setAction("reject")} disabled={busy}>
                  Reject
                </Button>
              </>
            )}
            {canReverse && (
              <Button variant="outline" onClick={() => setAction("reverse")}>
                Reverse entry
              </Button>
            )}
          </>
        }
      />
      <div className="grid gap-6 lg:grid-cols-[1fr_300px]">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Lines</CardTitle>
          </CardHeader>
          <CardContent className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>#</TableHead>
                  <TableHead>Account</TableHead>
                  <TableHead>Description</TableHead>
                  <TableHead className="text-right">Debit</TableHead>
                  <TableHead className="text-right">Credit</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {entry.lines.map((l) => (
                  <TableRow key={l.line_no}>
                    <TableCell>{l.line_no}</TableCell>
                    <TableCell>
                      <Link href={`/reports?tab=ledger&account=${l.account_id}`} className="hover:underline">
                        <span className="font-mono text-sm">{l.account_code}</span> {l.account_name}
                      </Link>
                    </TableCell>
                    <TableCell className="text-muted-foreground">{l.description}</TableCell>
                    <TableCell className="text-right">
                      <Money value={l.debit} hideZero />
                    </TableCell>
                    <TableCell className="text-right">
                      <Money value={l.credit} hideZero />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
              <TableFooter>
                <TableRow>
                  <TableCell colSpan={3}>Totals</TableCell>
                  <TableCell className="text-right">
                    <Money value={sumMoney(entry.lines.map((l) => l.debit))} />
                  </TableCell>
                  <TableCell className="text-right">
                    <Money value={sumMoney(entry.lines.map((l) => l.credit))} />
                  </TableCell>
                </TableRow>
              </TableFooter>
            </Table>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Details</CardTitle>
          </CardHeader>
          <CardContent>
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
              <dt className="text-muted-foreground">Status</dt>
              <dd>
                <StatusBadge status={entry.status} />
              </dd>
              <dt className="text-muted-foreground">Entry date</dt>
              <dd>{entry.entry_date}</dd>
              <dt className="text-muted-foreground">Source</dt>
              <dd>
                {entry.source_type}
                {entry.source_id ? ` #${entry.source_id}` : ""}
              </dd>
              <dt className="text-muted-foreground">Posted</dt>
              <dd>{formatDateTime(entry.posted_at)}</dd>
              <dt className="text-muted-foreground">Created</dt>
              <dd>{formatDateTime(entry.created_at)}</dd>
              {entry.reversal_of_id && (
                <>
                  <dt className="text-muted-foreground">Reverses</dt>
                  <dd>
                    <Link className="hover:underline" href={`/journal/${entry.reversal_of_id}`}>
                      Entry #{entry.reversal_of_id}
                    </Link>
                  </dd>
                </>
              )}
              {entry.reversed_by_id && (
                <>
                  <dt className="text-muted-foreground">Reversed by</dt>
                  <dd>
                    <Link className="hover:underline" href={`/journal/${entry.reversed_by_id}`}>
                      Entry #{entry.reversed_by_id}
                    </Link>
                  </dd>
                </>
              )}
              {entry.reversal_reason && (
                <>
                  <dt className="text-muted-foreground">Reason</dt>
                  <dd>{entry.reversal_reason}</dd>
                </>
              )}
              {entry.rejection_reason && (
                <>
                  <dt className="text-muted-foreground">Rejected</dt>
                  <dd>{entry.rejection_reason}</dd>
                </>
              )}
            </dl>
          </CardContent>
        </Card>
      </div>

      <Dialog open={action !== null} onOpenChange={(o) => !o && setAction(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{action === "reverse" ? "Reverse this entry" : "Reject this entry"}</DialogTitle>
            <DialogDescription>
              {action === "reverse"
                ? "A mirror entry (debits and credits swapped) will be posted. The original stays unchanged."
                : "The entry will not be posted. The accountant will see your reason."}
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-2">
            <Label htmlFor="action-reason">Reason</Label>
            <Textarea
              id="action-reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              rows={3}
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setAction(null)}>
              Cancel
            </Button>
            <Button onClick={() => void submitAction()} disabled={busy || !reason.trim()}>
              {action === "reverse" ? "Post reversal" : "Reject"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
