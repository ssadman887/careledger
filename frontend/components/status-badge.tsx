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
  draft: { label: "Draft", variant: "outline" },
  issued: { label: "Issued", variant: "secondary" },
  partially_paid: { label: "Partially paid", variant: "secondary" },
  paid: { label: "Paid", variant: "default" },
  void: { label: "Void", variant: "destructive" },
  completed: { label: "Completed", variant: "default" },
  cancelled: { label: "Cancelled", variant: "destructive" },
};

export function StatusBadge({ status }: { status: string }) {
  const style = STYLES[status] ?? { label: status, variant: "outline" as const };
  return <Badge variant={style.variant}>{style.label}</Badge>;
}
