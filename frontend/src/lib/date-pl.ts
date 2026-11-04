/**
 * Data w formacie DD.MM.RRRR — z zerem wiodącym w dniu i miesiącu.
 *
 * `Intl.DateTimeFormat("pl-PL")` daje „3.09.2026" (dzień bez zera), a surowa
 * wartość z API „2026-09-03". Obok siebie na jednym ekranie czytały się jak
 * dwa różne formaty. Data kalendarzowa `RRRR-MM-DD` jest składana z cyfr, BEZ
 * `new Date(...)`: tamto liczy północ UTC i w strefie za UTC cofa dzień.
 * Wartość z czasem (`created_at`) idzie przez lokalną datę przeglądarki.
 */
const DATE_ONLY = /^(\d{4})-(\d{2})-(\d{2})$/;

export function formatIsoDatePl(value: string | null | undefined): string {
  if (!value) return "—";
  const match = DATE_ONLY.exec(value.trim());
  if (match) return `${match[3]}.${match[2]}.${match[1]}`;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(date.getDate())}.${pad(date.getMonth() + 1)}.${date.getFullYear()}`;
}

/** „DD.MM.RRRR GG:MM" w lokalnej strefie przeglądarki. */
export function formatDateTimePl(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(date.getDate())}.${pad(date.getMonth() + 1)}.${date.getFullYear()} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

// ── Krótkie daty, dni tygodnia i miesiące (17.10.2026) ──────────────────────
// Ekrany „Ludzi”, opieki, sprzętu i spraw miały po kilka własnych kopii
// („5.11” obok „05.11”, „pn” obok „pon”). Jedna lista skrótów, jedna lista
// miesięcy, zawsze z zerem wiodącym; data kalendarzowa składana z cyfr.

/** Skróty dni tygodnia od poniedziałku (indeks jak `weekday()` w Pythonie). */
export const WEEKDAYS_PL = ["pon", "wt", "śr", "czw", "pt", "sob", "nd"] as const;

/** Nazwy miesięcy w mianowniku, małą literą. */
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

export interface YearMonth {
  year: number;
  month: number;
}

/** „05.11” — dzień i miesiąc (data kalendarzowa albo chwila jak `formatIsoDatePl`). */
export function formatDayMonthPl(value: string | null | undefined): string {
  const full = formatIsoDatePl(value);
  return full === "—" ? full : full.slice(0, 5);
}

/** Dzień tygodnia daty „RRRR-MM-DD”: 0 = poniedziałek … 6 = niedziela. */
export function weekdayOfIso(iso: string): number {
  const [year, month, day] = iso.slice(0, 10).split("-").map(Number);
  const sunday0 = new Date(Date.UTC(year, month - 1, day)).getUTCDay();
  return (sunday0 + 6) % 7;
}

/** „pon 05.11” — skrót dnia tygodnia i data bez roku (dzień z pierwszych 10 znaków). */
export function formatWeekdayDayPl(value: string | null | undefined): string {
  const day = value?.trim().slice(0, 10);
  if (!day || !DATE_ONLY.test(day)) return "—";
  return `${WEEKDAYS_PL[weekdayOfIso(day)]} ${formatDayMonthPl(day)}`;
}

function toYearMonth(value: string | YearMonth): YearMonth {
  if (typeof value !== "string") return value;
  const [year, month] = value.split("-").map(Number);
  return { year, month };
}

/** „listopad 2026” — z „2026-11” albo `{ year, month }`. */
export function monthYearPl(value: string | YearMonth): string {
  const { year, month } = toYearMonth(value);
  return `${MONTHS_PL[month - 1] ?? ""} ${year}`;
}

/** „Listopad 2026” — nagłówek miesiąca. */
export function monthTitlePl(value: string | YearMonth): string {
  const text = monthYearPl(value);
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** Miesiąc obok: `shiftMonth("2026-12", 1)` → „2027-01”, `{ year, month }` → ten sam kształt. */
export function shiftMonth(value: string, delta: number): string;
export function shiftMonth(value: YearMonth, delta: number): YearMonth;
export function shiftMonth(value: string | YearMonth, delta: number): string | YearMonth {
  const { year, month } = toYearMonth(value);
  const index = year * 12 + (month - 1) + delta;
  const shifted = { year: Math.floor(index / 12), month: (index % 12) + 1 };
  if (typeof value !== "string") return shifted;
  return `${shifted.year}-${String(shifted.month).padStart(2, "0")}`;
}

const MOMENT_PL = new Intl.DateTimeFormat("pl-PL", {
  timeZone: "Europe/Warsaw",
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

/**
 * Chwila z serwera (UTC) w czasie firmy: „16.10.2026, 05:31”. W odróżnieniu
 * od `formatDateTimePl` (strefa przeglądarki) zawsze Europe/Warsaw.
 */
export function formatMomentPl(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : MOMENT_PL.format(date);
}
