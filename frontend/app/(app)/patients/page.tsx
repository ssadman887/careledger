"use client";

import type { ColumnDef, SortingState } from "@tanstack/react-table";
import { Plus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { DataTable, toSortParam } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
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
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { api, errorMessage, type Schemas } from "@/lib/api/client";
import { useAuth } from "@/lib/auth/auth-context";
import { humanize } from "@/lib/format";
import { can } from "@/lib/permissions";

type Patient = Schemas["PatientOut"];
const PAGE_SIZE = 25;

function NewPatientDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const router = useRouter();
  const [form, setForm] = useState({
    first_name: "",
    last_name: "",
    date_of_birth: "",
    sex: "unknown",
    phone: "",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const set = (k: keyof typeof form) => (v: string) => setForm((f) => ({ ...f, [k]: v }));

  const submit = async () => {
    if (!form.first_name.trim() || !form.last_name.trim() || !form.date_of_birth) {
      return setError("First name, last name and date of birth are required");
    }
    setBusy(true);
    const { data, error: apiError } = await api.POST("/api/v1/patients", { body: form });
    setBusy(false);
    if (!data) return setError(errorMessage(apiError, "Could not create patient"));
    toast.success(`Registered ${data.full_name} (${data.mrn})`);
    router.push(`/patients/${data.id}`);
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Register patient</DialogTitle>
          <DialogDescription>
            Synthetic demo data only. Never enter a real person&apos;s details.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 sm:grid-cols-2">
          {(
            [
              ["first_name", "First name", "text"],
              ["last_name", "Last name", "text"],
              ["date_of_birth", "Date of birth", "date"],
              ["phone", "Phone (fictional)", "tel"],
            ] as const
          ).map(([key, label, type]) => (
            <div key={key} className="flex flex-col gap-2">
              <Label htmlFor={`np-${key}`}>{label}</Label>
              <Input
                id={`np-${key}`}
                type={type}
                value={form[key]}
                onChange={(e) => set(key)(e.target.value)}
              />
            </div>
          ))}
          <div className="flex flex-col gap-2">
            <Label htmlFor="np-sex">Sex</Label>
            <Select value={form.sex} onValueChange={set("sex")}>
              <SelectTrigger id="np-sex" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {["female", "male", "other", "unknown"].map((s) => (
                  <SelectItem key={s} value={s}>
                    {humanize(s)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
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
          <Button onClick={() => void submit()} disabled={busy}>
            Register
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default function PatientsPage() {
  const { roles } = useAuth();
  const [rows, setRows] = useState<Patient[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [sorting, setSorting] = useState<SortingState>([{ id: "last_name", desc: false }]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    const { data, error } = await api.GET("/api/v1/patients", {
      params: {
        query: { page, page_size: PAGE_SIZE, sort: toSortParam(sorting), search: search || undefined },
      },
    });
    setLoading(false);
    if (!data) return void toast.error(errorMessage(error, "Could not load patients"));
    setRows(data.items);
    setTotal(data.total);
  }, [page, sorting, search]);

  useEffect(() => {
    void load();
  }, [load]);

  const columns = useMemo<ColumnDef<Patient, unknown>[]>(
    () => [
      {
        accessorKey: "mrn",
        header: "MRN",
        cell: ({ row }) => (
          <Link href={`/patients/${row.original.id}`} className="font-mono text-sm hover:underline">
            {row.original.mrn}
          </Link>
        ),
      },
      {
        accessorKey: "last_name",
        header: "Name",
        cell: ({ row }) => (
          <Link href={`/patients/${row.original.id}`} className="hover:underline">
            {row.original.last_name}, {row.original.first_name}
          </Link>
        ),
      },
      { accessorKey: "date_of_birth", header: "Date of birth" },
      {
        accessorKey: "sex",
        header: "Sex",
        enableSorting: false,
        cell: ({ row }) => humanize(row.original.sex),
      },
      { accessorKey: "phone", header: "Phone", enableSorting: false },
    ],
    [],
  );

  return (
    <>
      <PageHeader
        title="Patients"
        description="Minimal synthetic patient register for billing. CareLedger is not a clinical system."
        actions={
          can(roles, "bill") ? (
            <Button onClick={() => setCreating(true)}>
              <Plus /> Register patient
            </Button>
          ) : undefined
        }
      />
      <div className="mb-4 max-w-sm">
        <Label htmlFor="patient-search" className="sr-only">
          Search patients
        </Label>
        <Input
          id="patient-search"
          placeholder="Search MRN or name"
          value={search}
          onChange={(e) => {
            setPage(1);
            setSearch(e.target.value);
          }}
        />
      </div>
      <DataTable
        columns={columns}
        data={rows}
        total={total}
        page={page}
        pageSize={PAGE_SIZE}
        sorting={sorting}
        onSortingChange={(s) => {
          setPage(1);
          setSorting(s);
        }}
        onPageChange={setPage}
        loading={loading}
      />
      <NewPatientDialog open={creating} onClose={() => setCreating(false)} />
    </>
  );
}
