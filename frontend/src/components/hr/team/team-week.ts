// „Mój zespół” wg makiety z 19.10.2026 — pasek „Dziś”, karty „Do Twojej
// decyzji”, mini-tydzień pn–pt i pasek godzin miesiąca (czyste funkcje).
//
// Rodzaj nieobecności tylko wtedy, gdy serwer go zwrócił (`leave_type`, krąg
// D6); mini-tydzień nie niesie rodzaju wcale. Kwoty premii tylko z `bonuses`,
// które serwer wysyła wyłącznie przełożonemu i Płacom (D2).

import { daysLabel, formatRange } from "@/components/hr/leave/leave-format";
import type {
  MyTeam,
  TeamLeaveDecision,
  TeamPerson,
  TeamTimesheetDecision,
  TeamWeekState,
} from "@/lib/api/hr-team";
import { TIMESHEET_STATUS_LABELS, type QueueStatus } from "@/lib/api/hr-time";
import { formatWeekdayDayPl, monthTitlePl, monthYearPl, weekdayOfIso } from "@/lib/date-pl";
import { employmentTerms } from "@/lib/hr-employment-terms";
import { formatMoney } from "@/lib/money";
import { countPl } from "@/lib/plural-pl";
import { warsawDateOf } from "@/lib/warsaw-date";

const WEEK_LABELS = ["pn", "wt", "śr", "cz", "pt", "so", "nd"] as const;

export const WEEK_STATE_LABELS: Record<TeamWeekState, string> = {
  work: "dostępny(a)",
  off: "dzień wolny",
  absent: "nieobecność",
  pending: "wniosek czeka",
  business_trip: "wyjazd",
  remote: "zdalnie",
  unknown: "brak danych o nieobecności",
};

export interface WeekCell {
  date: string;
  /** „pn”…„pt” — albo „D” (delegacja), „Z” (zdalnie), „½” (pół dnia). */
  mark: string;
  state: TeamWeekState;
  half: boolean;
  isToday: boolean;
  title: string;
}

/** Mini-tydzień osoby; `null`, gdy serwer go nie wysłał (moduły zamknięte). */
export function weekCells(person: TeamPerson, today: string): WeekCell[] | null {
  if (!person.week || person.week.length === 0) return null;
  return person.week.map((day) => {
    const label = WEEK_LABELS[weekdayOfIso(day.date)] ?? "";
    const half = Boolean(day.half_day) && (day.state === "absent" || day.state === "pending");
    const mark =
      day.state === "business_trip"
        ? "D"
        : day.state === "remote"
          ? "Z"
          : half
            ? "½"
            : label;
    const what = `${WEEK_STATE_LABELS[day.state]}${half ? " (pół dnia)" : ""}`;
    return {
      date: day.date,
      mark,
      state: day.state,
      half,
      isToday: day.date === today,
      title: `${label} ${day.date.slice(8, 10)}.${day.date.slice(5, 7)}: ${what}`,
    };
  });
}

/** Opis tygodnia dla czytnika ekranu: „pn: w pracy, wt: nieobecność, …”. */
export function weekAriaLabel(cells: readonly WeekCell[]): string {
  return cells.map((cell) => cell.title.replace(/ \d{2}\.\d{2}:/, ":")).join(", ");
}

export type TodayKind = "work" | "absent" | "trip" | "remote" | "unknown";

export interface TodayStatus {
  kind: TodayKind;
  text: string;
}

function firstName(name: string): string {
  return name.trim().split(/\s+/)[0] ?? name;
}

/**
 * Status osoby na pasku „Dziś”: nieobecność do kiedy (rodzaj tylko z serwera),
 * delegacja albo praca zdalna z mini-tygodnia, kogo zastępuje, „w pracy”.
 */
