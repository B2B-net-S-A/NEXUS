// Formatowanie Płac: sumy kwot, statusy premii i timesheetów. Kwoty, daty
// i miesiące z `@/lib/money` i `@/lib/date-pl` (jeden format w całej aplikacji).
// Czyste funkcje — testowane bez renderu (`__tests__/payroll-format.test.ts`).

import type { InlineStat } from "@/components/ds/InlineStats";
import type { StatusDotTone } from "@/components/ds/StatusDot";
import { STATUS_TONE } from "@/components/hr/time/time-format";
import type {
  BonusCategory,
  BonusRow,
  BonusStatus,
  Currency,
  PayrollMonthDetail,
  RateRow,
  TimesheetStatus,
} from "@/lib/api/hr-payroll";
import { TIMESHEET_STATUS_LABELS } from "@/lib/api/hr-time";
import { formatDayMonthPl } from "@/lib/date-pl";
import { formatMoney } from "@/lib/money";
import { warsawToday } from "@/lib/warsaw-date";

export const CURRENCIES: Currency[] = ["PLN", "EUR", "USD"];

export const CATEGORY_LABELS: Record<BonusCategory, string> = {
  sales: "Sprzedaż",
  delivery_lead: "Delivery Lead",
  recruiter: "Rekruter",
  custom: "Inna",
  league: "Liga",
};

/** Kategorie do ręcznej premii (Liga powstaje z wyników rywalizacji). */
export const MANUAL_CATEGORIES: BonusCategory[] = [
  "custom",
  "sales",
  "delivery_lead",
  "recruiter",
];

export const EMPLOYMENT_LABELS: Record<string, string> = {
  uop: "UoP",
  b2b: "B2B",
  zlecenie: "Zlecenie",
};

/** Sumy per waluta w jednej linii: „12 345,00 zł · 100,00 EUR”. */
export function formatTotals(totals: Record<string, string> | undefined): string {
  const entries = Object.entries(totals ?? {}).filter(([, value]) => Number(value) !== 0);
  if (entries.length === 0) return "—";
  return entries.map(([currency, value]) => formatMoney(value, currency)).join(" · ");
}

/** „168” / „7,5” — godziny bez zbędnych zer. */
export function formatHours(value: string | number | null | undefined): string {
  if (value == null || value === "") return "—";
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  return number.toLocaleString("pl-PL", { maximumFractionDigits: 2 });
}

/** Segment adresu `/people/payroll/2026-09`. */
export function ymSegment(year: number, month: number): string {
  return `${year}-${String(month).padStart(2, "0")}`;
}

export function parseYm(segment: string | undefined | null): { year: number; month: number } | null {
  const match = /^(\d{4})-(\d{2})$/.exec(segment ?? "");
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  if (year < 2020 || year > 2100 || month < 1 || month > 12) return null;
  return { year, month };
}

/** Bieżący miesiąc (Warszawa) jako „RRRR-MM” — wartość pola `type="month"`. */
export function warsawMonth(now: Date = new Date()): string {
  return warsawToday(now).slice(0, 7);
}

export const BONUS_STATUS_LABELS: Record<BonusStatus, string> = {
  proposed: "propozycja",
  assigned: "przyznana",
  cancelled: "anulowana",
};

export const BONUS_STATUS_TONE: Record<BonusStatus, StatusDotTone> = {
  proposed: "info",
  assigned: "success",
  cancelled: "neutral",
};

/**
 * Status timesheetu osoby w Płacach — słownik i kolory te same co w „Moim
 * miesiącu” i „Moim zespole”; osoba bez obowiązku timesheetu: „bez obowiązku”.
 */
export function timesheetLabel(status: TimesheetStatus | null, required: boolean): string {
  if (status) return TIMESHEET_STATUS_LABELS[status].toLowerCase();
  return required ? TIMESHEET_STATUS_LABELS.missing.toLowerCase() : "bez obowiązku";
}

export function timesheetTone(status: TimesheetStatus | null, required: boolean): StatusDotTone {
  if (status) return STATUS_TONE[status];
  return required ? STATUS_TONE.missing : "neutral";
}

