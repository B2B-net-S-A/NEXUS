// „Kalendarz zespołu” wg makiety z 19.10.2026 — czyste funkcje: okno dni
// (2 tygodnie / miesiąc), ciągłe paski nieobecności, wiersz „Nieobecnych”
// (mapa cieplna), panel „W tym tygodniu nie ma” i „Najtrudniejszy dzień”.
//
// D6: etykieta paska to `label` z serwera — poza kręgiem zawsze
// „Nieobecność”; wnioski oczekujące serwer wysyła tylko kręgowi D6.

import type {
  CalendarAbsence,
  CalendarPresenceKind,
  TeamCalendar,
  TeamCalendarPerson,
} from "@/lib/api/hr-leave";
import { WEEKDAYS_PL, monthTitlePl, shiftMonth } from "@/lib/date-pl";

export type CalendarView = "two_weeks" | "month";

export type CalendarDay = TeamCalendar["days"][number];

/** „RRRR-MM-DD” + n dni (UTC, bez stref). */
export function addDays(iso: string, delta: number): string {
  const [year, month, day] = iso.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, day + delta)).toISOString().slice(0, 10);
}

/** Poniedziałek tygodnia, w którym leży dzień. */
export function mondayOf(iso: string): string {
  const [year, month, day] = iso.split("-").map(Number);
  const weekday = (new Date(Date.UTC(year, month - 1, day)).getUTCDay() + 6) % 7;
  return addDays(iso, -weekday);
}

function lastDayOfMonth(month: string): string {
  return addDays(`${shiftMonth(month, 1)}-01`, -1);
}

export interface CalendarWindow {
  start: string;
  end: string;
  /** Miesiące do pobrania (`GET /calendar?month=`) — jeden albo dwa. */
  months: string[];
}

/** Okno widoku: cały miesiąc kotwicy albo 14 dni od poniedziałku jej tygodnia. */
export function calendarWindow(view: CalendarView, anchor: string): CalendarWindow {
  if (view === "month") {
    const month = anchor.slice(0, 7);
    return { start: `${month}-01`, end: lastDayOfMonth(month), months: [month] };
  }
  const start = mondayOf(anchor);
  const end = addDays(start, 13);
  const months = [start.slice(0, 7), end.slice(0, 7)].filter(
    (month, index, all) => all.indexOf(month) === index,
  );
  return { start, end, months };
}

/** Kotwica po strzałce: miesiąc albo dwa tygodnie dalej/wcześniej. */
export function shiftAnchor(view: CalendarView, anchor: string, delta: -1 | 1): string {
  if (view === "month") return `${shiftMonth(anchor.slice(0, 7), delta)}-01`;
  return addDays(mondayOf(anchor), 14 * delta);
}

function dayMonth(iso: string): string {
  return `${Number(iso.slice(8, 10))}.${iso.slice(5, 7)}`;
}

/** „Październik 2026” albo „19.10 – 1.11.2026”. */
export function windowTitle(view: CalendarView, window: CalendarWindow): string {
  if (view === "month") return monthTitlePl(window.start.slice(0, 7));
  return `${dayMonth(window.start)} – ${dayMonth(window.end)}.${window.end.slice(0, 4)}`;
}

function absenceKey(absence: CalendarAbsence): string {
  return absence.id ?? `${absence.start_date}|${absence.end_date}|${absence.status}|${absence.half_day ?? ""}`;
}

/**
 * Złożenie miesięcy w jedno okno (widok 2 tygodni na przełomie miesięcy):
 * dni z okna, osoby po `user_id`, nieobecność obejmująca oba miesiące raz.
 */
export function mergeCalendars(
  parts: readonly TeamCalendar[],
  window: CalendarWindow,
): TeamCalendar | null {
  if (parts.length === 0) return null;
  const days = new Map<string, CalendarDay>();
  const people = new Map<number, TeamCalendarPerson>();
  for (const part of parts) {
    for (const day of part.days) {
      if (day.date >= window.start && day.date <= window.end) days.set(day.date, day);
    }
    for (const person of part.people) {
      const known = people.get(person.user_id);
      if (!known) {
        people.set(person.user_id, {
          ...person,
          absences: [...person.absences],
          presence: [...(person.presence ?? [])],
        });
        continue;
      }
      const seen = new Set(known.absences.map(absenceKey));
      for (const absence of person.absences) {
        if (!seen.has(absenceKey(absence))) known.absences.push(absence);
      }
      const marks = new Set((known.presence ?? []).map((item) => item.date));
      for (const item of person.presence ?? []) {
        if (!marks.has(item.date)) known.presence = [...(known.presence ?? []), item];
      }
    }
  }
  const first = parts[0];
  return {
    month: first.month,
    today: first.today,
    departments: first.departments,
    presence_shown: parts.some((part) => part.presence_shown),
    days: [...days.values()].sort((a, b) => a.date.localeCompare(b.date)),
    // Kolejność osób z pierwszego miesiąca, dopisani z drugiego na końcu (po nazwisku).
    people: [...people.values()].sort((a, b) => a.name.localeCompare(b.name, "pl")),
  };
}