export function todayStatus(person: TeamPerson, today: string): TodayStatus {
  const absent = person.today?.absent ? person.today : null;
  if (absent) {
    const kind = absent.leave_type && absent.leave_type_label
      ? absent.leave_type_label.toLowerCase()
      : "nieobecność";
    if (absent.half_day && (!absent.until || absent.until === today)) {
      return { kind: "absent", text: `${kind} · pół dnia` };
    }
    return {
      kind: "absent",
      text: absent.until && absent.until !== today
        ? `${kind} do ${formatWeekdayDayPl(absent.until)}`
        : `${kind} dziś`,
    };
  }
  const day = person.week?.find((item) => item.date === today);
  if (day?.state === "business_trip") return { kind: "trip", text: "wyjazd" };
  if (day?.state === "remote") return { kind: "remote", text: "zdalnie" };
  if (person.covering_for.length > 0) {
    return {
      kind: "work",
      text: `zastępuje: ${person.covering_for.map(firstName).join(", ")}`,
    };
  }
  // Bez modułu urlopów (`unknown`) nieobecności nie znamy — nie mówimy „w pracy”.
  if (day?.state === "unknown" || (!person.today && !day)) return { kind: "unknown", text: "—" };
  return { kind: "work", text: "dostępny(a)" };
}

/** „4 w pracy · 1 osoba nieobecna · 1 w delegacji”. */
export function todaySummary(people: readonly TeamPerson[], today: string): string {
  const counts = { work: 0, absent: 0, trip: 0 };
  for (const person of people) {
    const status = todayStatus(person, today).kind;
    if (status === "absent") counts.absent += 1;
    else if (status === "trip") counts.trip += 1;
    else if (status !== "unknown") counts.work += 1;
  }
  const parts = [`dostępni: ${counts.work}`];
  if (counts.absent > 0) {
    parts.push(countPl(counts.absent, "osoba nieobecna", "osoby nieobecne", "osób nieobecnych"));
  }
  if (counts.trip > 0) parts.push(`na wyjeździe: ${counts.trip}`);
  return parts.join(" · ");
}

export type MonthTone = "draft" | "submitted" | "approved" | "missing";

export interface MonthProgress {
  /** `null` — osoba bez timesheetu albo brak danych („—”). */
  hours: number | null;
  norm: number;
  /** 0–100 — szerokość paska. */
  percent: number;
  text: string;
  status: QueueStatus | null;
  statusLabel: string;
  full: boolean;
}

/** Pasek godzin miesiąca: godziny / norma i status timesheetu. */
export function monthProgress(person: TeamPerson, team: MyTeam): MonthProgress | null {
  if (!team.month) return null;
  const norm = team.month.norm_hours;
  if (!person.month) {
    return {
      hours: null,
      norm,
      percent: 0,
      text: person.timesheet_required ? "—" : "bez timesheetu",
      status: null,
      statusLabel: "",
      full: false,
    };
  }
  const hours = person.month.hours;
  const percent = norm > 0 ? Math.max(0, Math.min(100, Math.round((hours / norm) * 100))) : 0;
  const shown = hours.toLocaleString("pl-PL", { maximumFractionDigits: 1 });
  return {
    hours,
    norm,
    percent,
    text: `${shown} / ${norm} h`,
    status: person.month.status,
    statusLabel: TIMESHEET_STATUS_LABELS[person.month.status].toLowerCase(),
    full: norm > 0 && hours >= norm,
  };
}

/** Ile pełnych dni minęło od chwili (kalendarz firmy); `null` bez daty. */
export function daysSince(instant: string | null | undefined, today: string): number | null {
  const day = warsawDateOf(instant ?? null);
  if (!day) return null;
  const [y1, m1, d1] = day.split("-").map(Number);
  const [y2, m2, d2] = today.split("-").map(Number);
  const diff = Math.round((Date.UTC(y2, m2 - 1, d2) - Date.UTC(y1, m1 - 1, d1)) / 86_400_000);
  return Math.max(0, diff);
}

function waitedLabel(prefix: string, days: number | null): string | undefined {
  if (days === null) return undefined;
  if (days === 0) return `${prefix} dziś`;
  if (days === 1) return `${prefix} wczoraj`;
  return `${prefix} ${days} dni temu`;
}

export type DecisionCard =
  | {
      kind: "leave";
      key: string;
      person: TeamPerson;
      item: TeamLeaveDecision;
      badge: string;
      title: string;
      detail: string;
      waited?: string;
    }
  | {
      kind: "timesheet";
      key: string;
      person: TeamPerson;
      item: TeamTimesheetDecision;
      badge: string;
      title: string;
      detail: string;
      waited?: string;
      /** Godziny do okna potwierdzenia (tylko bieżący miesiąc). */
      hoursText: string | null;
    }
  | {
      kind: "bonus";
      key: string;
      person: TeamPerson;
      badge: string;
      title: string;
      detail: string;
    };

