"use client";

import { ArrowLeft, Paperclip, Upload } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
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
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { api, errorMessage, type Schemas } from "@/lib/api/client";
import { useAuth } from "@/lib/auth/auth-context";
import { formatDateTime, humanize } from "@/lib/format";
import { toCents } from "@/lib/money";
import { can } from "@/lib/permissions";

type Claim = Schemas["ClaimOut"];
type Action = "cancel" | "appeal" | "close" | "accept" | "adjudicate" | null;

const ACTION_COPY: Record<
  Exclude<Action, null>,
  { title: string; description: string; button: string; noteRequired: boolean }
> = {
  cancel: {
    title: "Cancel draft claim",
    description: "Nothing has been posted; the invoice can be claimed again.",
    button: "Cancel claim",
    noteRequired: false,
  },
  appeal: {
    title: "Appeal denial",
    description:
      "Explain the grounds and attach supporting documents first. The insurer re-reviews the claim.",
    button: "File appeal",
    noteRequired: true,
  },
  close: {
    title: "Close denied claim",
    description: "The insurer share moves back to the patient's balance (Dr AR-Patients / Cr AR-Insurers).",
    button: "Close claim",
    noteRequired: false,
  },
  accept: {
    title: "Accept short payment",
    description:
      "The unpaid remainder is written off as a contractual adjustment and the claim is marked paid.",
    button: "Accept and settle",
    noteRequired: false,
  },
  adjudicate: { title: "Mock insurer decision", description: "", button: "Adjudicate", noteRequired: false },
};

function Row({ label, value, strong = false }: { label: string; value: string; strong?: boolean }) {
  return (
    <>
      <dt className={strong ? "font-medium" : "text-muted-foreground"}>{label}</dt>
      <dd className={`text-right ${strong ? "font-medium" : ""}`}>
        <Money value={value} hideZero={!strong} />
      </dd>
    </>
  );
}

