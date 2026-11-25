"use client";

import { toast } from "sonner";

import { api, errorMessage } from "@/lib/api/client";

import type { paths } from "./schema";

export type ExportFormat = "csv" | "pdf";
export type ExportPath = Extract<keyof paths, `/api/v1/exports/${string}`>;
type Query = Record<string, string | number | boolean | null | undefined>;

// One loosely-typed call for every export route: they all return a file and differ only in
// their (validated server-side) query parameters. The auth middleware still applies.
type LooseGet = (
  path: ExportPath,
  init: { params: { query: Query; path?: Record<string, number> }; parseAs: "blob" },
) => Promise<{ data?: Blob; error?: unknown; response: Response }>;

/** Filename from `Content-Disposition: attachment; filename="x.csv"`. */
export function filenameFrom(header: string | null, fallback: string): string {
  const match = header ? /filename="?([^";]+)"?/i.exec(header) : null;
  return match?.[1] ?? fallback;
}

export async function downloadExport(
  path: ExportPath,
  format: ExportFormat,
  query: Query = {},
  pathParams?: Record<string, number>,
): Promise<void> {
  const clean = Object.fromEntries(
    Object.entries({ ...query, format }).filter(([, v]) => v != null && String(v) !== ""),
  );
  const get = api.GET as unknown as LooseGet;
  const { data, error, response } = await get(path, {
    params: { query: clean, path: pathParams },
    parseAs: "blob",
  });
  if (!data) return void toast.error(errorMessage(error, "Export failed"));
  const url = URL.createObjectURL(data);
  const a = document.createElement("a");
  a.href = url;
  a.download = filenameFrom(response.headers.get("content-disposition"), `export.${format}`);
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 30_000);
  toast.success(`Downloaded ${a.download}`);
}
