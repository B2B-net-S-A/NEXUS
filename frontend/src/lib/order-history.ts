/**
 * Historia zamówienia MD — filtry i etykiety (ticket 7, 25.09.2026).
 *
 * Grupowanie (import = jeden wpis, seria edycji w 15 minut = jeden wpis)
 * robi SERWER (`GET …/order-groups/{id}/history`); tu wyłącznie filtr nad
 * gotową listą i słowa do przycisków. Czyste funkcje — testowalne bez DOM.
 */
import type {
  OrderHistoryCategory,
  OrderHistoryEntry,
} from "@/lib/api/orderGroups";

export type OrderHistoryCategoryFilter = "all" | OrderHistoryCategory;

export const ORDER_HISTORY_CATEGORY_OPTIONS: {
  value: OrderHistoryCategoryFilter;
  label: string;
}[] = [
  { value: "all", label: "Wszystko" },
  { value: "order", label: "Zamówienie" },
  { value: "consultants", label: "Konsultanci" },
  { value: "consumption", label: "Zużycie MD" },
  { value: "edits", label: "Edycje" },
];

/** Wartość filtra osoby „wszyscy" — pusty napis, bo osoba nie ma pustego imienia. */
export const ALL_PEOPLE = "";

export function filterOrderHistory(
  entries: OrderHistoryEntry[],
  filter: { category: OrderHistoryCategoryFilter; person: string },
): OrderHistoryEntry[] {
  return entries.filter((entry) => {
    if (filter.category !== "all" && entry.category !== filter.category) {
      return false;
    }
    if (filter.person !== ALL_PEOPLE && !entry.person_names.includes(filter.person)) {
      return false;
    }
    return true;
  });
}

/** „6 zmian", „2 zmiany", „1 zmiana". */
export function changesLabel(count: number): string {
  if (count === 1) return "1 zmiana";
  const lastTwo = count % 100;
  const last = count % 10;
  if (last >= 2 && last <= 4 && !(lastTwo >= 12 && lastTwo <= 14)) {
    return `${count} zmiany`;
  }
  return `${count} zmian`;
}

/** Adres widoku „Importy MD" otwierającego konkretny import. */
export function mdImportHref(clientId: number, importId: number): string {
  return `/clients/${clientId}?tab=importy-md&import=${importId}`;
}
