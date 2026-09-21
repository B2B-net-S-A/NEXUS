/**
 * Finanse → „Zamówienia PDF": etykiety i formatowanie (czyste funkcje).
 */

import type { OrderPdfEntryType, OrderPdfFile } from "@/lib/api/finance";
import { MONTHS_PL, formatDay, parseMonthValue } from "@/lib/finance-order-changes";

/** „2026-09" → „Wrzesień 2026". */
export function orderPdfMonthLabel(value: string): string {
  const parsed = parseMonthValue(value);
  if (!parsed) return value;
  return `${MONTHS_PL[parsed.month - 1]} ${parsed.year}`;
}

/** Okres w tym samym formacie, co w nazwie pliku: DD.MM.RRRR–DD.MM.RRRR. */
export function orderPdfPeriod(file: Pick<OrderPdfFile, "start" | "end">): string {
  return `${formatDay(file.start)}–${file.end ? formatDay(file.end) : "bezterminowo"}`;
}

const ENTRY_TYPE_LABELS: Record<OrderPdfEntryType, string> = {
  new: "Nowe zamówienie",
  extension: "Przedłużenie",
  amendment: "Aneks",
};

export function orderPdfEntryTypeLabel(type: OrderPdfEntryType): string {
  return ENTRY_TYPE_LABELS[type];
}

const STATUS_LABELS: Record<string, string> = {
  draft: "Szkic",
  active: "Aktywne",
  paused: "Wstrzymane",
  scheduled: "Zaplanowane",
  completed: "Zakończone",
  exhausted: "Wyczerpane",
};

export function orderPdfStatusLabel(status: string | null): string | null {
  if (!status) return null;
  return STATUS_LABELS[status] ?? status;
}

export function orderPdfKey(file: Pick<OrderPdfFile, "kind" | "id">): string {
  return `${file.kind}:${file.id}`;
}

export function filesLabel(count: number): string {
  if (count === 1) return "1 plik";
  const mod10 = count % 10;
  const mod100 = count % 100;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) {
    return `${count} pliki`;
  }
  return `${count} plików`;
}

export function clientsLabel(count: number): string {
  return count === 1 ? "1 klient" : `${count} klientów`;
}
