import { Badge } from "@/components/ui/badge";

const STYLES: Record<
  string,
  { label: string; variant: "default" | "secondary" | "destructive" | "outline" }
> = {
  posted: { label: "Posted", variant: "default" },
  pending_approval: { label: "Pending approval", variant: "secondary" },
  rejected: { label: "Rejected", variant: "destructive" },
  open: { label: "Open", variant: "outline" },
  closed: { label: "Closed", variant: "secondary" },
};

export function StatusBadge({ status }: { status: string }) {
  const style = STYLES[status] ?? { label: status, variant: "outline" as const };
  return <Badge variant={style.variant}>{style.label}</Badge>;
}
