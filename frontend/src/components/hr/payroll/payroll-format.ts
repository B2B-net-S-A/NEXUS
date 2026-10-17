// Formatowanie Płac: kwoty po polsku, miesiące, statusy premii i timesheetów.
// Czyste funkcje — testowane bez renderu (`__tests__/payroll-format.test.ts`).

import type { StatusDotTone } from "@/components/ds/StatusDot";
import type {
  BonusCategory,
  BonusRow,
  BonusStatus,
  Currency,
  TimesheetStatus,
} from "@/lib/api/hr-payroll";

export const MONTHS_PL = [
  "styczeń",
  "luty",
  "marzec",
  "kwiecień",
  "maj",
  "czerwiec",
  "lipiec",
  "sierpień",
  "wrzesień",
  "październik",
  "listopad",
  "grudzień",
] as const;

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

const CURRENCY_SUFFIX: Record<string, string> = { PLN: "zł", EUR: "EUR", USD: "USD" };

/** „1 234,50 zł” — kwota z tekstu dziesiętnego; brak = „—”. */
export function formatMoney(
  value: string | number | null | undefined,
  currency: string = "PLN",
): string {
  if (value == null || value === "") return "—";
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  const amount = number.toLocaleString("pl-PL", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return `${amount} ${CURRENCY_SUFFIX[currency] ?? currency}`;
}

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

export function monthLabel(year: number, month: number): string {
  return `${MONTHS_PL[month - 1] ?? ""} ${year}`;
}

export function capitalize(text: string): string {
  return text ? text[0].toUpperCase() + text.slice(1) : text;
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

/** Dziś w kalendarzu firmy (Europe/Warsaw) jako „RRRR-MM-DD”. */
export function warsawToday(now: Date = new Date()): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Europe/Warsaw",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(now);
}

/** Bieżący miesiąc (Warszawa) jako „RRRR-MM” — wartość pola `type="month"`. */
export function warsawMonth(now: Date = new Date()): string {
  return warsawToday(now).slice(0, 7);
}

/** „2026-09-30” → „30.09.2026” (bez strefy czasowej — data kalendarzowa). */
export function formatDay(value: string | null | undefined): string {
  if (!value) return "—";
  const [year, month, day] = value.slice(0, 10).split("-");
  if (!year || !month || !day) return "—";
  return `${day}.${month}.${year}`;
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

export const TIMESHEET_LABELS: Record<TimesheetStatus, string> = {
  draft: "szkic",
  submitted: "czeka na akceptację",
  approved: "zaakceptowany",
};

export function timesheetLabel(status: TimesheetStatus | null, required: boolean): string {
  if (status) return TIMESHEET_LABELS[status];
  return required ? "nie wysłany" : "bez obowiązku";
}

export function timesheetTone(status: TimesheetStatus | null, required: boolean): StatusDotTone {
  if (status === "approved") return "success";
  if (status === "submitted") return "warning";
  return required ? "danger" : "neutral";
}

/** Status premii dla osoby: „liczy się do 30.09”, „czeka na zatwierdzenie”… */
export function bonusStateLabel(bonus: Pick<BonusRow, "status" | "eligible" | "eligible_on">): string {
  if (bonus.status === "proposed") {
    if (bonus.eligible === false && bonus.eligible_on) {
      return `liczy się do ${formatDay(bonus.eligible_on).slice(0, 5)}`;
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
