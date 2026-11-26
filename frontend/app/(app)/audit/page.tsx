"use client";

import { ChevronDown, ChevronRight } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { Fragment, Suspense, useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { ExportMenu } from "@/components/export-menu";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api, errorMessage, type Schemas } from "@/lib/api/client";
import { downloadExport } from "@/lib/api/exports";
import { diffFields } from "@/lib/audit";
import { formatDateTime, humanize } from "@/lib/format";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 50;
const ALL = "all";

interface Filters {
  entity_type: string;
  action: string;
  actor_label: string;
  entity_id: string;
  date_from: string;
  date_to: string;
}
const EMPTY: Filters = {
  entity_type: ALL,
  action: ALL,
  actor_label: "",
  entity_id: "",
  date_from: "",
  date_to: "",
};

/** Filters as API query parameters (dates cover whole days, in UTC). */
function toQuery(f: Filters) {
  return {
    entity_type: f.entity_type === ALL ? undefined : f.entity_type,
    action: f.action === ALL ? undefined : f.action,
    actor_label: f.actor_label.trim() || undefined,
    entity_id: f.entity_id.trim() || undefined,
    date_from: f.date_from ? `${f.date_from}T00:00:00Z` : undefined,
    date_to: f.date_to ? `${f.date_to}T23:59:59Z` : undefined,
  };
}