export interface BarSegment {
  absence: CalendarAbsence;
  /** Indeks pierwszego dnia w oknie (0 = pierwsza kolumna dni). */
  startIndex: number;
  span: number;
  pending: boolean;
  half: boolean;
  /** Tekst na pasku (może być pusty przy jednym dniu). */
  label: string;
}

/** „5–8” w jednym miesiącu, „28.09–5.10” na przełomie. */
export function shortRange(start: string, end: string): string {
  if (start === end) return String(Number(start.slice(8, 10)));
  if (start.slice(0, 7) === end.slice(0, 7)) {
    return `${Number(start.slice(8, 10))}–${Number(end.slice(8, 10))}`;
  }
  return `${dayMonth(start)}–${dayMonth(end)}`;
}

/**
 * Ciągłe paski zamiast kafelka na dzień: jedna nieobecność = jeden pasek
 * od pierwszego do ostatniego dnia w oknie (także przez weekend).
 */
export function absenceSegments(
  absences: readonly CalendarAbsence[],
  days: readonly string[],
): BarSegment[] {
  if (days.length === 0) return [];
  const first = days[0];
  const last = days[days.length - 1];
  const segments: BarSegment[] = [];
  for (const absence of absences) {
    if (absence.end_date < first || absence.start_date > last) continue;
    const from = absence.start_date < first ? first : absence.start_date;
    const to = absence.end_date > last ? last : absence.end_date;
    const startIndex = days.indexOf(from);
    const endIndex = days.indexOf(to);
    if (startIndex < 0 || endIndex < startIndex) continue;
    const span = endIndex - startIndex + 1;
    const pending = absence.status === "pending";
    const half = absence.half_day !== null;
    const range = shortRange(absence.start_date, absence.end_date);
    const base = pending ? "wniosek" : absence.label.toLowerCase();
    const label = span >= 3 ? `${base} ${range}` : span === 2 ? range : half ? "½" : "";
    segments.push({ absence, startIndex, span, pending, half, label });
  }
  return segments.sort((a, b) => a.startIndex - b.startIndex);
}

/** Z / D na dniach bez paska nieobecności (zdalnie, delegacja). */
export function presenceMarks(
  person: TeamCalendarPerson,
  days: readonly string[],
  segments: readonly BarSegment[],
): { index: number; kind: CalendarPresenceKind }[] {
  const covered = new Set<number>();
  for (const segment of segments) {
    for (let index = segment.startIndex; index < segment.startIndex + segment.span; index += 1) {
      covered.add(index);
    }
  }
  const marks: { index: number; kind: CalendarPresenceKind }[] = [];
  for (const item of person.presence ?? []) {
    const index = days.indexOf(item.date);
    if (index >= 0 && !covered.has(index)) marks.push({ index, kind: item.kind });
  }
  return marks.sort((a, b) => a.index - b.index);
}

export interface AbsentCount {
  /** Osoby nieobecne (pół dnia = 0,5). */
  value: number;
  /** Wliczony wniosek, który czeka — „?” przy liczbie. */
  pending: boolean;
  text: string;
  /** Imiona i nazwiska nieobecnych (do podpowiedzi). */
  names: string[];
}

/** „½”, „1½”, „2”. */
export function formatCount(value: number): string {
  const whole = Math.floor(value);
  const half = value - whole >= 0.5;
  if (!half) return String(whole);
  return whole === 0 ? "½" : `${whole}½`;
}

/** Nieobecność osoby w dniu: zatwierdzona wygrywa z oczekującą. */
function absenceOn(person: TeamCalendarPerson, day: string): CalendarAbsence | null {
  let found: CalendarAbsence | null = null;
  for (const absence of person.absences) {
    if (day < absence.start_date || day > absence.end_date) continue;
    if (absence.status === "approved") return absence;
    found = found ?? absence;
  }
  return found;
}

/**
 * Wiersz „Nieobecnych” — dni robocze okna: ile osób nie ma (pół dnia = ½),
 * „?” gdy wliczony wniosek, który jeszcze czeka. Delegacja się nie liczy
 * (osoba pracuje, tylko poza biurem).
 */
