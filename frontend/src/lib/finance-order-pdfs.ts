/**
 * Finanse → „Zamówienia PDF": etykiety i formatowanie (czyste funkcje).
 */

import type { OrderPdfEntryType, OrderPdfFile } from "@/lib/api/finance";
import {
  MONTHS_PL,
  formatDay,
  formatMoment,
  parseMonthValue,
} from "@/lib/finance-order-changes";
import {
  ORDER_GROUP_STATUS_LABELS,
  ORDER_STATUS_LABELS,
} from "@/lib/status-labels";

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

/**
 * Status zamówienia przy pliku. Etykiety z jednego słownika (`status-labels`)
 * — lista łączy zamówienia okresowe (`client_orders`) i zamówienia MD/kosztowe
 * (`client_order_groups`). Do 24.09.2026 lokalna kopia nie znała
 * „cancelled”, więc anulowane zamówienie pokazywało surowy kod.
 */
const STATUS_LABELS: Record<string, string> = {
  ...ORDER_STATUS_LABELS,
  ...ORDER_GROUP_STATUS_LABELS,
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

/**
 * Status pobrania ZALOGOWANEJ osoby: „● Nowy" albo „Pobrane przez Ciebie
 * 22.09.2026". Pobranie przez kogoś innego nic tu nie zmienia.
 */
export function downloadStatusLabel(
  file: Pick<OrderPdfFile, "downloaded_at">,
): string {
  if (!file.downloaded_at) return "● Nowy";
  return `Pobrane przez Ciebie ${formatMoment(file.downloaded_at).slice(0, 10)}`;
}

/** Pliki jeszcze niepobrane przez zalogowaną osobę. */
export function newFilesCount(files: Pick<OrderPdfFile, "downloaded_at">[]): number {
  return files.filter((file) => !file.downloaded_at).length;
}

/** „1 nowy", „3 nowe", „12 nowych". */
export function newFilesLabel(count: number): string {
  if (count === 1) return "1 nowy";
  const mod10 = count % 10;
  const mod100 = count % 100;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) {
    return `${count} nowe`;
  }
  return `${count} nowych`;
}

/** Awaryjna nazwa ZIP-a, gdy serwer nie poda swojej: `[Klient]_[RRRR-MM].zip`. */
export function zipFallbackName(clientName: string | null, month: string): string {
  if (!clientName) return `Zamowienia_${month}.zip`;
  const slug = clientName
    .replace(/ł/g, "l")
    .replace(/Ł/g, "L")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^A-Za-z0-9.-]+/g, "_")
    .replace(/^[_.-]+|[_.-]+$/g, "");
  return `${slug || "klient"}_${month}.zip`;
}
