"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { Money } from "@/components/money";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
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
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { api, errorMessage, type Schemas } from "@/lib/api/client";
import { entityHref } from "@/lib/approvals";
import { useAuth } from "@/lib/auth/auth-context";
import { formatDateTime, humanize } from "@/lib/format";
import { MONEY_INPUT_PATTERN } from "@/lib/money";
import { can } from "@/lib/permissions";

type Approval = Schemas["ApprovalOut"];
type Scope = "to_decide" | "mine" | "all";
type Tab = Scope | "policies";

function ApprovalDialog({
  approval,
  onClose,
  onChanged,
}: {
  approval: Approval | null;
  onClose: () => void;
  onChanged: (a: Approval) => void;
}) {
  const [note, setNote] = useState("");
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    setNote("");
    setComment("");
  }, [approval?.id]);
  if (!approval) return null;
  const path = { params: { path: { approval_id: approval.id } } };

  const decide = async (approve: boolean) => {
    setBusy(true);
    const { data, error } = await api.POST("/api/v1/approvals/{approval_id}/decision", {
      ...path,
      body: { approve, note },
    });
    setBusy(false);
    if (!data) return void toast.error(errorMessage(error, "Decision failed"));
    toast.success(`${data.reference} ${approve ? "approved" : "rejected"}`);
    onChanged(data);
    onClose();
  };
  const addComment = async () => {
    const { data, error } = await api.POST("/api/v1/approvals/{approval_id}/comments", {
      ...path,
      body: { body: comment },
    });
    if (!data) return void toast.error(errorMessage(error, "Could not comment"));
    setComment("");
    onChanged(data);
  };

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {humanize(approval.kind)} · {approval.reference}
          </DialogTitle>
          <DialogDescription>{approval.summary}</DialogDescription>
        </DialogHeader>
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
          <dt className="text-muted-foreground">Amount</dt>
          <dd>
            <Money value={approval.amount} />{" "}
            <span className="text-muted-foreground">
              (threshold <Money value={approval.threshold} />)
            </span>
          </dd>
          <dt className="text-muted-foreground">Requested by</dt>
          <dd>
            {approval.requested_by_label} · {formatDateTime(approval.created_at)}
          </dd>
          <dt className="text-muted-foreground">Approver</dt>
          <dd>{humanize(approval.approver_role)}</dd>
          <dt className="text-muted-foreground">Status</dt>
          <dd>
            <StatusBadge status={approval.status} />
            {approval.decided_by_label && (
              <span className="text-muted-foreground ml-2 text-xs">
                by {approval.decided_by_label}
                {approval.decision_note ? `: ${approval.decision_note}` : ""}
              </span>
            )}
          </dd>
        </dl>
        <Link href={entityHref(approval)} className="text-sm underline-offset-2 hover:underline">
          Open the {humanize(approval.entity_type).toLowerCase()} →
        </Link>
        <div className="flex flex-col gap-2 border-t pt-3">
          <p className="text-sm font-medium">Discussion</p>
          {approval.comments.length === 0 && (
            <p className="text-muted-foreground text-sm">No comments yet.</p>
          )}
          <ul className="flex flex-col gap-2">
            {approval.comments.map((c) => (
              <li key={c.id} className="bg-muted/50 rounded-md p-2 text-sm">
                {c.body}
                <span className="text-muted-foreground block text-xs">
                  {c.author_label} · {formatDateTime(c.created_at)}
                </span>
              </li>
            ))}
          </ul>
          <div className="flex gap-2">
            <Label htmlFor="approval-comment" className="sr-only">
              Add a comment
            </Label>
            <Input
              id="approval-comment"
              placeholder="Add a comment"
              value={comment}
              onChange={(e) => setComment(e.target.value)}
            />
            <Button variant="outline" onClick={() => void addComment()} disabled={!comment.trim()}>
              Comment
            </Button>
          </div>
        </div>
        {approval.can_decide && (
          <>
            <div className="flex flex-col gap-2">
              <Label htmlFor="decision-note">Decision note (required to reject)</Label>
              <Textarea id="decision-note" rows={2} value={note} onChange={(e) => setNote(e.target.value)} />
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => void decide(false)} disabled={busy || !note.trim()}>
                Reject
              </Button>
              <Button onClick={() => void decide(true)} disabled={busy}>
                Approve
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}

