"use client";

import { Plus } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { flattenTree } from "@/lib/accounts-tree";
import { api, errorMessage } from "@/lib/api/client";
import { useAccounts, type Account } from "@/lib/api/hooks";
import { useAuth } from "@/lib/auth/auth-context";
import { can } from "@/lib/permissions";
import { cn } from "@/lib/utils";

import { AccountForm } from "./account-form";

const ALL = "all";
const TYPES = ["asset", "liability", "equity", "revenue", "expense"] as const;

export default function AccountsPage() {
  const { roles } = useAuth();
  const canWrite = can(roles, "manageAccounts");
  const { accounts, loading, reload } = useAccounts();
  const [type, setType] = useState<string>(ALL);
  const [search, setSearch] = useState("");
  const [editing, setEditing] = useState<Account | null>(null);
  const [formOpen, setFormOpen] = useState(false);

  const rows = useMemo(() => {
    const tree = flattenTree(accounts);
    const q = search.trim().toLowerCase();
    return tree.filter(
      (a) =>
        (type === ALL || a.type === type) &&
        (!q || a.code.toLowerCase().includes(q) || a.name.toLowerCase().includes(q)),
    );
  }, [accounts, type, search]);

  const toggleActive = async (a: Account) => {
    const { data, error } = await api.PATCH("/api/v1/accounts/{account_id}", {
      params: { path: { account_id: a.id } },
      body: { is_active: !a.is_active },
    });
    if (!data) toast.error(errorMessage(error, "Could not update account"));
    else {
      toast.success(`${data.code} ${data.is_active ? "activated" : "deactivated"}`);
      void reload();
    }
  };

  return (
    <>
      <PageHeader
        title="Chart of accounts"
        description="Hierarchical accounts used by every posting. Header accounts group others and cannot be posted to."
        actions={
          canWrite ? (
            <Button
              onClick={() => {
                setEditing(null);
                setFormOpen(true);
              }}
            >
              <Plus /> New account
            </Button>
          ) : undefined
        }
      />
      <div className="mb-4 flex flex-wrap gap-3">
        <div className="w-64">
          <Label htmlFor="acc-search" className="sr-only">
            Search accounts
          </Label>
          <Input
            id="acc-search"
            placeholder="Search code or name"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <div className="w-44">
          <Label htmlFor="acc-type-filter" className="sr-only">
            Account type
          </Label>
          <Select value={type} onValueChange={setType}>
            <SelectTrigger id="acc-type-filter" className="w-full capitalize">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>All types</SelectItem>
              {TYPES.map((t) => (
                <SelectItem key={t} value={t} className="capitalize">
                  {t}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>
      <div className="bg-card overflow-x-auto rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-28">Code</TableHead>
              <TableHead>Name</TableHead>
              <TableHead>Type</TableHead>
              <TableHead>Normal balance</TableHead>
              <TableHead>Status</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody aria-busy={loading}>
            {rows.length === 0 && (
              <TableRow>
                <TableCell colSpan={6} className="text-muted-foreground h-24 text-center">
                  {loading ? "Loading…" : "No accounts match."}
                </TableCell>
              </TableRow>
            )}
            {rows.map((a) => (
              <TableRow key={a.id} className={cn(!a.is_active && "opacity-50")}>
                <TableCell className="font-mono text-sm">{a.code}</TableCell>
                <TableCell>
                  <span
                    style={{ paddingLeft: `${a.depth * 1.25}rem` }}
                    className={cn(a.is_header && "font-semibold")}
                  >
                    {a.is_header ? (
                      a.name
                    ) : (
                      <Link href={`/reports?tab=ledger&account=${a.id}`} className="hover:underline">
                        {a.name}
                      </Link>
                    )}
                  </span>
                  {a.is_header && (
                    <Badge variant="outline" className="ml-2 text-[10px]">
                      Header
                    </Badge>
                  )}
                </TableCell>
                <TableCell className="capitalize">{a.type}</TableCell>
                <TableCell className="capitalize">{a.normal_balance}</TableCell>
                <TableCell>
                  {a.is_active ? (
                    <Badge variant="outline">Active</Badge>
                  ) : (
                    <Badge variant="secondary">Inactive</Badge>
                  )}
                </TableCell>
                <TableCell className="text-right">
                  {canWrite && (
                    <div className="flex justify-end gap-1">
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => {
                          setEditing(a);
                          setFormOpen(true);
                        }}
                      >
                        Edit
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => void toggleActive(a)}>
                        {a.is_active ? "Deactivate" : "Activate"}
                      </Button>
                    </div>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <AccountForm
        open={formOpen}
        account={editing}
        accounts={accounts}
        onClose={() => setFormOpen(false)}
        onSaved={() => {
          setFormOpen(false);
          void reload();
        }}
      />
    </>
  );
}
