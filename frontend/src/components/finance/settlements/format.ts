// Wspólne etykiety i formaty ekranów rozliczeń klientów.
import type { StatusDotTone } from "@/components/ds/StatusDot";
import type {
  ClientInvoiceState,
  ContractorInvoiceState,
  IntegrationCostStatus,
  IntegrationUsage,
  KesuState,
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
  extra_pending: { label: "Czeka na dodatek", tone: "warning" },
};

export const CLIENT_INVOICE: Record<ClientInvoiceState, { label: string; tone: StatusDotTone }> = {
  waiting: { label: "Czeka", tone: "neutral" },
  ready: { label: "Do wystawienia", tone: "info" },
  issued: { label: "Wystawiona", tone: "success" },
  awaiting_signature: { label: "Czeka na podpis", tone: "warning" },
};

export const KESU: Record<KesuState, { label: string; tone: StatusDotTone }> = {
  to_company: { label: "Do podpisu spółki", tone: "info" },
  awaiting_client: { label: "Czeka na podpis klienta", tone: "warning" },
  signed: { label: "Oba podpisy", tone: "success" },
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

/** Kwota w walucie faktury klienta: „1 234,50 EUR”, dla zł jak `pln`. */
export function money(value: string | null | undefined, currency: string | null | undefined): string {
  const code = (currency || "PLN").toUpperCase();
  if (code === "PLN") return pln(value);
  const text = formatPlnDocument(value);
  return text == null ? "–" : `${text.slice(0, -3)} ${code}`;
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

/** Koszt integracji (E5.1): wpisują Finanse, przyjmuje DL klienta. */
export const INTEGRATION_STATUS: Record<IntegrationCostStatus, { label: string; tone: StatusDotTone }> = {
  pending: { label: "Czeka na DL-a", tone: "warning" },
  approved: { label: "Zgoda DL-a", tone: "success" },
  rejected: { label: "Odrzucony", tone: "neutral" },
};

/** „Wykorzystano 1 500 zł z 2 000 zł w 2026 · czeka 400 zł”. */
export function integrationUsageText(usage: IntegrationUsage): string {
  const parts = [
    usage.limit
      ? `Wykorzystano ${pln(usage.approved)} z ${pln(usage.limit)} w ${usage.year}`
      : `Wykorzystano ${pln(usage.approved)} w ${usage.year} (bez limitu)`,
  ];
  if (Number(usage.pending) > 0) parts.push(`czeka ${pln(usage.pending)}`);
  if (usage.remaining !== null) parts.push(`zostało ${pln(usage.remaining)}`);
  return parts.join(" · ");
}