export function absentCounts(
  people: readonly TeamCalendarPerson[],
  days: readonly CalendarDay[],
): Map<string, AbsentCount> {
  const counts = new Map<string, AbsentCount>();
  for (const day of days) {
    if (day.kind !== "work") continue;
    let value = 0;
    let pending = false;
    const names: string[] = [];
    for (const person of people) {
      const absence = absenceOn(person, day.date);
      if (!absence) continue;
      value += absence.half_day ? 0.5 : 1;
      if (absence.status === "pending") pending = true;
      names.push(person.name);
    }
    if (value > 0) {
      counts.set(day.date, { value, pending, text: `${formatCount(value)}${pending ? "?" : ""}`, names });
    }
  }
  return counts;
}

export type HeatLevel = "low" | "mid" | "high";

/** Natężenie komórki mapy cieplnej: 1 osoba, 2 osoby, 3 i więcej. */
export function heatLevel(value: number): HeatLevel {
  if (value <= 1) return "low";
  if (value <= 2) return "mid";
  return "high";
}

export interface HardestDay {
  date: string;
  count: AbsentCount;
}

/** Dzień z największą liczbą nieobecnych (od 2 osób), najwcześniejszy przy remisie. */
export function hardestDay(counts: ReadonlyMap<string, AbsentCount>): HardestDay | null {
  let best: HardestDay | null = null;
  for (const [date, count] of counts) {
    if (count.value < 2) continue;
    if (!best || count.value > best.count.value || (count.value === best.count.value && date < best.date)) {
      best = { date, count };
    }
  }
  return best;
}

export interface WeekAbsentee {
  user_id: number;
  name: string;
  text: string;
  pending: boolean;
  first: string;
}

function weekdayName(iso: string): string {
  const [year, month, day] = iso.split("-").map(Number);
  return WEEKDAYS_PL[(new Date(Date.UTC(year, month - 1, day)).getUTCDay() + 6) % 7];
}

/**
 * „W tym tygodniu nie ma” (pn–pt): nieobecność do kiedy albo dni tygodnia,
 * oczekujące z dopiskiem „wniosek czeka”, delegacja osobno. Bez rodzaju (D6).
 */
export function weekAbsentees(
  people: readonly TeamCalendarPerson[],
  monday: string,
  today: string,
): WeekAbsentee[] {
  const friday = addDays(monday, 4);
  const pivot = today > monday && today <= friday ? today : monday;
  const result: WeekAbsentee[] = [];
  for (const person of people) {
    const parts: string[] = [];
    let pending = false;
    let first = "9999-12-31";
    const absences = person.absences
      .filter((absence) => absence.end_date >= monday && absence.start_date <= friday)
      .sort((a, b) => a.start_date.localeCompare(b.start_date));
    for (const absence of absences) {
      const from = absence.start_date < monday ? monday : absence.start_date;
      if (from < first) first = from;
      let text: string;
      if (absence.start_date <= pivot) {
        text = absence.end_date <= friday
          ? `do ${weekdayName(absence.end_date)} ${dayMonth(absence.end_date)}`
          : `do ${dayMonth(absence.end_date)}`;
      } else {
        const to = absence.end_date > friday ? friday : absence.end_date;
        text = from === to ? weekdayName(from) : `${weekdayName(from)}–${weekdayName(to)}`;
      }
      if (absence.half_day) text += " (pół dnia)";
      if (absence.status === "pending") {
        text += " · wniosek czeka";
        pending = true;
      }
      parts.push(text);
    }
    const trips = (person.presence ?? [])
      .filter((item) => item.kind === "business_trip" && item.date >= monday && item.date <= friday)
      .map((item) => item.date)
      .sort();
    if (trips.length > 0) {
      if (trips[0] < first) first = trips[0];
      parts.push(`${trips.map(weekdayName).join(", ")} · delegacja`);
    }
    if (parts.length > 0) {
      result.push({ user_id: person.user_id, name: person.name, text: parts.join("; "), pending, first });
    }
  }
  return result.sort((a, b) => a.first.localeCompare(b.first) || a.name.localeCompare(b.name, "pl"));
}

function fold(text: string): string {
  return text.normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/ł/g, "l").replace(/Ł/g, "L").toLowerCase();
}

/** „Znajdź osobę”: bez wielkości liter i polskich znaków („lukasz” = „Łukasz”). */
export function matchesName(person: Pick<TeamCalendarPerson, "name">, query: string): boolean {
  const needle = fold(query.trim());
  if (!needle) return true;
  return fold(person.name).includes(needle);
}
