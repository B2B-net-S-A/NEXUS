/**
 * Stawka do klienta (Pipeline v4, decyzja Artura 23.09.2026).
 *
 * Ustala i wpisuje ją WYŁĄCZNIE Delivery Lead (i admin); widzą ją dodatkowo
 * Finanse. Rekruter widzi tylko oczekiwania kandydata i budżet z profilu
 * Championa — kwoty, za którą osoba poszła do klienta, nie widzi w ogóle.
 * Lustro `CLIENT_RATE_VIEW_ROLES` / `CLIENT_RATE_WRITE_ROLES`
 * w `backend/app/api/candidate_access.py` (serwer i tak redaguje kwotę).
 */
import { getUserRoles } from "@/store/auth";

const VIEW_ROLES = new Set(["admin", "delivery_lead", "finance"]);
const WRITE_ROLES = new Set(["admin", "delivery_lead"]);

type UserLike = Parameters<typeof getUserRoles>[0];

export function canViewClientRate(user: UserLike): boolean {
  return getUserRoles(user).some((role) => VIEW_ROLES.has(role));
}

export function canWriteClientRate(user: UserLike): boolean {
  return getUserRoles(user).some((role) => WRITE_ROLES.has(role));
}
