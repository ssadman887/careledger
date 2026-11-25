import { TriangleAlert } from "lucide-react";

export const DEMO_BANNER_TEXT = "Demo system. Synthetic data only. Not for real patient data.";

/** Persistent banner shown on every page (spec rule 13). */
export function DemoBanner() {
  return (
    <div
      role="status"
      className="bg-warning text-warning-foreground sticky top-0 z-50 flex items-center justify-center gap-2 px-4 py-1.5 text-center text-xs font-medium"
    >
      <TriangleAlert aria-hidden className="size-3.5 shrink-0" />
      <span>{DEMO_BANNER_TEXT}</span>
    </div>
  );
}
