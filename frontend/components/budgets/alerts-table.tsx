import Link from "next/link";

import { StatusBadge } from "@/components/status-badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { Schemas } from "@/lib/api/client";
import { formatDateTime } from "@/lib/format";

export function AlertsTable({ alerts }: { alerts: Schemas["BudgetAlertOut"][] }) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Raised</TableHead>
          <TableHead>Level</TableHead>
          <TableHead>Alert</TableHead>
          <TableHead className="text-right">Used</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {alerts.length === 0 && (
          <TableRow>
            <TableCell colSpan={4} className="text-muted-foreground h-16 text-center">
              No alerts.
            </TableCell>
          </TableRow>
        )}
        {alerts.map((a) => (
          <TableRow key={a.id}>
            <TableCell className="text-sm whitespace-nowrap">{formatDateTime(a.created_at)}</TableCell>
            <TableCell>
              <StatusBadge status={a.level} />
            </TableCell>
            <TableCell className="max-w-xl">
              <Link href={`/budgets/${a.budget_id}`} className="text-sm hover:underline">
                {a.message}
              </Link>
            </TableCell>
            <TableCell className="text-right tabular-nums">{a.percent_used}%</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
