"use client";

import { Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import { Input } from "@/components/ui/input";
import { api, type Schemas } from "@/lib/api/client";
import { cn } from "@/lib/utils";

const DEBOUNCE_MS = 250;

/** Header search across records the user may read. Press "/" or Ctrl+K to focus. */
export function GlobalSearch() {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const [q, setQ] = useState("");
  const [groups, setGroups] = useState<Schemas["SearchGroupOut"][]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const hits = useMemo(() => groups.flatMap((g) => g.hits.map((h) => ({ ...h, group: g.label }))), [groups]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = e.target instanceof HTMLElement && /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName);
      if ((e.key === "k" && (e.ctrlKey || e.metaKey)) || (e.key === "/" && !typing)) {
        e.preventDefault();
        inputRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    const term = q.trim();
    if (term.length < 2) {
      setGroups([]);
      return;
    }
    const t = setTimeout(() => {
      void api.GET("/api/v1/search", { params: { query: { q: term } } }).then(({ data }) => {
        setGroups(data?.groups ?? []);
        setActive(0);
      });
    }, DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [q]);

  const go = (href: string) => {
    setOpen(false);
    setQ("");
    inputRef.current?.blur();
    router.push(href);
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((i) => Math.min(i + 1, hits.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter" && hits[active]) {
      e.preventDefault();
      go(hits[active].href);
    } else if (e.key === "Escape") {
      setOpen(false);
      inputRef.current?.blur();
    }
  };

  const showPanel = open && q.trim().length >= 2;
  let index = -1;
  return (
    <div className="relative w-full max-w-md">
      <Search className="text-muted-foreground pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2" />
      <Input
        ref={inputRef}
        role="combobox"
        aria-expanded={showPanel}
        aria-controls="global-search-results"
        aria-label="Search records"
        placeholder="Search patients, invoices, claims, entries…  ( / )"
        className="pl-8"
        value={q}
        onChange={(e) => {
          setQ(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        onKeyDown={onKeyDown}
      />
      {showPanel && (
        <div
          id="global-search-results"
          role="listbox"
          className="bg-popover text-popover-foreground absolute top-full right-0 left-0 z-50 mt-1 max-h-[60vh] overflow-y-auto rounded-md border p-1 shadow-lg"
        >
          {groups.length === 0 && <p className="text-muted-foreground px-3 py-4 text-sm">No matches.</p>}
          {groups.map((g) => (
            <div key={g.type} role="group" aria-label={g.label}>
              <p className="text-muted-foreground px-2 pt-2 pb-1 text-[11px] font-semibold tracking-wider uppercase">
                {g.label}
              </p>
              {g.hits.map((h) => {
                index += 1;
                const i = index;
                return (
                  <button
                    key={`${g.type}-${h.id}-${h.href}`}
                    type="button"
                    role="option"
                    aria-selected={i === active}
                    onMouseDown={(e) => e.preventDefault()}
                    onMouseEnter={() => setActive(i)}
                    onClick={() => go(h.href)}
                    className={cn(
                      "block w-full rounded-sm px-2 py-1.5 text-left",
                      i === active && "bg-accent text-accent-foreground",
                    )}
                  >
                    <span className="block text-sm font-medium">{h.title}</span>
                    <span className="text-muted-foreground block truncate text-xs">{h.subtitle}</span>
                  </button>
                );
              })}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