export default function ClaimPage() {
  const { id } = useParams<{ id: string }>();
  const claimId = Number(id);
  const { roles } = useAuth();
  const canWork = can(roles, "workClaims");
  const [claim, setClaim] = useState<Claim | null>(null);
  const [action, setAction] = useState<Action>(null);
  const [note, setNote] = useState("");
  const [outcome, setOutcome] = useState<"auto" | "approve" | "partial" | "deny">("auto");
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    const { data, error } = await api.GET("/api/v1/claims/{claim_id}", {
      params: { path: { claim_id: claimId } },
    });
    if (!data) return void toast.error(errorMessage(error, "Claim not found"));
    setClaim(data);
  }, [claimId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (!claim) return <p className="text-muted-foreground">Loading…</p>;

  const path = { params: { path: { claim_id: claim.id } } };
  const allowed = new Set(claim.allowed_transitions);

  const submit = async () => {
    setBusy(true);
    const { data, error } = await api.POST("/api/v1/claims/{claim_id}/submit", path);
    setBusy(false);
    if (!data) return void toast.error(errorMessage(error, "Could not submit"));
    toast.success(`${data.claim_number} submitted to ${data.insurer_name}`);
    setClaim(data);
  };

  const runAction = async () => {
    if (!action) return;
    setBusy(true);
    const body = { note };
    const result =
      action === "cancel"
        ? await api.POST("/api/v1/claims/{claim_id}/cancel", { ...path, body })
        : action === "appeal"
          ? await api.POST("/api/v1/claims/{claim_id}/appeal", { ...path, body })
          : action === "close"
            ? await api.POST("/api/v1/claims/{claim_id}/close", { ...path, body })
            : action === "accept"
              ? await api.POST("/api/v1/claims/{claim_id}/accept-short-pay", { ...path, body })
              : await api.POST("/api/v1/claims/{claim_id}/adjudicate", {
                  ...path,
                  body: { outcome: outcome === "auto" ? null : outcome },
                });
    setBusy(false);
    if (!result.data) return void toast.error(errorMessage(result.error, "Action failed"));
    toast.success(`${result.data.claim_number}: ${humanize(result.data.status)}`);
    setClaim(result.data);
    setAction(null);
    setNote("");
  };

  const upload = async (file: File) => {
    const { data, error } = await api.POST("/api/v1/claims/{claim_id}/attachments", {
      ...path,
      // The schema types the file as a binary string; the serializer sends real multipart data.
      body: { file: file as unknown as string },
      bodySerializer: (body) => {
        const form = new FormData();
        form.append("file", body.file as unknown as Blob, file.name);
        return form;
      },
    });
    if (!data) return void toast.error(errorMessage(error, "Upload failed"));
    toast.success(`Attached ${data.filename}`);
    void load();
  };

  const download = async (a: Schemas["ClaimAttachmentOut"]) => {
    const { data } = await api.GET("/api/v1/claims/{claim_id}/attachments/{attachment_id}", {
      params: { path: { claim_id: claim.id, attachment_id: a.id } },
      parseAs: "blob",
    });
    if (!data) return void toast.error("Download failed");
    const url = URL.createObjectURL(data);
    const link = document.createElement("a");
    link.href = url;
    link.download = a.filename;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 30_000);
  };

  const shortPaid =
    (claim.status === "approved" || claim.status === "partially_approved") &&
    (toCents(claim.paid_amount) ?? 0n) > 0n &&
    (toCents(claim.outstanding) ?? 0n) > 0n;
  const copy = action ? ACTION_COPY[action] : null;

  return (
    <>
      <Button asChild variant="ghost" size="sm" className="mb-2 -ml-2">
        <Link href="/claims">
          <ArrowLeft /> Claims
        </Link>
      </Button>
      <PageHeader
        title={claim.claim_number}
        description={`${claim.patient_name} · ${claim.insurer_name} · ${claim.plan_name} (${claim.policy_number})`}
        actions={
          <>
            {claim.status === "draft" && canWork && (
              <Button onClick={() => void submit()} disabled={busy}>
                Submit to insurer
              </Button>
            )}
            {claim.status === "draft" && can(roles, "draftClaim") && (
              <Button variant="outline" onClick={() => setAction("cancel")}>
                Cancel
              </Button>
            )}
            {(claim.status === "submitted" || claim.status === "appealed") && canWork && (
              <Button onClick={() => setAction("adjudicate")}>Run mock insurer</Button>
            )}
            {allowed.has("appealed") && canWork && (
              <Button onClick={() => setAction("appeal")} disabled={claim.appeal_count >= 2}>
                Appeal
              </Button>
            )}
            {allowed.has("closed") && canWork && (
              <Button variant="outline" onClick={() => setAction("close")}>
                Close and bill patient
              </Button>
            )}
            {shortPaid && canWork && (
              <Button variant="outline" onClick={() => setAction("accept")}>
                Accept short pay
              </Button>
            )}
          </>
        }
      />

      <div className="mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {(
          [
            ["Status", <StatusBadge key="s" status={claim.status} />],
            ["Claimed from insurer", <Money key="c" value={claim.insurer_amount} />],
            ["Approved", <Money key="a" value={claim.approved_amount} />],
            [
              "Paid / outstanding",
              <span key="p">
                <Money value={claim.paid_amount} /> / <Money value={claim.outstanding} />
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

      {claim.denial_code && (
        <Card className="border-destructive/40 mb-6">
          <CardContent className="text-sm">
            <span className="font-mono font-medium">{claim.denial_code}</span> · {claim.denial_description}
            {claim.denial_note && <span className="text-muted-foreground block">{claim.denial_note}</span>}
            <span className="text-muted-foreground block text-xs">
              Appeals used: {claim.appeal_count} of 2
            </span>
          </CardContent>
        </Card>
      )}

      <div className="grid gap-6 xl:grid-cols-[1fr_360px]">
        <div className="flex flex-col gap-6">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Coverage split</CardTitle>
            </CardHeader>
            <CardContent>
              <dl className="grid max-w-md grid-cols-[1fr_auto] gap-x-6 gap-y-1 text-sm">
                <Row label="Billed" value={claim.billed_amount} strong />
                <Row label="Copay" value={claim.copay_amount} />
                <Row label="Deductible" value={claim.deductible_amount} />
                <Row label="Coinsurance" value={claim.coinsurance_amount} />
                <Row label="Over limit / already paid" value={claim.over_limit_amount} />
                <Row label="Patient responsibility" value={claim.patient_amount} strong />
                <Row label="Insurer responsibility" value={claim.insurer_amount} strong />
                <Row label="Contractual adjustments" value={claim.adjustment_amount} />
              </dl>
              <p className="text-muted-foreground mt-3 text-xs">
                Invoice{" "}
                <Link href={`/invoices/${claim.invoice_id}`} className="hover:underline">
                  {claim.invoice_number}
                </Link>{" "}
                · service date {claim.service_date}
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Lines</CardTitle>
            </CardHeader>
            <CardContent className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>#</TableHead>
                    <TableHead>Code</TableHead>
                    <TableHead>Description</TableHead>
                    <TableHead className="text-right">Billed</TableHead>
                    <TableHead className="text-right">Insurer share</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {claim.lines.map((l) => (
                    <TableRow key={l.line_no}>
                      <TableCell>{l.line_no}</TableCell>
                      <TableCell className="font-mono text-xs">{l.service_code}</TableCell>
                      <TableCell>{l.description}</TableCell>
                      <TableCell className="text-right">
                        <Money value={l.billed_amount} />
                      </TableCell>
                      <TableCell className="text-right">
                        <Money value={l.insurer_amount} />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle className="text-base">Attachments</CardTitle>
              {canWork && (
                <>
                  <input
                    ref={fileRef}
                    type="file"
                    accept="application/pdf,image/png,image/jpeg,text/plain"
                    className="sr-only"
                    aria-label="Choose attachment"
                    onChange={(e) => {
                      const f = e.target.files?.[0];
                      if (f) void upload(f);
                      e.target.value = "";
                    }}
                  />
                  <Button size="sm" variant="outline" onClick={() => fileRef.current?.click()}>
                    <Upload /> Upload
                  </Button>
                </>
              )}
            </CardHeader>
            <CardContent>
              {claim.attachments.length === 0 ? (
                <p className="text-muted-foreground text-sm">
                  No documents. PDF, PNG, JPEG or text up to 5 MB.
                </p>
              ) : (
                <ul className="flex flex-col gap-1 text-sm">
                  {claim.attachments.map((a) => (
                    <li key={a.id}>
                      <button
                        type="button"
                        className="inline-flex items-center gap-1 hover:underline"
                        onClick={() => void download(a)}
                      >
                        <Paperclip className="size-3.5" aria-hidden /> {a.filename}
                      </button>
                      <span className="text-muted-foreground ml-2 text-xs">
                        {(a.size_bytes / 1024).toFixed(1)} KB · {formatDateTime(a.created_at)}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        </div>

        <Card className="h-fit">
          <CardHeader>
            <CardTitle className="text-base">Timeline</CardTitle>
          </CardHeader>
          <CardContent>
            <ol className="relative flex flex-col gap-4 border-l pl-4" aria-label="Claim events">
              {claim.events.map((e) => (
                <li key={e.id} className="text-sm">
                  <span className="bg-primary absolute -left-1.5 mt-1.5 size-3 rounded-full" aria-hidden />
                  <p className="font-medium">
                    {humanize(e.event_type)}
                    {e.amount && e.amount !== "0.00" && (
                      <>
                        {" · "}
                        <Money value={e.amount} />
                      </>
                    )}
                    {e.denial_code && <span className="text-destructive font-mono"> {e.denial_code}</span>}
                  </p>
                  {e.note && <p className="text-muted-foreground">{e.note}</p>}
                  <p className="text-muted-foreground text-xs">
                    {e.actor_label} · {formatDateTime(e.created_at)}
                  </p>
                </li>
              ))}
            </ol>
          </CardContent>
        </Card>
      </div>

      <Dialog open={action !== null} onOpenChange={(o) => !o && setAction(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{copy?.title}</DialogTitle>
            {copy?.description && <DialogDescription>{copy.description}</DialogDescription>}
          </DialogHeader>
          {action === "adjudicate" ? (
            <div className="flex flex-col gap-2">
              <Label htmlFor="adj-outcome">Outcome</Label>
              <Select value={outcome} onValueChange={(v) => setOutcome(v as typeof outcome)}>
                <SelectTrigger id="adj-outcome" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="auto">Let the mock insurer decide</SelectItem>
                  <SelectItem value="approve">Approve in full</SelectItem>
                  <SelectItem value="partial">Partially approve (70%)</SelectItem>
                  <SelectItem value="deny">Deny (CO-50)</SelectItem>
                </SelectContent>
              </Select>
            </div>
          ) : (
            <div className="flex flex-col gap-2">
              <Label htmlFor="action-note">{copy?.noteRequired ? "Grounds (required)" : "Note"}</Label>
              <Textarea id="action-note" rows={3} value={note} onChange={(e) => setNote(e.target.value)} />
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setAction(null)}>
              Back
            </Button>
            <Button
              onClick={() => void runAction()}
              disabled={busy || (!!copy?.noteRequired && !note.trim())}
            >
              {copy?.button}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
