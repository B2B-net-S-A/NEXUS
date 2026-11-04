// Filtry „Ludzie → Kalendarz” (przebudowa 22.10.2026): chipy zakresu
// („Mój zespół”, „Wszyscy”, działy), chipy stanu („Dziś nieobecni”,
// „Zdalnie dziś”), szukanie, zakres i okres — wszystko w adresie, żeby link
// („Nieobecni dziś” z górnego paska) i odświeżenie otwierały ten sam widok.

import type { TeamCalendarPerson } from "@/lib/api/hr-leave";

/** Odczyt parametrów — `URLSearchParams` albo `useSearchParams()` z Next. */
type ParamReader = Pick<URLSearchParams, "get">;

import { matchesName, type CalendarView } from "./calendar-bars";

/** `team` — mój zespół (tylko koordynator), `all` — wszyscy, `dept:<nazwa>` — dział. */
export type CalendarScope = "team" | "all" | `dept:${string}`;

export type CalendarStatusChip = "absent" | "remote" | null;

export interface CalendarFilters {
  scope: CalendarScope;
  status: CalendarStatusChip;
  query: string;
  view: CalendarView;
  /** Pierwszy dzień miesiąca (widok miesiąca) albo dzień w oknie 2 tygodni. */
  anchor: string;
}

export interface CalendarDefaults {
  /** Koordynator ma domyślnie „Mój zespół”, reszta „Wszyscy”. */
  isManager: boolean;
  today: string;
}

/** Parametry adresu kalendarza. */
export const CALENDAR_PARAMS = {
  scope: "scope",
  department: "dept",
  status: "status",
  query: "q",
  view: "view",
  month: "month",
  from: "from",
} as const;

const MONTH_RE = /^\d{4}-(0[1-9]|1[0-2])$/;
const DAY_RE = /^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$/;

export function defaultScope(isManager: boolean): CalendarScope {
  return isManager ? "team" : "all";
}

export function defaultAnchor(view: CalendarView, today: string): string {
  return view === "month" ? `${today.slice(0, 7)}-01` : today;
}

/** Zakres z adresu; „Mój zespół” u kogoś bez zespołu przechodzi na domyślny. */
export function scopeFromParams(params: ParamReader, isManager: boolean): CalendarScope | null {
  const department = params.get(CALENDAR_PARAMS.department)?.trim();
  if (department) return `dept:${department}`;
  const scope = params.get(CALENDAR_PARAMS.scope);
  if (scope === "all") return "all";
  if (scope === "team") return isManager ? "team" : "all";
  return null;
}

export function statusFromParams(params: ParamReader): CalendarStatusChip {
  const status = params.get(CALENDAR_PARAMS.status);
  return status === "absent" || status === "remote" ? status : null;
}

/** Stan widoku z adresu; brak albo zła wartość = domyślna. */
export function filtersFromParams(
  params: ParamReader,
  { isManager, today }: CalendarDefaults,
): CalendarFilters {
  const view: CalendarView = params.get(CALENDAR_PARAMS.view) === "two_weeks" ? "two_weeks" : "month";
  const month = params.get(CALENDAR_PARAMS.month);
  const from = params.get(CALENDAR_PARAMS.from);
  const anchor =
    view === "month"
      ? month && MONTH_RE.test(month)
        ? `${month}-01`
        : defaultAnchor("month", today)
      : from && DAY_RE.test(from)
        ? from
        : defaultAnchor("two_weeks", today);
  return {
    scope: scopeFromParams(params, isManager) ?? defaultScope(isManager),
    status: statusFromParams(params),
    query: params.get(CALENDAR_PARAMS.query) ?? "",
    view,
    anchor,
  };
}

/**
 * Adres widoku: tylko to, co różni się od domyślnego; obce parametry adresu
 * (np. `?as=` harnessu) zostają. Zwraca `?…` albo samą ścieżkę (gdy wszystko
 * domyślne), do `replaceUrl` z `useUrlWriter`.
 */
export function filtersHref(
  filters: CalendarFilters,
  { isManager, today }: CalendarDefaults,
  location: { pathname: string; search: string },
): string {
  const params = new URLSearchParams(location.search);
  for (const name of Object.values(CALENDAR_PARAMS)) params.delete(name);
  if (filters.scope.startsWith("dept:")) {
    params.set(CALENDAR_PARAMS.department, filters.scope.slice(5));
  } else if (filters.scope !== defaultScope(isManager)) {
    params.set(CALENDAR_PARAMS.scope, filters.scope);
  }
  if (filters.status) params.set(CALENDAR_PARAMS.status, filters.status);
  if (filters.query.trim()) params.set(CALENDAR_PARAMS.query, filters.query);
  if (filters.view === "two_weeks") params.set(CALENDAR_PARAMS.view, "two_weeks");
  if (filters.anchor !== defaultAnchor(filters.view, today)) {
    if (filters.view === "month") params.set(CALENDAR_PARAMS.month, filters.anchor.slice(0, 7));
    else params.set(CALENDAR_PARAMS.from, filters.anchor);
  }
  const search = params.toString();
  return search ? `?${search}` : location.pathname;
}

/** Szukanie po imieniu albo stanowisku (pole „Imię, stanowisko”). */
export function matchesPerson(
  person: Pick<TeamCalendarPerson, "name" | "job_title">,
  query: string,
): boolean {
  if (!query.trim()) return true;
  return matchesName(person, query) || matchesName({ name: person.job_title ?? "" }, query);
}

/** Osoby w zakresie chipa działu (zakres „Mój zespół” ma własne zapytanie). */
export function inScope(people: readonly TeamCalendarPerson[], scope: CalendarScope): TeamCalendarPerson[] {
  if (!scope.startsWith("dept:")) return [...people];
  const department = scope.slice(5);
  return people.filter((person) => person.department === department);
}
