// „Przepisy” (/compliance, 15.11.2026): kto otwiera ekran — lustro
// `require_compliance_access` z `backend/app/api/law_radar.py`.
// Administrator i Head of Recruitment z roli, reszta z jednego z czterech
// uprawnień. Front używa tego wyłącznie do tego, co pokazać; bramką jest serwer.

import { hasAnyPermission, type Permission } from "@/lib/permissions";
import { hasRole, type UserRole } from "@/store/auth";

export const COMPLIANCE_ROLES: readonly UserRole[] = ["admin", "head_of_recruitment"];

export const COMPLIANCE_PERMISSIONS: readonly Permission[] = [
  "finance_module",
  "payroll",
  "people_admin",
  "contracts_orders_edit",
];

type AccessUser = Parameters<typeof hasAnyPermission>[0] & Parameters<typeof hasRole>[0];

export function canOpenCompliance(user: AccessUser): boolean {
  return hasRole(user, ...COMPLIANCE_ROLES) || hasAnyPermission(user, ...COMPLIANCE_PERMISSIONS);
}
