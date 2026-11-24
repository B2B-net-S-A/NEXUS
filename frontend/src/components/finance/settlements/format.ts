// Wspólne etykiety i formaty ekranów rozliczeń klientów.
import type { StatusDotTone } from "@/components/ds/StatusDot";
import type {
  AutoAcceptInfo,
  ClientAcceptanceState,
  ClientInvoiceDeadline,
  ClientInvoiceState,
  ContractorInvoiceState,
  IntegrationCostStatus,
  IntegrationUsage,
  KesuState,
  SettlementFilter,
  SettlementStatus,
} from "@/lib/api/client-settlements";
import { formatPlnDocument } from "@/lib/money";
import { countPl, pluralPl } from "@/lib/plural-pl";

export const STATUS: Record<SettlementStatus, { label: string; tone: StatusDotTone }> = {
  missing: { label: "Brak RCP", tone: "neutral" },
  checking: { label: "Do sprawdzenia", tone: "info" },
  ok: { label: "Bez uwag", tone: "info" },
  warnings: { label: "Z uwagami", tone: "warning" },
  needs_fix: { label: "Do poprawy", tone: "danger" },
  no_md: { label: "Brak MD", tone: "danger" },
  accepted: { label: "Przyjęte", tone: "success" },
};

/**
 * Stan RCP w wierszu: „Z uwagami” dzieli się na „Błąd” (reguła blokuje przyjęcie)
 * i „Uwaga” (Finanse mogą przyjąć na karcie osoby) — makiety 24.11.2026.
 */
export function statusLook(status: SettlementStatus, issueLevel?: "fail" | "warn" | null): { label: string; tone: StatusDotTone } {
  if (status === "warnings") return issueLevel === "fail" ? { label: "Błąd", tone: "danger" } : { label: "Uwaga", tone: "warning" };
  if (status === "no_md") return { label: "Zamówienie bez MD", tone: "danger" };
  if (status === "checking") return { label: "Nieodczytany plik", tone: "info" };
  return STATUS[status];
}

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
  awaiting_client: { label: "Czeka na klienta", tone: "warning" },
  awaiting_t4t: { label: "Czeka na T4T", tone: "warning" },
};

/** Akceptacja klienta po wysyłce KCP (E6.5): drugi stan w kolumnie RCP. */
export const CLIENT_ACCEPTANCE: Record<ClientAcceptanceState, { label: string; tone: StatusDotTone } | null> = {
  none: null,
  to_send: { label: "Klient: do wysłania", tone: "info" },
  sent: { label: "Klient: wysłana, czeka", tone: "warning" },
  accepted: { label: "Klient: zaakceptowana", tone: "success" },
};

/** „2026-11-10T10:30:00+01:00” → „10.11 10:30” (godzina z zapisu, czas firmy). */
export function dayTime(value: string | null | undefined): string {
  const day = shortDay(value);
  const time = value && value.length >= 16 ? value.slice(11, 16) : "";
  return time ? `${day} ${time}` : day;
}

/**
 * Pasek nad tabelą miesiąca przy regule „Przyjmuj RCP bez uwag automatycznie”.
 * `today` i `info.from` to daty RRRR-MM-DD w kalendarzu firmy.
 */
export function autoAcceptText(info: AutoAcceptInfo, today: string): string {
  const when = info.from <= today ? "przy najbliższym porannym biegu (dzień roboczy, od 7:00)" : `od ${shortDay(info.from)} rano`;
  if (info.count === 0) {
    return `Automat przyjmuje RCP bez uwag od ${info.workday}. dnia roboczego po miesiącu. Teraz nie ma czego przyjąć.`;
  }
  const mod10 = info.count % 10;
  const mod100 = info.count % 100;
  const few = mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14);
  return `${info.count} RCP bez uwag ${few ? "przyjmą się same" : "przyjmie się samo"} ${when}. RCP odesłane „Do poprawy” przyjmujecie ręcznie.`;
}

/** „2026-11-10T10:30:00+01:00” → „10.11”. */
export function shortDay(value: string | null | undefined): string {
  if (!value || value.length < 10) return "";
  return `${value.slice(8, 10)}.${value.slice(5, 7)}`;
}

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

/** Ostrzeżenie o terminie faktury do klienta z T4T (art. 106i: 15. dnia następnego miesiąca). */
export function deadlineText(d: ClientInvoiceDeadline): string {
  const who = `${countPl(d.missing, "osoba", "osoby", "osób")} bez zatwierdzonych godzin w T4T`;
  const day = shortDay(d.date);
  if (d.overdue) {
    return `Termin faktury minął ${day} (${countPl(-d.days_left, "dzień", "dni", "dni")} temu): ${who}.`;
  }
  if (d.days_left === 0) return `Dziś termin faktury (${day}): ${who}.`;
  return `Do terminu faktury ${day} ${pluralPl(d.days_left, "został", "zostały", "zostało")} ${countPl(d.days_left, "dzień", "dni", "dni")}: ${who}.`;
}
