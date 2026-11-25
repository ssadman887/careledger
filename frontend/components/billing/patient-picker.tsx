"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api, type Schemas } from "@/lib/api/client";
import { cn } from "@/lib/utils";

type Patient = Schemas["PatientOut"];

/** Search-as-you-type patient selector (MRN or name). */
export function PatientPicker({
  value,
  onChange,
  id = "patient-search",
}: {
  value: Patient | null;
  onChange: (p: Patient | null) => void;
  id?: string;
}) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Patient[]>([]);

  useEffect(() => {
    if (value) return;
    const handle = setTimeout(() => {
      void api
        .GET("/api/v1/patients", { params: { query: { search: query || undefined, page_size: 8 } } })
        .then(({ data }) => setResults(data?.items ?? []));
    }, 200);
    return () => clearTimeout(handle);
  }, [query, value]);

  if (value) {
    return (
      <div className="flex items-center justify-between rounded-md border px-3 py-2">
        <div>
          <p className="text-sm font-medium">{value.full_name}</p>
          <p className="text-muted-foreground text-xs">
            {value.mrn} · born {value.date_of_birth}
          </p>
        </div>
        <Button type="button" variant="ghost" size="sm" onClick={() => onChange(null)}>
          Change
        </Button>
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-2">
      <Label htmlFor={id}>Patient</Label>
      <Input
        id={id}
        placeholder="Search MRN or name"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        autoComplete="off"
      />
      <ul
        role="listbox"
        aria-label="Matching patients"
        className="max-h-64 overflow-y-auto rounded-md border"
      >
        {results.length === 0 && <li className="text-muted-foreground px-3 py-2 text-sm">No matches</li>}
        {results.map((p) => (
          <li key={p.id} role="option" aria-selected={false}>
            <button
              type="button"
              onClick={() => onChange(p)}
              className={cn(
                "hover:bg-accent focus-visible:bg-accent flex w-full items-center justify-between px-3 py-2 text-left text-sm outline-none",
              )}
            >
              <span>{p.full_name}</span>
              <span className="text-muted-foreground font-mono text-xs">{p.mrn}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
