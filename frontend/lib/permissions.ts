import type { RoleName } from "@/lib/roles";

/**
 * UI affordances only. The backend enforces every one of these rules; hiding a button is
 * never the security boundary. Keep in sync with the role dependencies in app/api/v1.
 */
const RULES = {
  manageAccounts: ["admin", "accountant"],
  postJournal: ["accountant"],
  approveJournal: ["finance_manager"],
  managePeriods: ["accountant", "finance_manager"],
  manageUsers: ["admin"],
  bill: ["billing_clerk"],
  voidInvoice: ["billing_clerk", "finance_manager"],
  approveRefund: ["finance_manager"],
  readLedger: ["accountant", "finance_manager", "auditor"],
  draftClaim: ["billing_clerk", "insurance_officer"],
  workClaims: ["insurance_officer"],
  manageInsurers: ["insurance_officer", "admin"],
  managePolicies: ["insurance_officer", "billing_clerk"],
  collections: ["billing_clerk", "finance_manager"],
  managePayables: ["accountant"],
  editApprovalPolicies: ["admin", "finance_manager"],
  approvalOversight: ["finance_manager", "auditor", "admin"],
  managePayroll: ["accountant"],
  approvePayroll: ["finance_manager"],
  editTaxSlabs: ["accountant", "finance_manager"],
  manageBudgets: ["finance_manager"],
  readAudit: ["admin", "finance_manager", "auditor"],
} as const satisfies Record<string, readonly RoleName[]>;

export type Permission = keyof typeof RULES;

export function can(roles: readonly RoleName[], permission: Permission): boolean {
  const allowed: readonly RoleName[] = RULES[permission];
  return roles.some((r) => allowed.includes(r));
}
