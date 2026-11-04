// Słowa i liczby zakładki „Faktury z KSeF” (M5) i karty stanu KSeF — czyste
// funkcje, testowane bez DOM (`__tests__/ksef-format.test.ts`). Kwoty
// z `@/lib/money`, chwile w czasie firmy z `@/lib/date-pl`.

import type { InlineStat } from "@/components/ds/InlineStats";
import type { StatusDotTone } from "@/components/ds/StatusDot";
import { SETTLEMENT_TONE } from "@/components/hr/me/settlement-format";
import type {
  KsefHealth,
  KsefInvoice,
  KsefInvoiceList,
  KsefRunCounts,
  KsefRunKind,
  KsefStatus,
  WhiteListMode,
} from "@/lib/api/hr-ksef";
import type { SettlementStatus } from "@/lib/api/hr-settlements";
import { formatMomentPl, monthYearPl } from "@/lib/date-pl";
import { countPl } from "@/lib/plural-pl";

/** Limit PDF-u faktury spoza KSeF — ten sam co `pdf_store.MAX_PDF_BYTES`. */
export const MAX_INVOICE_PDF_BYTES = 10 * 1024 * 1024;

export const HEALTH_TONE: Record<KsefHealth, StatusDotTone> = {
  disabled: "neutral",
  healthy: "success",
  degraded: "warning",
};

export const RUN_KIND_LABELS: Record<KsefRunKind, string> = {
  auto: "co godzinę",
  manual: "„Pobierz teraz”",
  refetch: "„Pobierz ponownie okres”",
};

export const WHITE_LIST_MODE_LABELS: Record<WhiteListMode, string> = {
  off: "wyłączona",
  simulate: "symulacja (fikcyjne wpisy)",
  test: "środowisko testowe MF",
  live: "wykaz MF",
};

/** Stan dopasowania w wierszu: z rozliczeniem — jego stan, bez — „do przypisania”. */
export const MATCH_LABELS: Record<SettlementStatus, string> = {
  awaiting_document: "czeka na fakturę",
  mismatch: "rozbieżność",
  ready: "zgodna",
  approved: "zatwierdzona do zapłaty",
  paid: "opłacono",
  cancelled: "anulowane",
};

export function matchText(invoice: KsefInvoice): string {
  if (invoice.match_status === "ignored") return "pominięta";
  if (invoice.match_status === "unmatched" || !invoice.settlement) return "do przypisania";
  const status = invoice.settlement.status as SettlementStatus;
  return MATCH_LABELS[status] ?? invoice.settlement.status;
}

export function matchTone(invoice: KsefInvoice): StatusDotTone {
  if (invoice.match_status === "ignored") return "neutral";
  if (invoice.match_status === "unmatched" || !invoice.settlement) return "warning";
  return SETTLEMENT_TONE[invoice.settlement.status as SettlementStatus] ?? "neutral";
}

/**
 * Dopasowaną fakturę Płace mogą przenieść do innego miesiąca albo pominąć,
 * dopóki rozliczenie nie jest opłacone (serwer odpina ją i przelicza
 * rozliczenie; przy opłaconym zostaje jako dowód zapłaty — 409).
 */
export function canDetach(invoice: KsefInvoice): boolean {
  return (
    invoice.match_status === "matched" &&
    invoice.settlement !== null &&
    invoice.settlement.status !== "paid" &&
    invoice.settlement.status !== "cancelled"
  );
}

/** „Anna P. · październik” — osoba i miesiąc rozliczenia w kolumnie dopasowania. */
export function matchPerson(invoice: KsefInvoice): string | null {
  const name = invoice.user?.name?.trim();
  const short = name ? shortName(name) : null;
  const settlement = invoice.settlement;
  const month = settlement
    ? monthYearPl({ year: settlement.year, month: settlement.month }).split(" ")[0]
    : null;
  return [short, month].filter(Boolean).join(" · ") || null;
}

/** „Anna Przykładowa” → „Anna P.” */
export function shortName(name: string): string {
  const [first, ...rest] = name.split(/\s+/);
  const last = rest.at(-1);
  return last ? `${first} ${last.charAt(0)}.` : first;
}

/** Numer KSeF bez NIP-u z przodu: „…-20261105-0B91E4C2A7D8-1F”. */
export function shortKsefNumber(number: string | null): string {
  if (!number) return "—";
  return /^\d{10}-/.test(number) ? `…${number.slice(10)}` : number;
}

/** „777…7777” — NIP skrócony w wąskiej kolumnie (pełny w dymku). */
export function maskNip(nip: string): string {
  return /^\d{10}$/.test(nip) ? `${nip.slice(0, 3)}…${nip.slice(-4)}` : nip;
}

export function invoiceStats(
  list: KsefInvoiceList,
  monthLabel: string,
  status: KsefStatus | undefined,
): InlineStat[] {
  const stats: InlineStat[] = [
    { id: "total", label: `od zespołu · ${monthLabel}`, value: list.counts.total },
    { id: "matched", label: "dopasowane same", value: list.counts.matched },
    { id: "unmatched", label: "do przypisania", value: list.counts.unmatched },
  ];
  if (list.counts.ignored) {
    stats.push({ id: "ignored", label: "pominięte", value: list.counts.ignored });
  }
  if (status?.enabled) {
    stats.push({
      id: "schedule",
      label: "pobieranie",
      value: "co godzinę",
      title: status.last_run_at ? `Ostatnie: ${formatMomentPl(status.last_run_at)}` : undefined,
    });
  }
  return stats;
}

/** Zdanie po „Pobierz teraz” / „Pobierz ponownie okres”. */
export function runSummary(result: KsefRunCounts & { partial?: boolean }): string {
  const parts: string[] = [];
  const saved = result.saved ?? 0;
  parts.push(
    saved > 0
      ? `Nowe faktury od zespołu: ${saved}`
      : "Brak nowych faktur od zespołu",
  );
  if (result.matched) parts.push(`dopasowane: ${result.matched}`);
  if (result.skipped) {
    parts.push(`${countPl(result.skipped, "faktura", "faktury", "faktur")} dostawców pominięte`);
  }
  if (result.pending) parts.push(`w kolejce do ponownego pobrania: ${result.pending}`);
  if (result.failed) parts.push(`nie dało się odczytać: ${result.failed}`);
  const text = parts.join(" · ");
  return result.partial ? `${text}. Reszta w następnym pobraniu (limit KSeF).` : `${text}.`;
}

/** Ostatnie pobranie w jednym zdaniu (nagłówek zakładki). */
export function lastRunLine(status: KsefStatus): string {
  if (!status.last_run_at) return "Jeszcze nie pobierano faktur.";
  const kind = status.last_run_kind ? ` (${RUN_KIND_LABELS[status.last_run_kind]})` : "";
  return `Ostatnie pobranie: ${formatMomentPl(status.last_run_at)}${kind}`;
}

/** „Pobierz teraz” ma sens tylko przy włączonej integracji i bez blokady 429. */
export function canFetch(status: KsefStatus | undefined): boolean {
  return Boolean(status?.enabled && !status.blocked_until);
}
