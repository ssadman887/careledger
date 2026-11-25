import type { Schemas } from "@/lib/api/client";

/** Where to see the business record behind an approval request. */
export function entityHref(a: Pick<Schemas["ApprovalOut"], "kind" | "entity_id">): string {
  switch (a.kind) {
    case "manual_journal":
      return `/journal/${a.entity_id}`;
    case "refund":
      return "/payments?tab=refunds";
    case "write_off":
      return "/ar?tab=write-offs";
    case "vendor_bill":
      return `/payables/bills/${a.entity_id}`;
    default:
      return "/approvals";
  }
}
