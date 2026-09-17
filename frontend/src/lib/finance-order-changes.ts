// Finanse → Zmiany w zamówieniach: formatowanie wierszy czterech podzakładek.
//
// Czyste funkcje (bez Reacta), żeby dało się je przetestować bez montowania
// widoku. Werdykty i reguły następcy liczy SERWER — tu tylko opis.

import type {
  OrderChangeItem,
  OrderEntryItem,
  OrderExitItem,
  OrderGapItem,
  OrderTypeCode,
  RateUnitCode,
} from "@/lib/api/finance";

export const MONTHS_PL = [
  "Styczeń",
  "Luty",
  "Marzec",
  "Kwiecień",
  "Maj",
  "Czerwiec",
  "Lipiec",
  "Sierpień",
  "Wrzesień",
  "Październik",
  "Listopad",
  "Grudzień",
] as const;

export interface MonthOption {
  value: string; // "RRRR-MM"
  year: number;
  month: number;
  label: string;
}

export function monthValue(year: number, month: number): string {
  return `${year}-${String(month).padStart(2, "0")}`;
}

export function parseMonthValue(
  value: string | null | undefined,
): { year: number; month: number } | null {
  const match = /^(\d{4})-(\d{2})$/.exec(value ?? "");
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  if (month < 1 || month > 12) return null;
  return { year, month };
}

/**
 * Kolejny miesiąc + bieżący + 24 wstecz. Kolejny, bo rozliczenia na
 * nadchodzący miesiąc startują ok. 17. dnia bieżącego — wejścia od 1. dnia
 * następnego miesiąca są już wtedy znane.
 */
export function monthOptions(today: Date, back = 24): MonthOption[] {
  const options: MonthOption[] = [];
  for (let offset = 1; offset >= -back; offset -= 1) {
    const d = new Date(today.getFullYear(), today.getMonth() + offset, 1);
    const year = d.getFullYear();
    const month = d.getMonth() + 1;
    options.push({
      value: monthValue(year, month),
      year,
      month,
      label: `${MONTHS_PL[month - 1]} ${year}`,
    });
  }
  return options;
}

const TYPE_LABELS: Record<OrderTypeCode, string> = {
  periodic: "B2B",
  cost: "Kosztowe",
  md: "MD",
};

export function orderTypeLabel(type: OrderTypeCode): string {
  return TYPE_LABELS[type] ?? type;
}

const UNIT_LABELS: Record<RateUnitCode, string> = {
  hourly: "h",
  daily: "dzień",
  monthly: "mc",
  md: "MD",
};

const MONEY = new Intl.NumberFormat("pl-PL", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

/** „152,00 zł/h" — kwota zawsze z jednostką (152 bez niej nie jest stawką). */
export function formatRate(
  amount: number | null | undefined,
  unit: RateUnitCode | null | undefined,
  currency: string | null | undefined,
): string {
  if (amount === null || amount === undefined) return "—";
  const code = (currency ?? "PLN").toUpperCase();
  const money = `${MONEY.format(amount)} ${code === "PLN" ? "zł" : code}`;
  const unitLabel = unit ? UNIT_LABELS[unit] : null;
  return unitLabel ? `${money}/${unitLabel}` : money;
}

/** „2026-09-01" → „01.09.2026". Parsowane jako data, bez strefy czasowej. */
export function formatDay(iso: string | null | undefined): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso ?? "");
  if (!match) return "—";
  return `${match[3]}.${match[2]}.${match[1]}`;
}

