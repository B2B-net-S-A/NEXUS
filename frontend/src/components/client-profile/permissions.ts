/**
 * Bramki przycisków zapisu na profilu klienta — lustra guardów backendu.
 *
 * Audyt 24.09.2026 (S11/W2): profil pokazywał przyciski, które dla danej roli
 * kończyły się 403 („Dodaj wiedzę", umowy wykonawcze, „Przedłuż", „Dodaj"
 * w Projektach). Źródłem prawdy zostaje backend — tu tylko nie pokazujemy
 * akcji, której serwer i tak odmówi.
 */

import { hasSectionAccess } from "@/lib/section-access";
import { hasRole, type User } from "@/store/auth";

type PermissionUser =
  | Pick<User, "role" | "roles" | "effective_section_access" | "data_scope">
  | null
  | undefined;

/**
 * Admin albo Delivery Lead z zapisem sekcji Delivery — lustro
 * `DeliveryLeadPlus` (backend/app/api/deps.py) pod bramką sekcji Delivery:
 * `POST /api/contracts/bulk-extend`, `POST /api/jobs/{id}/close`, wiedza
 * o kliencie (`ClientAccess.can_edit_knowledge`).
 */
export function canManageClientDelivery(user: PermissionUser): boolean {
  return (
    hasRole(user, "admin", "delivery_lead") &&
    hasSectionAccess(user, "delivery", "write")
  );
}

/**
 * „Przegrana” w Projektach — `POST /api/jobs/{id}/close` = `DeliveryLeadPlus`
 * pod bramką sekcji Pipeline (zapis).
 */
export function canCloseJobAsLost(user: PermissionUser): boolean {
  return (
    hasRole(user, "admin", "delivery_lead") &&
    hasSectionAccess(user, "pipeline", "write")
  );
}

/**
 * „Dodaj” kandydata do rekrutacji z Projektów — `POST /api/pipeline/move`
 * = `RecruiterPlus` (każda rola operacyjna, bez podglądu `user`) pod bramką
 * sekcji Pipeline (zapis).
 */
export function canMoveInPipeline(user: PermissionUser): boolean {
  return (
    hasRole(
      user,
      "admin",
      "head_of_recruitment",
      "delivery_lead",
      "talent_community_manager",
      "tac",
      "recruiter",
      "finance",
      "sourcer",
    ) && hasSectionAccess(user, "pipeline", "write")
  );
}

/**
 * Admin albo Delivery Lead PRZYPISANY do tego klienta — lustro
 * `DlAssignedOrAdmin` (umowy wykonawcze, przypisania). Przypisanie DL-a
 * czytamy z `data_scope.finance_client_ids` (portfel z `GET /api/auth/me`).
 */
export function canManageAssignedClient(
  user: PermissionUser,
  clientId: number,
): boolean {
  if (!hasSectionAccess(user, "delivery", "write")) return false;
  if (hasRole(user, "admin")) return true;
  if (!hasRole(user, "delivery_lead")) return false;
  const scope = user?.data_scope;
  if (!scope || scope.kind !== "delivery_clients") return false;
  return (scope.finance_client_ids ?? []).includes(clientId);
}
