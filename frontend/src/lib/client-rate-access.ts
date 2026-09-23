/**
 * Stawka do klienta (Pipeline v4, decyzja Artura 23.09.2026).
 *
 * Ustala i wpisuje ją WYŁĄCZNIE Delivery Lead (i admin); widzą ją dodatkowo
 * Head of Recruitment, TCM i Finanse. Rekruter, sourcer i TAC widzą tylko
 * oczekiwania kandydata i budżet z profilu Championa.
 * Lustro `CLIENT_RATE_VIEW_ROLES` / `CLIENT_RATE_WRITE_ROLES`
 * w `backend/app/api/candidate_access.py` (serwer i tak redaguje kwotę).
 */
import { getUserRoles } from "@/store/auth";

const VIEW_ROLES = new Set([
  "admin",
  "head_of_recruitment",
  "delivery_lead",
  "talent_community_manager",
  "finance",
]);
const WRITE_ROLES = new Set(["admin", "delivery_lead"]);

type UserLike = Parameters<typeof getUserRoles>[0];

export function canViewClientRate(user: UserLike): boolean {
  return getUserRoles(user).some((role) => VIEW_ROLES.has(role));
}

export function canWriteClientRate(user: UserLike): boolean {
  return getUserRoles(user).some((role) => WRITE_ROLES.has(role));
}