/** Status premii dla osoby: „liczy się do 30.09”, „czeka na zatwierdzenie”… */
export function bonusStateLabel(bonus: Pick<BonusRow, "status" | "eligible" | "eligible_on">): string {
  if (bonus.status === "proposed") {
    if (bonus.eligible === false && bonus.eligible_on) {
      return `liczy się do ${formatDayMonthPl(bonus.eligible_on)}`;
    }
    return "czeka na zatwierdzenie";
  }
  return BONUS_STATUS_LABELS[bonus.status];
}

/**
 * Powód anulowania premii dla osoby. Automat anuluje z kodem (premia nie
 * znika bez śladu — etap 2, D2), ręczne anulowanie to „manual”.
 */
export function cancelReasonLabel(
  reason: string | null | undefined,
  requiredDays = 21,
): string | null {
  switch (reason) {
    case "contract_ended":
      return `kontrakt zakończony przed ${requiredDays}. dniem roboczym`;
    case "contract_void":
      return "kontrakt unieważniony";
    case "contract_deleted":
      return "kontrakt usunięty";
    case "rule_no_longer_applies":
      return "zmieniły się warunki premii";
    case "manual":
      return "anulowana przez Płace albo przełożonego";
    default:
      return null;
  }
}

/** Procent paska „X z 21 dni roboczych” (0–100). */
export function progressPercent(elapsed: number | null | undefined, required: number | undefined): number {
  if (!required || required <= 0 || elapsed == null) return 0;
  return Math.max(0, Math.min(100, Math.round((elapsed / required) * 100)));
}

/** „Placement” albo opis premii — pierwsza linia komórki. */
export function bonusTitle(bonus: Pick<BonusRow, "description" | "category_label">): string {
  return bonus.description?.trim() || bonus.category_label;
}

/** Kwota z pola formularza („1 234,5”) → tekst dziesiętny dla API albo `null`. */
export function parseAmount(raw: string): string | null {
  const cleaned = raw.replace(/\s/g, "").replace(",", ".");
  if (!/^\d+(\.\d{1,2})?$/.test(cleaned)) return null;
  return cleaned;
}

/**
 * Komunikat po zapisie stawki. Serwer zapisuje, ale ostrzega (rok bez
 * minimalnej stawki zlecenia albo stawka w innej walucie niż złoty, D7) —
 * ostrzeżenie doklejone, typ „info” (wzorzec `leaveToast`).
 */
export function rateToast(row?: Pick<RateRow, "warning"> | null): [string, "success" | "info"] {
  const warning = row?.warning?.trim();
  return warning ? [`Stawka zapisana. ${warning}`, "info"] : ["Stawka zapisana", "success"];
}

/** Liczby nad tabelą (czysta funkcja — test bez renderu). */
export function monthStats(detail: PayrollMonthDetail): InlineStat[] {
  const stats: InlineStat[] = [
    { id: "people", label: "osób", value: detail.stats.people },
    {
      id: "approved",
      label: "timesheetów zaakceptowanych",
      value: detail.stats.timesheets_approved,
    },
    { id: "submitted", label: "czeka na akceptację", value: detail.stats.timesheets_submitted },
    { id: "missing", label: "nie wysłanych", value: detail.stats.timesheets_missing },
    { id: "proposals", label: "premie do decyzji", value: detail.stats.proposals },
  ];
  if (detail.totals) {
    stats.push({
      id: "totals",
      label: "razem do wypłaty",
      value: formatTotals(detail.totals),
      title: "Liczone są tylko zaakceptowane godziny i przyznane premie.",
    });
  }
  return stats;
}

/** Premie podzielone na sekcje ekranu. */
export function splitBonuses(bonuses: BonusRow[]): {
  toDecide: BonusRow[];
  assigned: BonusRow[];
  cancelled: number;
} {
  return {
    toDecide: bonuses.filter((b) => b.status === "proposed"),
    assigned: bonuses.filter((b) => b.status === "assigned"),
    cancelled: bonuses.filter((b) => b.status === "cancelled").length,
  };
}