function Policies({ editable }: { editable: boolean }) {
  const [policies, setPolicies] = useState<Schemas["ApprovalPolicyOut"][]>([]);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const load = useCallback(async () => {
    const { data } = await api.GET("/api/v1/approvals/policies");
    setPolicies(data ?? []);
    setDrafts(Object.fromEntries((data ?? []).map((p) => [p.kind, p.threshold])));
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  const save = async (
    p: Schemas["ApprovalPolicyOut"],
    patch: { threshold?: string; is_active?: boolean },
  ) => {
    if (patch.threshold !== undefined && !MONEY_INPUT_PATTERN.test(patch.threshold))
      return void toast.error("Threshold must look like 500.00");
    const { data, error } = await api.PATCH("/api/v1/approvals/policies/{kind}", {
      params: { path: { kind: p.kind } },
      body: patch,
    });
    if (!data) return void toast.error(errorMessage(error, "Could not update policy"));
    toast.success(`${humanize(p.kind)} policy updated`);
    void load();
  };

  return (
    <div className="bg-card overflow-x-auto rounded-lg border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Kind</TableHead>
            <TableHead>Rule</TableHead>
            <TableHead>Approver</TableHead>
            <TableHead>Needs approval above</TableHead>
            <TableHead>Active</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {policies.map((p) => (
            <TableRow key={p.kind}>
              <TableCell className="font-medium">{humanize(p.kind)}</TableCell>
              <TableCell className="text-muted-foreground text-sm">{p.description}</TableCell>
              <TableCell>{humanize(p.approver_role)}</TableCell>
              <TableCell>
                {editable ? (
                  <span className="flex items-center gap-2">
                    <Label htmlFor={`thr-${p.kind}`} className="sr-only">
                      Threshold for {humanize(p.kind)}
                    </Label>
                    <Input
                      id={`thr-${p.kind}`}
                      className="w-32"
                      inputMode="decimal"
                      value={drafts[p.kind] ?? ""}
                      onChange={(e) => setDrafts((d) => ({ ...d, [p.kind]: e.target.value }))}
                    />
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => void save(p, { threshold: drafts[p.kind] ?? p.threshold })}
                    >
                      Save
                    </Button>
                  </span>
                ) : (
                  <Money value={p.threshold} />
                )}
              </TableCell>
              <TableCell>
                {editable ? (
                  <input
                    type="checkbox"
                    className="size-4"
                    aria-label={`${humanize(p.kind)} approvals active`}
                    checked={p.is_active}
                    onChange={(e) => void save(p, { is_active: e.target.checked })}
                  />
                ) : p.is_active ? (
                  "Yes"
                ) : (
                  "No"
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function ApprovalsInner() {
  const router = useRouter();
  const params = useSearchParams();
  const { roles } = useAuth();
  const oversight = can(roles, "approvalOversight");
  const canSeePolicies = roles.some((r) => ["admin", "finance_manager", "accountant", "auditor"].includes(r));
  const defaultTab: Tab = roles.includes("finance_manager") ? "to_decide" : "mine";
  const tab = (
    ["to_decide", "mine", "all", "policies"].includes(params.get("tab") ?? "")
      ? params.get("tab")
      : defaultTab
  ) as Tab;
  const [rows, setRows] = useState<Approval[]>([]);
  const [status, setStatus] = useState<"pending" | "any">("pending");
  const [selected, setSelected] = useState<Approval | null>(null);

  const load = useCallback(async () => {
    if (tab === "policies") return;
    const { data, error } = await api.GET("/api/v1/approvals", {
      params: { query: { scope: tab, status: status === "pending" ? "pending" : undefined, page_size: 100 } },
    });
    if (!data) return void toast.error(errorMessage(error, "Could not load approvals"));
    setRows(data.items);
  }, [tab, status]);
  useEffect(() => {
    void load();
  }, [load]);

  return (
    <>
      <PageHeader
        title="Approvals"
        description="One inbox for every approval: manual journals, refunds, write-offs and vendor bills. Requesters can never approve their own requests."
      />
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <Tabs value={tab} onValueChange={(t) => router.replace(`/approvals?tab=${t}`)}>
          <TabsList>
            <TabsTrigger value="to_decide">To decide</TabsTrigger>
            <TabsTrigger value="mine">My requests</TabsTrigger>
            {oversight && <TabsTrigger value="all">All</TabsTrigger>}
            {canSeePolicies && <TabsTrigger value="policies">Policies</TabsTrigger>}
          </TabsList>
        </Tabs>
        {tab !== "policies" && (
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              className="size-4"
              checked={status === "pending"}
              onChange={(e) => setStatus(e.target.checked ? "pending" : "any")}
            />
            Pending only
          </label>
        )}
      </div>
      {tab === "policies" ? (
        <Policies editable={can(roles, "editApprovalPolicies")} />
      ) : (
        <div className="bg-card overflow-x-auto rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Request</TableHead>
                <TableHead>Summary</TableHead>
                <TableHead>Requested</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">Amount</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.length === 0 && (
                <TableRow>
                  <TableCell colSpan={6} className="text-muted-foreground h-20 text-center">
                    Nothing here.
                  </TableCell>
                </TableRow>
              )}
              {rows.map((a) => (
                <TableRow key={a.id}>
                  <TableCell>
                    <span className="block text-sm font-medium">{humanize(a.kind)}</span>
                    <span className="text-muted-foreground font-mono text-xs">{a.reference}</span>
                  </TableCell>
                  <TableCell className="max-w-md">
                    <span className="line-clamp-2 text-sm">{a.summary}</span>
                  </TableCell>
                  <TableCell className="text-sm">
                    {a.requested_by_label}
                    <span className="text-muted-foreground block text-xs">
                      {formatDateTime(a.created_at)}
                    </span>
                  </TableCell>
                  <TableCell>
                    <StatusBadge status={a.status} />
                  </TableCell>
                  <TableCell className="text-right">
                    <Money value={a.amount} />
                  </TableCell>
                  <TableCell className="text-right">
                    <Button
                      size="sm"
                      variant={a.can_decide ? "default" : "outline"}
                      onClick={() => setSelected(a)}
                    >
                      {a.can_decide ? "Review" : "View"}
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
      <ApprovalDialog
        approval={selected}
        onClose={() => setSelected(null)}
        onChanged={(a) => {
          setSelected((s) => (s && s.id === a.id ? a : s));
          void load();
        }}
      />
    </>
  );
}

export default function ApprovalsPage() {
  return (
    <Suspense fallback={<p className="text-muted-foreground">Loading…</p>}>
      <ApprovalsInner />
    </Suspense>
  );
}