function Changes({ entry }: { entry: Schemas["AuditLogOut"] }) {
  const fields = diffFields(entry.before, entry.after);
  if (fields.length === 0) return <p className="text-muted-foreground text-sm">No field data recorded.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-muted-foreground text-left">
            <th className="py-1 pr-4 font-medium">Field</th>
            <th className="py-1 pr-4 font-medium">Before</th>
            <th className="py-1 font-medium">After</th>
          </tr>
        </thead>
        <tbody className="font-mono">
          {fields.map((f) => (
            <tr key={f.field} className={cn(f.changed ? "" : "text-muted-foreground")}>
              <td className="py-0.5 pr-4 align-top">{f.field}</td>
              <td className={cn("py-0.5 pr-4 align-top", f.changed && f.before && "text-destructive")}>
                <div className="max-w-sm break-all">{f.before || "—"}</div>
              </td>
              <td className={cn("py-0.5 align-top", f.changed && "text-emerald-700 dark:text-emerald-400")}>
                <div className="max-w-sm break-all">{f.after || "—"}</div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {entry.request_id && <p className="text-muted-foreground mt-2 text-xs">Request {entry.request_id}</p>}
    </div>
  );
}

/** Filters from the URL, so records can link to their own audit trail. */
function initialFilters(params: { get(name: string): string | null }): Filters {
  return {
    ...EMPTY,
    entity_type: params.get("entity_type") ?? ALL,
    action: params.get("action") ?? ALL,
    entity_id: params.get("entity_id") ?? "",
    actor_label: params.get("actor") ?? "",
  };
}

function AuditInner() {
  const params = useSearchParams();
  const [facets, setFacets] = useState<Schemas["AuditFacetsOut"]>({ entity_types: [], actions: [] });
  const [draft, setDraft] = useState<Filters>(() => initialFilters(params));
  const [filters, setFilters] = useState<Filters>(() => initialFilters(params));
  const [page, setPage] = useState(1);
  const [data, setData] = useState<Schemas["Page_AuditLogOut_"] | null>(null);
  const [expanded, setExpanded] = useState<number | null>(null);

  useEffect(() => {
    void api.GET("/api/v1/audit-log/facets").then(({ data: f }) => f && setFacets(f));
  }, []);
  const load = useCallback(async () => {
    const { data: rows, error } = await api.GET("/api/v1/audit-log", {
      params: { query: { ...toQuery(filters), page, page_size: PAGE_SIZE } },
    });
    if (!rows) return void toast.error(errorMessage(error, "Could not load the audit log"));
    setData(rows);
  }, [filters, page]);
  useEffect(() => {
    void load();
  }, [load]);

  const apply = () => {
    setPage(1);
    setFilters(draft);
  };
  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;
  const set = (key: keyof Filters) => (value: string) => setDraft((d) => ({ ...d, [key]: value }));

  return (
    <>
      <PageHeader
        title="Audit log"
        description="Every change, approval and export, recorded in the same transaction. Entries can never be edited or deleted."
        actions={
          <ExportMenu
            onExport={(fmt) => {
              const { entity_id: _ignored, ...q } = toQuery(filters);
              void _ignored;
              return downloadExport("/api/v1/exports/audit-log", fmt, q);
            }}
          />
        }
      />
      <form
        className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6"
        onSubmit={(e) => {
          e.preventDefault();
          apply();
        }}
      >
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="audit-type">Record type</Label>
          <Select value={draft.entity_type} onValueChange={set("entity_type")}>
            <SelectTrigger id="audit-type">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>All types</SelectItem>
              {facets.entity_types.map((t) => (
                <SelectItem key={t} value={t}>
                  {humanize(t)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="audit-action">Action</Label>
          <Select value={draft.action} onValueChange={set("action")}>
            <SelectTrigger id="audit-action">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>All actions</SelectItem>
              {facets.actions.map((a) => (
                <SelectItem key={a} value={a}>
                  {humanize(a)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="audit-actor">Actor</Label>
          <Input
            id="audit-actor"
            placeholder="e.g. finance"
            value={draft.actor_label}
            onChange={(e) => set("actor_label")(e.target.value)}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="audit-entity">Record id</Label>
          <Input
            id="audit-entity"
            value={draft.entity_id}
            onChange={(e) => set("entity_id")(e.target.value)}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="audit-from">From</Label>
          <Input
            id="audit-from"
            type="date"
            value={draft.date_from}
            onChange={(e) => set("date_from")(e.target.value)}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="audit-to">To</Label>
          <Input
            id="audit-to"
            type="date"
            value={draft.date_to}
            onChange={(e) => set("date_to")(e.target.value)}
          />
        </div>
        <div className="flex gap-2 sm:col-span-2 lg:col-span-3 xl:col-span-6">
          <Button type="submit">Apply filters</Button>
          <Button
            type="button"
            variant="ghost"
            onClick={() => {
              setDraft(EMPTY);
              setFilters(EMPTY);
              setPage(1);
            }}
          >
            Clear
          </Button>
          {data && (
            <span className="text-muted-foreground ml-auto self-center text-sm">
              {data.total.toLocaleString()} entries
            </span>
          )}
        </div>
      </form>

      <div className="bg-card overflow-x-auto rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-8" />
              <TableHead>When</TableHead>
              <TableHead>Actor</TableHead>
              <TableHead>Action</TableHead>
              <TableHead>Record</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data?.items.length === 0 && (
              <TableRow>
                <TableCell colSpan={5} className="text-muted-foreground h-20 text-center">
                  No entries match these filters.
                </TableCell>
              </TableRow>
            )}
            {data?.items.map((e) => (
              <Fragment key={e.id}>
                <TableRow
                  className="cursor-pointer"
                  onClick={() => setExpanded(expanded === e.id ? null : e.id)}
                >
                  <TableCell>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="size-6"
                      aria-label={`${expanded === e.id ? "Hide" : "Show"} changes for entry ${e.id}`}
                      aria-expanded={expanded === e.id}
                    >
                      {expanded === e.id ? <ChevronDown /> : <ChevronRight />}
                    </Button>
                  </TableCell>
                  <TableCell className="text-sm whitespace-nowrap">{formatDateTime(e.occurred_at)}</TableCell>
                  <TableCell className="text-sm">{e.actor_label}</TableCell>
                  <TableCell>
                    <Badge variant={e.action === "export" ? "secondary" : "outline"}>
                      {humanize(e.action)}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-sm">
                    {humanize(e.entity_type)}{" "}
                    <span className="text-muted-foreground font-mono">#{e.entity_id}</span>
                  </TableCell>
                </TableRow>
                {expanded === e.id && (
                  <TableRow className="bg-muted/30 hover:bg-muted/30">
                    <TableCell />
                    <TableCell colSpan={4}>
                      <Changes entry={e} />
                    </TableCell>
                  </TableRow>
                )}
              </Fragment>
            ))}
          </TableBody>
        </Table>
      </div>
      <div className="mt-3 flex items-center justify-end gap-2">
        <span className="text-muted-foreground text-sm">
          Page {page} of {pages}
        </span>
        <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
          Previous
        </Button>
        <Button variant="outline" size="sm" disabled={page >= pages} onClick={() => setPage((p) => p + 1)}>
          Next
        </Button>
      </div>
    </>
  );
}

export default function AuditPage() {
  return (
    <Suspense fallback={<p className="text-muted-foreground">Loading…</p>}>
      <AuditInner />
    </Suspense>
  );
}