export function formatMoment(iso: string | null | undefined): string {
  if (!iso) return "—";
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return "—";
  return parsed.toLocaleString("pl-PL", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function initials(name: string): string {
  const parts = name
    .replace(/[^\p{L}\s-]/gu, " ")
    .split(/[\s-]+/)
    .filter(Boolean);
  if (parts.length === 0) return "—";
  const first = parts[0][0] ?? "";
  const last = parts.length > 1 ? parts[parts.length - 1][0] ?? "" : "";
  return (first + last).toUpperCase();
}

/** „Klient · zam. NB-2291 · od 01.09.2026 · 152,00 zł/h → 180,00 zł/h" */
export function entryDetails(item: OrderEntryItem): string {
  const parts = [
    item.client_name,
    `zam. ${item.order_number}`,
    `od ${formatDay(item.start_date)}`,
    `koszt ${formatRate(item.rate_cost, item.rate_unit, item.currency)}`,
    `przychód ${formatRate(item.rate_revenue, item.rate_unit, item.currency)}`,
  ];
  return parts.join(" · ");
}

/**
 * W Wejściach są WYŁĄCZNIE osoby nowe — stąd stała plakietka. Kontynuacje,
 * zmiany klienta i dodatkowe projekty mają własne wiersze w Zmianach.
 */
export function entryTags(item: OrderEntryItem): string[] {
  const tags = ["Nowy konsultant"];
  if (item.status === "draft") tags.push("Szkic");
  return tags;
}

export function exitDetails(item: OrderExitItem): string {
  return [
    item.client_name,
    `zam. ${item.order_number}`,
    `do ${formatDay(item.end_date)}`,
  ].join(" · ");
}

export type Tone = "neutral" | "success" | "warning" | "danger";

export function exitTone(item: OrderExitItem): Tone {
  switch (item.verdict) {
    case "ended_intent":
      return "neutral";
    case "ending_pending":
      return "warning";
    case "no_successor":
      return "danger";
  }
}

export function changeTitle(item: OrderChangeItem): string {
  switch (item.kind) {
    case "rate_cost":
      return "Zmiana stawki kosztowej";
    case "rate_revenue":
      return "Zmiana stawki przychodowej";
    case "end_date":
      return "Zmiana daty końca zamówienia";
    case "additional_project":
      return "Dodatkowy projekt";
    case "order_continuation":
      return "Kontynuacja zamówienia";
    case "client_change":
      return "Zmiana klienta";
  }
}

/**
 * „od 01.09.2026 · koszt … · przychód …" — wspólny ogon nowych zamówień.
 * BEZ klienta i numeru zamówienia: te stoją w wierszu meta (i w osobnych
 * kolumnach arkusza), a powtórzone czytają się jak druga, inna wartość.
 */
function newOrderTail(item: OrderChangeItem): string {
  return (
    `od ${formatDay(item.effective_date)} · koszt ` +
    `${formatRate(item.rate_cost, item.rate_unit, item.currency)} · przychód ` +
    `${formatRate(item.rate_revenue, item.rate_unit, item.currency)}`
  );
}

function previousOrderLabel(item: OrderChangeItem): string {
  if (!item.previous_order_number) return "—";
  return `zam. ${item.previous_order_number} (do ${formatDay(item.previous_end_date)})`;
}

/** Opis zmiany: „152,00 zł/h → 170,00 zł/h" albo „31.12.2026 → bezterminowo". */
export function changeValue(item: OrderChangeItem): string {
  if (item.kind === "order_continuation") {
    return `po ${previousOrderLabel(item)} · ${newOrderTail(item)}`;
  }
  if (item.kind === "client_change") {
    return (
      `z: ${item.previous_client_name ?? "—"} · ${previousOrderLabel(item)} · ` +
      newOrderTail(item)
    );
  }
  if (item.kind === "additional_project") {
    const others = item.other_client_names.join(", ") || "—";
    return `${newOrderTail(item)} · równolegle u: ${others}`;
  }
  if (item.kind === "end_date") {
    const before = item.old_date ? formatDay(item.old_date) : "bezterminowo";
    const after = item.new_date ? formatDay(item.new_date) : "bezterminowo";
    return `${before} → ${after}`;
  }
  return (
    `${formatRate(item.old_amount, item.old_unit, item.currency)} → ` +
    `${formatRate(item.new_amount, item.new_unit, item.currency)}`
  );
}

const NEW_ORDER_KINDS = new Set<OrderChangeItem["kind"]>([
  "additional_project",
  "order_continuation",
  "client_change",
]);

export function changeMeta(item: OrderChangeItem): string {
  if (NEW_ORDER_KINDS.has(item.kind)) {
    // Nowe zamówienie nie ma wpisu w dzienniku — nie ma więc ani chwili
    // wprowadzenia, ani autora; wpisanie tu „system" byłoby zmyśleniem.
    return [item.client_name, `zam. ${item.order_number}`].join(" · ");
  }
  const who =
    item.author_name ?? (item.source === "system" ? "system" : "nieznany autor");
  return [
    item.client_name,
    `zam. ${item.order_number}`,
    formatMoment(item.occurred_at),
    who,
  ].join(" · ");
}

export function gapDetails(item: OrderGapItem): string {
  return [
    item.client_name,
    `zam. ${item.order_number}`,
    `zakończone ${formatDay(item.ended_on)}`,
    `brak od ${formatDay(item.detected_on)}`,
  ].join(" · ");
}

export function gapStatusLabel(item: OrderGapItem): string {
  if (item.status === "open") return "Brak zamówienia";
  const days = item.delay_days;
  const delay =
    days === null || days === undefined
      ? ""
      : days === 0
        ? " (w dniu wykrycia braku)"
        : ` (${days} ${days === 1 ? "dzień" : "dni"} po terminie)`;
  return `Uzupełnione z opóźnieniem: zam. ${item.resolved_order_number ?? "—"}${delay}`;
}

/** „3 osoby" / „1 osoba" / „5 osób" — do banera o brakach. */
export function peopleLabel(count: number): string {
  if (count === 1) return "1 osoba ma";
  const lastTwo = count % 100;
  const last = count % 10;
  if (last >= 2 && last <= 4 && !(lastTwo >= 12 && lastTwo <= 14)) {
    return `${count} osoby mają`;
  }
  return `${count} osób ma`;
}
