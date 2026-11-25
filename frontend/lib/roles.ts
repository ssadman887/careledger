import type { components } from "@/lib/api/schema";

export type RoleName = components["schemas"]["RoleName"];

export const ROLE_LABELS: Record<RoleName, string> = {
  admin: "Administrator",
  billing_clerk: "Billing clerk",
  insurance_officer: "Insurance officer",
  accountant: "Accountant",
  finance_manager: "Finance manager",
  auditor: "Auditor",
};

export function hasAnyRole(userRoles: readonly RoleName[], allowed: readonly RoleName[]): boolean {
  return allowed.some((r) => userRoles.includes(r));
}
