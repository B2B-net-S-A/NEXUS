/**
 * Zdania karty „Z notatek rekruterów” na profilu kandydata (22.09.2026).
 *
 * Czyste funkcje nad odpowiedzią `GET /api/candidates/{id}/notes-facts` —
 * przeliczenia (MD ÷ 8, miesiąc ÷ 168) liczy serwer, tu tylko je opisujemy.
 */

import type { CandidateNotesFacts } from "@/lib/api";
import { formatWorkMode } from "@/lib/work-mode";

const PERIOD_LABELS: Record<string, string> = {
  h: "godz.",
  md: "dzień (MD)",
  month: "mies.",
};

const CONVERSION_NOTE: Record<string, string> = {
  md: "stawka za dzień ÷ 8 h",
  month: "stawka miesięczna ÷ 168 h",
};

export const CONTRACT_FORM_LABELS: Record<string, string> = {
  b2b: "B2B",
  uop: "Umowa o pracę",
  any: "B2B lub umowa o pracę",
};

const CONTRACT_TYPE_LABELS: Record<string, string> = {
  b2b: "B2B",
  uop: "UoP",
  zlecenie: "Zlecenie",
};

const NOTICE_UNITS: Record<string, [string, string, string]> = {
  days: ["dzień", "dni", "dni"],
  weeks: ["tydzień", "tygodnie", "tygodni"],
  months: ["miesiąc", "miesiące", "miesięcy"],
};

export function formatAmount(value: string | number | null | undefined): string | null {
  if (value == null || value === "") return null;
  const numeric = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(numeric)) return null;
  return new Intl.NumberFormat("pl-PL", {
    minimumFractionDigits: numeric % 1 === 0 ? 0 : 2,
    maximumFractionDigits: 2,
  }).format(numeric);
}

export function describeNotesRate(rate: NonNullable<CandidateNotesFacts["rate"]>): {
  original: string;
  hourly: string | null;
  conversion: string | null;
  warning: string | null;
} {
  const amount = formatAmount(rate.value) ?? String(rate.value);
  const currency = rate.currency ?? "waluta nieznana";
  const period = rate.period ? PERIOD_LABELS[rate.period] : "jednostka nieznana";
  const hourly = formatAmount(rate.hourly_pln);
  let warning: string | null = null;
  if (!hourly) {
    if (rate.note) {
      warning = rate.note;
    } else if (rate.currency && rate.currency !== "PLN") {
      warning = `Stawka w ${rate.currency} — przelicz ręcznie po kursie z dnia rozmowy.`;
    } else if (!rate.currency) {
      warning = "Notatka nie podaje waluty — sprawdź w notatce przed zapisem.";
    } else if (!rate.period) {
      warning = "Notatka nie mówi, czy to stawka za godzinę, dzień czy miesiąc.";
    } else {
      warning = "Kwota poza zakresem stawek godzinowych — sprawdź w notatce.";
    }
  }
  return {
    original: `${amount} ${currency} / ${period}`,
    hourly: hourly ? `${hourly} PLN netto/h` : null,
    conversion:
      hourly && rate.period && CONVERSION_NOTE[rate.period]
        ? CONVERSION_NOTE[rate.period]
        : null,
    warning,
  };
}

export function profileRateText(amount: string | null): string {
  const formatted = formatAmount(amount);
  return formatted ? `${formatted} PLN netto/h` : "nie uzupełniono";
}

export function notesWorkModeText(
  workMode: NonNullable<CandidateNotesFacts["work_mode"]>,
): { notes: string; profile: string } {
  return {
    notes: formatWorkMode(workMode.modes, workMode.max_onsite_days) ?? "—",
    profile:
      formatWorkMode(workMode.profile_modes, workMode.profile_max_onsite_days) ??
      "nie uzupełniono",
  };
}

export function contractTypesText(types: readonly string[]): string {
  if (types.length === 0) return "nie uzupełniono";
  return types.map((t) => CONTRACT_TYPE_LABELS[t] ?? t).join(", ");
}

function pluralIndex(n: number): 0 | 1 | 2 {
  if (n === 1) return 0;
  const lastTwo = n % 100;
  const last = n % 10;
  if (last >= 2 && last <= 4 && (lastTwo < 12 || lastTwo > 14)) return 1;
  return 2;
}

export function noticeText(
  period: number | null | undefined,
  unit: string | null | undefined,
): string | null {
  if (period == null) return null;
  const forms = NOTICE_UNITS[unit ?? "days"] ?? NOTICE_UNITS.days;
  return `${period} ${forms[pluralIndex(period)]} wypowiedzenia`;
}

export function formatIsoDate(value: string | null | undefined): string | null {
  if (!value) return null;
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (!match) return value;
  return `${match[3]}.${match[2]}.${match[1]}`;
}

/** Zdanie o dostępności: to, co da się zapisać, albo cytat z notatki. */
export function notesAvailabilityText(
  availability: NonNullable<CandidateNotesFacts["availability"]>,
): { notes: string; profile: string } {
  const parsed =
    availability.available_from != null
      ? `od ${formatIsoDate(availability.available_from)}`
      : noticeText(availability.notice_period, availability.notice_period_unit);
  const profileParts = [
    availability.profile_availability_date
      ? `od ${formatIsoDate(availability.profile_availability_date)}`
      : null,
    noticeText(
      availability.profile_notice_period,
      availability.profile_notice_period_unit,
    ),
  ].filter(Boolean);
  return {
    notes:
      parsed ??
      availability.raw ??
      availability.notice_period_text ??
      availability.available_from_text ??
      "—",
    profile: profileParts.length ? profileParts.join(" · ") : "nie uzupełniono",
  };
}

export function formatExtractedAt(value: string | null): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat("pl-PL", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  }).format(date);
}
