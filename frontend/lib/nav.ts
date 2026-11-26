import type { RoleName } from "@/lib/roles";
import { hasAnyRole } from "@/lib/roles";

export interface NavItem {
  label: string;
  href: string;
  /** Roles that see this item. Auditors see every module (read-only). */
  roles: readonly RoleName[];
  /** Build phase that delivers the page; items from later phases render as "soon". */
  phase: number;
}

export interface NavSection {
  title: string;
  items: readonly NavItem[];
}

/** Phase currently implemented. Bump as phases land. */
export const CURRENT_PHASE = 7;

const ALL: readonly RoleName[] = [
  "admin",
  "billing_clerk",
  "insurance_officer",
  "accountant",
  "finance_manager",
  "auditor",
];

export const NAV: readonly NavSection[] = [
  {
    title: "Overview",
    items: [{ label: "Dashboard", href: "/dashboard", roles: ALL, phase: 0 }],
  },
  {
    title: "Revenue cycle",
    items: [
      {
        label: "Patients",
        href: "/patients",
        roles: ["billing_clerk", "insurance_officer", "finance_manager"],
        phase: 2,
      },
      { label: "Invoices", href: "/invoices", roles: ["billing_clerk", "finance_manager"], phase: 2 },
      { label: "Payments", href: "/payments", roles: ["billing_clerk", "finance_manager"], phase: 2 },
      {
        label: "Claims",
        href: "/claims",
        roles: ["insurance_officer", "billing_clerk", "finance_manager"],
        phase: 3,
      },
      {
        label: "Remittances",
        href: "/remittances",
        roles: ["insurance_officer", "finance_manager"],
        phase: 3,
      },
      {
        label: "Insurers",
        href: "/insurers",
        roles: ["insurance_officer", "billing_clerk", "finance_manager", "admin"],
        phase: 3,
      },
      {
        label: "AR aging",
        href: "/ar",
        roles: ["billing_clerk", "insurance_officer", "finance_manager", "accountant"],
        phase: 4,
      },
    ],
  },
  {
    title: "Accounting",
    items: [
      {
        label: "Chart of accounts",
        href: "/accounts",
        roles: ["admin", "accountant", "finance_manager"],
        phase: 1,
      },
      { label: "Journal entries", href: "/journal", roles: ["accountant", "finance_manager"], phase: 1 },
      { label: "Fiscal periods", href: "/periods", roles: ["accountant", "finance_manager"], phase: 1 },
      { label: "Financial reports", href: "/reports", roles: ["accountant", "finance_manager"], phase: 1 },
      { label: "Payables", href: "/payables", roles: ["accountant", "finance_manager"], phase: 4 },
      { label: "Payroll", href: "/payroll", roles: ["accountant", "finance_manager"], phase: 5 },
      { label: "Budgets", href: "/budgets", roles: ["finance_manager", "accountant"], phase: 5 },
    ],
  },
  {
    title: "Governance",
    items: [
      {
        label: "Approvals",
        href: "/approvals",
        roles: ["finance_manager", "accountant", "billing_clerk", "admin"],
        phase: 4,
      },
      { label: "Audit log", href: "/audit", roles: ["admin", "finance_manager"], phase: 6 },
      { label: "Users", href: "/admin/users", roles: ["admin"], phase: 0 },
    ],
  },
];

/** Navigation filtered for the user's roles (auditors see everything). Empty sections removed. */
export function navForRoles(roles: readonly RoleName[]): NavSection[] {
  const isAuditor = roles.includes("auditor");
  return NAV.map((section) => ({
    title: section.title,
    items: section.items.filter((item) => isAuditor || hasAnyRole(roles, item.roles)),
  })).filter((section) => section.items.length > 0);
}

export function isAvailable(item: NavItem): boolean {
  return item.phase <= CURRENT_PHASE;
}
