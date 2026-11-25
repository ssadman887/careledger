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
  cancelled: { label: "Cancelled", variant: "outline" },
  submitted: { label: "Submitted", variant: "secondary" },
  under_review: { label: "Under review", variant: "secondary" },
  approved: { label: "Approved", variant: "default" },
  partially_approved: { label: "Partially approved", variant: "secondary" },
  denied: { label: "Denied", variant: "destructive" },
  appealed: { label: "Appealed", variant: "secondary" },
  matched: { label: "Matched", variant: "default" },
  short_paid: { label: "Short paid", variant: "secondary" },
  overpaid: { label: "Overpaid", variant: "destructive" },
  unmatched: { label: "Unmatched", variant: "destructive" },
  imported: { label: "Imported", variant: "secondary" },
};

export function StatusBadge({ status }: { status: string }) {
  const style = STYLES[status] ?? { label: status, variant: "outline" as const };
  return <Badge variant={style.variant}>{style.label}</Badge>;
}
