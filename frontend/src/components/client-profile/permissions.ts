/**
 * Bramki przycisków zapisu na profilu klienta — lustra guardów backendu.
 *
 * Audyt 24.09.2026 (S11/W2): profil pokazywał przyciski, które dla danej roli
 * kończyły się 403 („Dodaj wiedzę", umowy wykonawcze, „Przedłuż", „Dodaj"
 * w Projektach). Źródłem prawdy zostaje backend — tu tylko nie pokazujemy
 * akcji, której serwer i tak odmówi.
 *
 * Od 0409 backend pyta o uprawnienia z ekranu Ustawienia → Zespół i dostęp →
 * Osoby i role, więc te bramki też (`lib/permissions.ts`): przycisk widzi
 * każdy posiadacz uprawnienia, a rola, której je wyłączono — nie.
 */

import { hasPermission } from "@/lib/permissions";
import { hasSectionAccess } from "@/lib/section-access";
import { hasRole, isClientInAssignedScope, type User } from "@/store/auth";

type PermissionUser =
  | Pick<
      User,
      | "role"
      | "roles"
      | "effective_section_access"
      | "effective_action_access"
      | "data_scope"
    >
  | null
  | undefined;

/**
 * „Klienci: dodawanie i edycja” — wiedza o kliencie, materiały, kontakty
 * (`ClientAccess.can_edit_*` w backendzie). Sekcja Delivery (zapis) jest
 * sufitem trasy: przy świeżym profilu wynika z uprawnienia, stary wyjątek
 * osoby potrafi ją jeszcze ograniczyć.
 */
export function canManageClientDelivery(user: PermissionUser): boolean {
  return (
    hasPermission(user, "clients_edit") &&
    hasSectionAccess(user, "delivery", "write")
  );
}

/**
 * „Kontrakty i zamówienia: tworzenie i edycja” — „Przedłuż” na profilu klienta
 * (`POST /api/contracts/bulk-extend`). Osobne od `canManageClientDelivery`:
 * Finanse przedłużają kontrakty, a klientów nie edytują.
 */
export function canManageClientContracts(user: PermissionUser): boolean {
  return (
    hasPermission(user, "contracts_orders_edit") &&
    hasSectionAccess(user, "delivery", "write")
  );
}

/**
 * „Przegrana” w Projektach — `POST /api/jobs/{id}/close` wymaga uprawnienia
 * „Rekrutacje: zakładanie, zamykanie, wysyłka CV do klienta” pod bramką
 * sekcji Pipeline (zapis).
 */
export function canCloseJobAsLost(user: PermissionUser): boolean {
  return (
    hasPermission(user, "recruitment_manage") &&
    hasSectionAccess(user, "pipeline", "write")
  );
}

/**
 * „Dodaj” kandydata do rekrutacji z Projektów — `POST /api/pipeline/move`
 * = `RecruiterPlus` (każda rola operacyjna, bez podglądu `user`) pod bramką
 * sekcji Pipeline (zapis). Zostaje przy roli: to nie jest jedno z uprawnień
 * z ekranu.
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
 * Umowy wykonawcze i przypisania do nich — lustro `ClientContractsEditUser`:
 * „Kontrakty i zamówienia: tworzenie i edycja” u klienta z przypisania. Konto
 * z rolą Delivery Leada ma go w `data_scope.finance_client_ids` (portfel
 * z `GET /api/auth/me`); pozostałych posiadaczy przypisanie nie dotyczy.
 */
export function canManageAssignedClient(
  user: PermissionUser,
  clientId: number,
): boolean {
  return canManageClientContracts(user) && isClientInAssignedScope(user, clientId);
}
