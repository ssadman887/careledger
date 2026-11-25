"use client";

import type { ColumnDef, SortingState } from "@tanstack/react-table";
import { Plus } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { DataTable, toSortParam } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api, errorMessage, type Schemas } from "@/lib/api/client";
import { useAuth } from "@/lib/auth/auth-context";
import { formatDateTime } from "@/lib/format";
import { ROLE_LABELS, type RoleName } from "@/lib/roles";

import { CreateUserForm } from "./create-user-form";

type User = Schemas["UserOut"];
const PAGE_SIZE = 20;

export default function UsersPage() {
  const { roles } = useAuth();
  const canWrite = roles.includes("admin");
  const [rows, setRows] = useState<User[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [sorting, setSorting] = useState<SortingState>([{ id: "username", desc: false }]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    const { data, error } = await api.GET("/api/v1/users", {
      params: {
        query: { page, page_size: PAGE_SIZE, sort: toSortParam(sorting), search: search || undefined },
      },
    });
    setLoading(false);
    if (!data) {
      toast.error(errorMessage(error, "Could not load users"));
      return;
    }
    setRows(data.items);
    setTotal(data.total);
  }, [page, sorting, search]);

  useEffect(() => {
    void load();
  }, [load]);

  const columns = useMemo<ColumnDef<User, unknown>[]>(
    () => [
      { accessorKey: "username", header: "Username" },
      { accessorKey: "full_name", header: "Name" },
      { accessorKey: "email", header: "Email" },
      {
        id: "roles",
        header: "Roles",
        enableSorting: false,
        cell: ({ row }) => (
          <div className="flex flex-wrap gap-1">
            {row.original.roles.map((r) => (
              <Badge key={r} variant="secondary">
                {ROLE_LABELS[r as RoleName] ?? r}
              </Badge>
            ))}
          </div>
        ),
      },
      {
        accessorKey: "is_active",
        header: "Status",
        enableSorting: false,
        cell: ({ row }) =>
          row.original.is_active ? (
            <Badge variant="outline">Active</Badge>
          ) : (
            <Badge variant="destructive">Inactive</Badge>
          ),
      },
      {
        accessorKey: "last_login_at",
        header: "Last login",
        enableSorting: false,
        cell: ({ row }) => formatDateTime(row.original.last_login_at),
      },
    ],
    [],
  );

  return (
    <>
      <PageHeader
        title="Users"
        description="Accounts are created by administrators; there is no self sign-up."
        actions={
          canWrite && !creating ? (
            <Button onClick={() => setCreating(true)}>
              <Plus /> New user
            </Button>
          ) : undefined
        }
      />
      {creating && (
        <CreateUserForm
          onCancel={() => setCreating(false)}
          onCreated={() => {
            setCreating(false);
            void load();
          }}
        />
      )}
      <div className="mb-4 max-w-xs">
        <Label htmlFor="user-search" className="sr-only">
          Search users
        </Label>
        <Input
          id="user-search"
          placeholder="Search name, username, email"
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
    </>
  );
}
