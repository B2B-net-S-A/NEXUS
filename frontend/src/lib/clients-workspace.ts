/**
 * Moduł „Klienci i umowy" po uproszczeniu menu (22.09.2026): z pięciu pozycji
 * (Klienci, Panel klientów, Moje relacje, Kontrakty, Zamówienia z maila)
 * zostały dwie — Klienci i Kontrakty. Dawne ekrany żyją jako TRYBY:
 *
 * | dawny adres          | nowy adres                          |
 * |----------------------|-------------------------------------|
 * | `/my-clients`        | `/clients?mine=1` (przełącznik „Moi klienci") |
 * | `/my-relationships`  | `/clients?view=contacts`            |
 * | `/order-mail`        | `/contracts?view=order-mail`        |
 *
 * Stare adresy przekierowują na stałe — powiadomienia w bazie mają zapisane
 * `link="/order-mail?doc=…"`.
 *
 * Czyste funkcje, bez Reacta — testowane w `clients-workspace.test.ts`.
 */

import type { UserRole } from "@/store/auth";

/** Role z przypisaniem klienta — mają „Moich klientów" i to jest ich domyślny widok. */
export const CLIENTS_MINE_ROLES: readonly UserRole[] = ["delivery_lead", "tac"];

/**
 * „Moi klienci" czy „Wszyscy". Jawne `mine=0/1` w adresie wygrywa; bez niego
 * osoba z przypisaniami widzi swoich, reszta — wszystkich. Bez przypisań
 * „Moich" nie ma wcale (`mine=1` od takiej osoby nic nie zawęża).
 */
export function resolveClientsMine(
  mineAvailable: boolean,
  param: string | null,
): boolean {
  if (!mineAvailable) return false;
  if (param === "0") return false;
  return true;
}

export type ClientsView = "list" | "contacts";

export function resolveClientsView(param: string | null): ClientsView {
  return param === "contacts" ? "contacts" : "list";
}

export type ContractsView = "register" | "operations" | "order-mail";

export function resolveContractsView(param: string | null): ContractsView {
  if (param === "operations") return "operations";
  if (param === "order-mail") return "order-mail";
  return "register";
}

/** Przepisuje query dawnego adresu na nowy, zachowując resztę parametrów (np. `doc`). */
export function legacyRedirectTarget(
  path: string,
  extra: Record<string, string>,
  search: Record<string, string | string[] | undefined>,
): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(search)) {
    if (key in extra || value === undefined) continue;
    for (const item of Array.isArray(value) ? value : [value]) {
      params.append(key, item);
    }
  }
  for (const [key, value] of Object.entries(extra)) params.set(key, value);
  const qs = params.toString();
  return qs ? `${path}?${qs}` : path;
}
