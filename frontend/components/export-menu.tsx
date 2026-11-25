"use client";

import { Download } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { ExportFormat } from "@/lib/api/exports";

/** "Export" button offering CSV and PDF. Exports are recorded in the audit log. */
export function ExportMenu({
  onExport,
  label = "Export",
  formats = ["csv", "pdf"],
}: {
  onExport: (format: ExportFormat) => Promise<void>;
  label?: string;
  formats?: readonly ExportFormat[];
}) {
  const [busy, setBusy] = useState(false);
  const run = async (format: ExportFormat) => {
    setBusy(true);
    try {
      await onExport(format);
    } finally {
      setBusy(false);
    }
  };
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" disabled={busy}>
          <Download /> {label}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {formats.includes("csv") && (
          <DropdownMenuItem onSelect={() => void run("csv")}>CSV (spreadsheet)</DropdownMenuItem>
        )}
        {formats.includes("pdf") && <DropdownMenuItem onSelect={() => void run("pdf")}>PDF</DropdownMenuItem>}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
