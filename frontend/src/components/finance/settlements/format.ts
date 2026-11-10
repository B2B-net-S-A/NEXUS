// Wspólne etykiety i formaty ekranów rozliczeń klientów.
import type { StatusDotTone } from "@/components/ds/StatusDot";
import type {
  ClientInvoiceState,
  ContractorInvoiceState,
  SettlementFilter,
  SettlementStatus,
} from "@/lib/api/client-settlements";
import { formatPlnDocument } from "@/lib/money";

export const STATUS: Record<SettlementStatus, { label: string; tone: StatusDotTone }> = {
  missing: { label: "Brak RCP", tone: "neutral" },
  checking: { label: "Do sprawdzenia", tone: "info" },
  ok: { label: "Bez uwag", tone: "info" },
  warnings: { label: "Z uwagami", tone: "warning" },
  needs_fix: { label: "Do poprawy", tone: "danger" },
  no_md: { label: "Brak MD", tone: "danger" },
  accepted: { label: "Przyjęte", tone: "success" },
};

export const CONTRACTOR_INVOICE: Record<ContractorInvoiceState, { label: string; tone: StatusDotTone }> = {
  none: { label: "Po przyjęciu RCP", tone: "neutral" },
  can_issue: { label: "Może wystawić", tone: "info" },
  in_ksef: { label: "W KSeF", tone: "success" },
  differs: { label: "Inna kwota", tone: "danger" },
  nip_check: { label: "NIP do zatwierdzenia", tone: "warning" },
};

export const CLIENT_INVOICE: Record<ClientInvoiceState, { label: string; tone: StatusDotTone }> = {
  waiting: { label: "Czeka", tone: "neutral" },
  ready: { label: "Do wystawienia", tone: "info" },
  issued: { label: "Wystawiona", tone: "success" },
};

export const FILTERS: { key: SettlementFilter; label: string }[] = [
  { key: "todo", label: "Do zrobienia" },
  { key: "missing", label: "Brak RCP" },
  { key: "needs_fix", label: "U konsultanta" },
  { key: "accepted", label: "Przyjęte" },
  { key: "all", label: "Wszyscy" },
];

/** Filtr listy po stanie — to samo, co liczy serwer w `counts`. */
export function matchesFilter(filter: SettlementFilter, status: SettlementStatus, differs: boolean): boolean {
  switch (filter) {
    case "todo":
      return status === "checking" || status === "ok" || status === "warnings" || status === "no_md" || differs;
    case "missing":
      return status === "missing";
    case "needs_fix":
      return status === "needs_fix";
    case "accepted":
      return status === "accepted";
    default:
      return true;
  }
}

export function pln(value: string | null | undefined): string {
  return formatPlnDocument(value) ?? "–";
}

export function mdText(value: string | null | undefined): string {
  if (value == null) return "–";
  const n = Number(value);
  return Number.isFinite(n) ? n.toLocaleString("pl-PL", { maximumFractionDigits: 3 }) : "–";
}

export function pctText(value: string | null | undefined): string | null {
  if (value == null) return null;
  const n = Number(value);
  return Number.isFinite(n) ? `${n.toLocaleString("pl-PL", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%` : null;
}

const MONTHS = [
  "styczeń", "luty", "marzec", "kwiecień", "maj", "czerwiec",
  "lipiec", "sierpień", "wrzesień", "październik", "listopad", "grudzień",
];

/** „2026-10” → „październik 2026”. */
export function monthLabel(month: string): string {
  const [y, m] = month.split("-").map(Number);
  return `${MONTHS[(m ?? 1) - 1]} ${y}`;
}

/** Ostatnie `count` miesięcy wstecz od `today` (YYYY-MM-DD), najnowszy pierwszy. */
export function recentMonths(today: string, count = 6): string[] {
  const [y, m] = today.split("-").map(Number);
  return Array.from({ length: count }, (_, i) => {
    const idx = y * 12 + (m - 1) - i;
    return `${Math.floor(idx / 12)}-${String((idx % 12) + 1).padStart(2, "0")}`;
  });
}

/** Bieżący miesiąc i `count - 1` kolejnych: od kiedy mogą działać nowe reguły. */
export function nextMonths(today: string, count = 3): string[] {
  const [y, m] = today.split("-").map(Number);
  return Array.from({ length: count }, (_, i) => {
    const idx = y * 12 + (m - 1) + i;
    return `${Math.floor(idx / 12)}-${String((idx % 12) + 1).padStart(2, "0")}`;
  });
}

/** Rozliczamy miesiąc zamknięty: domyślnie poprzedni. */
export function defaultMonth(today: string): string {
  return recentMonths(today, 2)[1];
}
