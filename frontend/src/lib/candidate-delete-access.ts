import { hasRole, type User } from "@/store/auth";

/**
 * Czy użytkownik może trwale usunąć profil kandydata.
 *
 * Wydzielone z `CandidateDetailV2` do osobnej jednostki, bo to jedyne
 * kryterium z ticketu, które da się tanio i wiarygodnie pokryć testem —
 * zamontowanie całego profilu (4,6 tys. linii, kilkadziesiąt zależności) nie
 * jest w tym repo utartą praktyką, a test, który sam odtwarza tę regułę,
 * sprawdzałby własną kopię, nie kod produkcyjny.
 *
 * WYŁĄCZNIE `admin`, celowo węziej niż przy zwykłej edycji kandydata:
 * - `admin` to szczyt hierarchii (`ROLE_RANK`), więc „Admin lub wyższa"
 *   z ticketu znaczy dokładnie tę jedną rolę;
 * - `delivery_lead` jest tu istotnym przypadkiem negatywnym, nie
 *   hipotetycznym: do 2026-08 endpoint był chroniony `DeliveryLeadPlus`, więc
 *   DL usuwanie mógł. To zawężenie jest zmianą, którą trzeba pilnować.
 *
 * Lustro guardu backendu (`CandidateHardDeleteAccess`). Frontend ukrywa opcję,
 * backend ją odrzuca — ukrycie w UI nie jest zabezpieczeniem, tylko
 * uprzejmością wobec użytkownika, który i tak dostałby 403.
 */
export function canHardDeleteCandidate(
  user: Pick<User, "role" | "roles"> | null | undefined,
): boolean {
  return hasRole(user, "admin");
}
