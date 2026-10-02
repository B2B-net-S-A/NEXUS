/**
 * Stawka do klienta (Pipeline v4, decyzja Artura 23.09.2026).
 *
 * Ustala i wpisuje ją posiadacz uprawnienia „Rekrutacje: zakładanie,
 * zamykanie, wysyłka CV do klienta” (domyślnie Delivery Lead i admin); widzą
 * ją dodatkowo Head of Recruitment, TCM i Finanse. Rekruter, sourcer i TAC
 * widzą tylko oczekiwania kandydata i budżet z profilu Championa.
 *
 * To reguły ZAPASOWE — gdy odpowiedź serwera nie niesie `can_view_client_rate`
 * / `can_write_client_rate`. Odczyt zostaje przy roli (lustro
 * `CLIENT_RATE_VIEW_ROLES` w `backend/app/api/candidate_access.py`), zapis
 * idzie za uprawnieniem (`user_can_write_client_rate`). Serwer i tak redaguje
 * kwotę.
 */
import { hasPermission, type PermissionUser } from "@/lib/permissions";
import { getUserRoles } from "@/store/auth";

const VIEW_ROLES = new Set([
  "admin",
  "head_of_recruitment",
  "delivery_lead",
  "talent_community_manager",
  "finance",
]);

type UserLike = Parameters<typeof getUserRoles>[0];

export function canViewClientRate(user: UserLike): boolean {
  return getUserRoles(user).some((role) => VIEW_ROLES.has(role));
}

export function canWriteClientRate(
  user: PermissionUser | null | undefined,
): boolean {
  return hasPermission(user, "recruitment_manage");
}
