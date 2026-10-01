/**
 * Wybór klienta w Rekrutacjach i Kontraktach pokazuje tylko klientów
 * z zakładek „Aktywni” i „Relacyjni” (ticket 30.09.2026). Rekrutacja bywa
 * jednak przypisana do klienta, który od tego czasu przeszedł do
 * „Nieaktywnych” — wtedy pole edycji musi nadal pokazywać JEGO, a nie
 * pierwszą pozycję listy. Bieżący klient trafia więc na listę, nawet gdy
 * filtr go pomija; nowego nieaktywnego klienta wybrać się nie da.
 */

import type { ClientRef } from "@/lib/contract-client-filter";

export function withCurrentClient(
  clients: readonly ClientRef[],
  currentId: number | string | null | undefined,
  currentName: string | null | undefined,
): ClientRef[] {
  const id = Number(currentId);
  if (!currentId || !Number.isFinite(id) || clients.some((c) => c.id === id)) {
    return [...clients];
  }
  return [{ id, name: currentName?.trim() || `Klient #${id}` }, ...clients];
}

/** Klucze react-query list wyboru klienta (`/api/clients-lookup`). */
export function isClientPickerQueryKey(queryKey: readonly unknown[]): boolean {
  const head = queryKey[0];
  return (
    typeof head === "string" &&
    (head.startsWith("clients-lookup") || head === "contract-reassign-clients")
  );
}
