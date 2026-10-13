/**
 * „W bazie od” — kiedy osoba trafiła do naszej bazy (13.10.2026).
 *
 * Prośba rekrutera: świeże osoby są najlepsze, więc data wejścia do bazy ma
 * być widać od razu — w głowie panelu osoby, w „Notatkach i historii”,
 * w profilu przed telefonem i na karcie Tablicy. Datę i to, czy jest
 * dokładna, liczy serwer (`backend/app/services/candidate_added_date.py`):
 * osoba z Traffita bez daty dodania u źródła ma w bazie dzień importu, więc
 * ekran mówi wtedy „przed DD.MM.RRRR” i nie pokazuje „Nowy w bazie”.
 *
 * Dni liczymy w kalendarzu firmy (Europe/Warsaw), nie w dobach od znacznika.
 */

import { pluralPl } from "@/lib/plural-pl";
import { warsawDateOf, warsawToday } from "@/lib/warsaw-date";

/** Do ilu dni osoba jest „Nowa w bazie” (decyzja Artura 13.10.2026). */
export const NEW_IN_BASE_DAYS = 14;

const DAY_MS = 86_400_000;

export interface AddedToBaseInput {
  at: string | null | undefined;
  exact: boolean | null | undefined;
}

export interface AddedToBaseView {
  /** „03.10.2026”, a dla daty niedokładnej „przed 16.04.2026”. */
  dateLabel: string;
  /** „dziś”, „wczoraj”, „10 dni temu”, „2 mies. temu”, „6 lat temu”. */
  ageLabel: string;
  /** Dni kalendarzowe od wejścia do bazy; `null` dla daty niedokładnej. */
  days: number | null;
  exact: boolean;
  /** Pigułka „Nowy w bazie”: data dokładna i najwyżej 14 dni. */
  isNew: boolean;
}

function dayNumber(isoDay: string): number {
  return Date.parse(`${isoDay}T00:00:00Z`) / DAY_MS;
}

function formatDay(isoDay: string): string {
  const [year, month, day] = isoDay.split("-");
  return `${day}.${month}.${year}`;
}

/** „DD.MM.RRRR” dnia w kalendarzu firmy; wartość nieczytelna — `null`. */
export function formatWarsawDay(value: string | null | undefined): string | null {
  const day = warsawDateOf(value ?? null);
  return day ? formatDay(day) : null;
}

function fullMonthsBetween(fromDay: string, toDay: string): number {
  const [fy, fm, fd] = fromDay.split("-").map(Number);
  const [ty, tm, td] = toDay.split("-").map(Number);
  return ty * 12 + tm - (fy * 12 + fm) - (td < fd ? 1 : 0);
}

function ageLabel(days: number, fromDay: string, today: string): string {
  if (days <= 0) return "dziś";
  if (days === 1) return "wczoraj";
  const months = fullMonthsBetween(fromDay, today);
  if (months < 2) return `${days} dni temu`;
  if (months < 12) return `${months} mies. temu`;
  const years = Math.floor(months / 12);
  return `${years} ${pluralPl(years, "rok", "lata", "lat")} temu`;
}

/** „dziś”, „1 dzień”, „N dni” — treść pigułki „Nowy w bazie · …”. */
export function newInBaseDaysText(days: number): string {
  if (days <= 0) return "dziś";
  if (days === 1) return "1 dzień";
  return `${days} dni`;
}

export function addedToBaseView(
  input: AddedToBaseInput,
  now: Date = new Date(),
): AddedToBaseView | null {
  const day = warsawDateOf(input.at ?? null);
  if (!day) return null;
  const label = formatDay(day);
  if (!input.exact) {
    return {
      dateLabel: `przed ${label}`,
      ageLabel: "dokładnej daty nie znamy",
      days: null,
      exact: false,
      isNew: false,
    };
  }
  const today = warsawToday(now);
  const days = Math.max(0, Math.round(dayNumber(today) - dayNumber(day)));
  return {
    dateLabel: label,
    ageLabel: ageLabel(days, day, today),
    days,
    exact: true,
    isNew: days <= NEW_IN_BASE_DAYS,
  };
}

/** Dymek pigułki: data, kto dodał, skąd — człony, których nie znamy, nie wchodzą. */
export function addedToBaseTitle(
  view: AddedToBaseView,
  addedBy?: string | null,
  addedVia?: string | null,
): string {
  return [
    `W bazie od ${view.dateLabel}`,
    addedBy?.trim() ? `dodał(a) ${addedBy.trim()}` : null,
    addedVia?.trim() || null,
  ]
    .filter(Boolean)
    .join(" · ");
}