/** Słowo wniosku: forma znana → słownik formy (D4), nieznana → „wniosek”. */
function requestBadge(person: TeamPerson): string {
  if (!person.employment_type) return "wniosek";
  if (person.employment_type === "uop") return "wniosek urlopowy";
  return employmentTerms(person.employment_type).request;
}

function proposalsTotal(person: TeamPerson): string | null {
  const proposed = (person.bonuses?.items ?? []).filter((item) => item.status === "proposed");
  if (proposed.length === 0) return null;
  const totals = new Map<string, number>();
  for (const item of proposed) {
    totals.set(item.currency, (totals.get(item.currency) ?? 0) + Number(item.amount));
  }
  return [...totals.entries()]
    .map(([currency, amount]) => formatMoney(amount, currency))
    .join(" + ");
}

/**
 * Karty „Do Twojej decyzji”: wnioski i timesheety (decyzja tutaj, tymi samymi
 * trasami co „Akceptacje”) oraz propozycje premii tylko do wiadomości
 * (decydują Płace). Karty premii tylko przy `sees_bonuses` (D2).
 */
export function decisionCards(team: MyTeam): DecisionCard[] {
  const today = team.today;
  const leave: DecisionCard[] = [];
  const timesheets: DecisionCard[] = [];
  const bonuses: DecisionCard[] = [];
  for (const person of team.people) {
    for (const item of person.to_decide.leave_requests) {
      const pool =
        person.leave?.has_paid_pool && person.leave.remaining_days !== null
          ? `zostało ${daysLabel(person.leave.remaining_days)} ${
              person.employment_type === "uop" ? "urlopu" : "z puli"
            }`
          : null;
      leave.push({
        kind: "leave",
        key: `leave-${item.id}`,
        person,
        item,
        badge: requestBadge(person),
        title: `${person.name} · ${formatRange(item.start_date, item.end_date)}`,
        detail: [daysLabel(item.days_total), item.leave_type_label, pool]
          .filter(Boolean)
          .join(" · "),
        waited: (() => {
          const days = daysSince(item.created_at, today);
          if (days === null) return undefined;
          return days === 0 ? "złożony dziś" : `czeka ${days === 1 ? "1 dzień" : `${days} dni`}`;
        })(),
      });
    }
    for (const item of person.to_decide.timesheets) {
      const sameMonth =
        team.month !== null &&
        team.month.year === item.year &&
        team.month.month === item.month &&
        person.month !== null;
      const hoursText = sameMonth && person.month && team.month
        ? `${person.month.hours.toLocaleString("pl-PL", { maximumFractionDigits: 1 })} / ${team.month.norm_hours} h`
        : null;
      timesheets.push({
        kind: "timesheet",
        key: `timesheet-${item.id}`,
        person,
        item,
        badge: "timesheet",
        title: `${person.name} · ${monthYearPl(item)}`,
        detail: hoursText ?? `do akceptacji za ${monthTitlePl(item).toLowerCase()}`,
        waited: waitedLabel("wysłany", daysSince(item.submitted_at, today)),
        hoursText,
      });
    }
    if (team.sees_bonuses) {
      const total = proposalsTotal(person);
      if (total) {
        bonuses.push({
          kind: "bonus",
          key: `bonus-${person.user_id}`,
          person,
          badge: "premia · do wiadomości",
          title: `${person.name} · ${total}`,
          detail: `${countPl(
            person.bonuses?.proposals ?? 0,
            "propozycja premii",
            "propozycje premii",
            "propozycji premii",
          )} — decydują Płace`,
        });
      }
    }
  }
  return [...leave, ...timesheets, ...bonuses];
}

/** Liczba spraw do decyzji (bez premii — te są do wiadomości). */
export function decisionCount(cards: readonly DecisionCard[]): number {
  return cards.filter((card) => card.kind !== "bonus").length;
}

/**
 * Znacznik „brak dd.mm” przy godzinach miesiąca (22.10.2026): jeden dzień bez
 * wpisu — jego data, kilka — liczba z ostatnią datą. Brak danych = brak znacznika.
 */
export function missingDaysLabel(dates: readonly string[] | undefined): string | null {
  if (!dates || dates.length === 0) return null;
  const last = dates[dates.length - 1];
  const [, month, day] = last.split("-");
  const short = `${day}.${month}`;
  return dates.length === 1 ? `brak ${short}` : `brak ${dates.length} dni · ost. ${short}`;
}
