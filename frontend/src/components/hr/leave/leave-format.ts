// Teksty i daty modułu urlopów — czyste funkcje (testowane bez renderu).
//
// Daty przychodzą z serwera jako „YYYY-MM-DD” (dzień kalendarza firmy) i tak
// zostają: żadnego `new Date(iso)` z przesunięciem strefy ani
// `toISOString().slice(0, 10)` (to dzień UTC — wieczorem już jutro).

import type { InlineStat } from "@/components/ds/InlineStats";
import type { StatusDotTone } from "@/components/ds/StatusDot";
import { absenceCardKind } from "@/components/hr/me/overview-format";
import type { EmploymentType } from "@/lib/api/hr";
import type {
  AbsentTodayRow,
  CalendarAbsence,
  CalendarPresence,
  CalendarPresenceKind,
  HalfDay,
  LeaveBalance,
  LeaveInput,
  LeavePreview,
  LeaveEditInput,
  LeaveRequestRow,
  LeaveStatus,
  LeaveStatusCounts,
  LeaveType,
  PendingLeaveRow,
  PersonAbsence,
  TeamCalendarPerson,
} from "@/lib/api/hr-leave";
import { formatDayMonthPl, formatWeekdayDayPl } from "@/lib/date-pl";
import { capitalize, employmentTerms, reportsAbsence } from "@/lib/hr-employment-terms";

export const LEAVE_TYPE_LABELS: Record<LeaveType, string> = {
  vacation: "Urlop wypoczynkowy",
  on_demand: "Urlop na żądanie",
  occasional: "Urlop okolicznościowy",
  childcare: "Opieka nad dzieckiem (art. 188)",
  care_leave: "Urlop opiekuńczy",
  force_majeure: "Siła wyższa",
  sick_leave: "Zwolnienie lekarskie (L4)",
  maternity: "Urlop macierzyński",
  paternity: "Urlop ojcowski",
  parental_leave: "Urlop rodzicielski",
  childrearing: "Urlop wychowawczy",
  unpaid_leave: "Urlop bezpłatny",
  blood_donation: "Oddanie krwi",
  training: "Urlop szkoleniowy",
  holiday_in_lieu: "Odbiór dnia za święto",
  other: "Inna nieobecność",
};

export const LEAVE_STATUS_LABELS: Record<LeaveStatus, string> = {
  pending: "Czeka na akceptację",
  approved: "Zatwierdzony",
  rejected: "Odrzucony",
  cancelled: "Anulowany",
};

export const LEAVE_STATUS_TONE: Record<LeaveStatus, StatusDotTone> = {
  pending: "warning",
  approved: "success",
  rejected: "danger",
  cancelled: "neutral",
};

export const HALF_DAY_LABELS: Record<HalfDay, string> = {
  morning: "pół dnia (rano)",
  afternoon: "pół dnia (po południu)",
};

/** Nazwa, którą widzi każdy poza kręgiem D6 (bez rodzaju nieobecności). */
export const NEUTRAL_ABSENCE = "Nieobecność";

interface DayParts {
  year: number;
  month: number;
  day: number;
}

function parseDay(iso: string): DayParts {
  const [year, month, day] = iso.slice(0, 10).split("-").map(Number);
  return { year, month, day };
}

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

/** „23–31.12.2026”, „23.12.2026–04.01.2027”, „14.11.2026”. */
export function formatRange(start: string, end: string): string {
  const a = parseDay(start);
  const b = parseDay(end);
  const full = (p: DayParts) => `${pad(p.day)}.${pad(p.month)}.${p.year}`;
  if (start === end) return full(a);
  if (a.year !== b.year) return `${full(a)}–${full(b)}`;
  if (a.month === b.month) return `${pad(a.day)}–${full(b)}`;
  return `${pad(a.day)}.${pad(a.month)}–${full(b)}`;
}

/** „1 dzień”, „5 dni”, „0,5 dnia”, „2,5 dnia”. */
export function daysLabel(value: string | number): string {
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  const text = number.toLocaleString("pl-PL", { maximumFractionDigits: 1 });
  if (number === 1) return "1 dzień";
  return Number.isInteger(number) ? `${text} dni` : `${text} dnia`;
}

/** „Anna Przykładowa” → „Anna P.” (plakietka przy osobie musi być krótka). */
export function shortName(name: string | null | undefined): string {
  if (!name) return "";
  const parts = name.trim().split(/\s+/);
  if (parts.length < 2) return parts[0] ?? "";
  return `${parts[0]} ${parts[parts.length - 1][0]}.`;
}

const EVENT_FORMAT = new Intl.DateTimeFormat("pl-PL", {
  timeZone: "Europe/Warsaw",
  weekday: "short",
  day: "2-digit",
  month: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
});

/** Chwila z serwera (UTC) jako czas warszawski: „śr., 12.11, 10:00”. */
export function eventLabel(instant: string): string {
  const parsed = new Date(instant);
  return Number.isNaN(parsed.getTime()) ? "" : EVENT_FORMAT.format(parsed);
}

/**
 * Tekst plakietki przy osobie: „Nieobecność do 24.10 · zastępuje Anna P.”.
 * Bez rodzaju nieobecności (D6) — plakietkę widzi cały zespół.
 */
export function absenceBadgeText(absence: Pick<
  PersonAbsence,
  "until" | "half_day" | "substitute_name"
>, today: string): string {
  const until =
    absence.half_day && absence.until === today
      ? "Nieobecność dziś (pół dnia)"
      : absence.until === today
        ? "Nieobecność dziś"
        : `Nieobecność do ${formatDayMonthPl(absence.until)}`;
  return absence.substitute_name
    ? `${until} · zastępuje ${shortName(absence.substitute_name)}`
    : until;
}

export type CalendarCell =
  | { kind: "none" }
  | { kind: "absent" | "pending"; half: boolean; absence: CalendarAbsence };

/** Komórki siatki kalendarza dla osoby: dzień → nieobecność (zatwierdzona wygrywa). */
export function calendarCells(
  absences: readonly CalendarAbsence[],
  days: readonly string[],
): Map<string, CalendarCell> {
  const cells = new Map<string, CalendarCell>();
  for (const day of days) cells.set(day, { kind: "none" });
  for (const absence of absences) {
    for (const day of days) {
      if (day < absence.start_date || day > absence.end_date) continue;
      const current = cells.get(day);
      if (current && current.kind === "absent") continue;
      cells.set(day, {
        kind: absence.status === "approved" ? "absent" : "pending",
        half: absence.half_day !== null,
        absence,
      });
    }
  }
  return cells;
}

/** Czy zakres dat jest kompletny i poprawny (do włączenia podglądu). */
export function validRange(start: string, end: string): boolean {
  const pattern = /^\d{4}-\d{2}-\d{2}$/;
  return pattern.test(start) && pattern.test(end) && end >= start;
}

/** Komunikat po zmianie urlopu: przy zamkniętym miesiącu płac doklejone ostrzeżenie, typ „info”. */
export function leaveToast(
  message: string,
  row?: { payroll_warning?: string | null } | null,
): [string, "success" | "info"] {
  const warning = row?.payroll_warning?.trim();
  return warning ? [`${message}. ${warning}`, "info"] : [message, "success"];
}


// ── Zgłoszenie z B2B i zlecenia (etap 2, D5) ─────────────────────────────────

/** Status wiersza: zgłoszenie z B2B/zlecenia jest „zgłoszone”, nie „zatwierdzone”. */
export function statusLabel(row: Pick<LeaveRequestRow, "status" | "is_report">): string {
  if (row.is_report && row.status === "approved") return "Zgłoszone";
  return LEAVE_STATUS_LABELS[row.status];
}

export interface OutcomeLine {
  title: string;
  text: string;
}

/**
 * „Co się stanie po zgłoszeniu” w oknie osoby na B2B albo zleceniu (makieta m5):
 * termin od razu w kalendarzu, koordynator tylko wie (może zgłosić kolizję),
 * raport godzin według formy i podziału z podglądu serwera.
 */
export function reportOutcome(
  preview: Pick<LeavePreview, "paid_days" | "unpaid_days" | "approver">,
  form: EmploymentType | null | undefined,
): OutcomeLine[] {
  const words = employmentTerms(form);
  const paid = Number(preview.paid_days) || 0;
  const unpaid = Number(preview.unpaid_days) || 0;
  const lines: OutcomeLine[] = [
    {
      title: "Termin od razu w kalendarzu",
      text: "zespół widzi „nieobecny”, bez szczegółów",
    },
    {
      title: `${capitalize(words.coordinator)} dostaje informację`,
      text: `${preview.approver} może zgłosić kolizję z pracą i poprosić o inny termin; nie zatwierdza i nie odrzuca`,
    },
  ];
  if (form === "b2b") {
    lines.push({
      title: words.timesheet,
      text:
        paid > 0
          ? unpaid > 0
            ? "dni z puli liczą się jak dni pracy do faktury, pozostałe są puste"
            : "dni z puli liczą się jak dni pracy do faktury"
          : "dni przerwy są puste — bez wynagrodzenia",
    });
  } else {
    lines.push({
      title: words.timesheet,
      text: "za te dni nie ma godzin — nieobecność jest bez wynagrodzenia",
    });
  }
  return lines;
}

/** „Rozliczenie: z płatnej puli 4 dni · bez wynagrodzenia 1 dzień” (B2B z pulą). */
export function paySplitLabel(
  preview: Pick<LeavePreview, "paid_days" | "unpaid_days">,
): string | null {
  const paid = Number(preview.paid_days) || 0;
  const unpaid = Number(preview.unpaid_days) || 0;
  if (paid <= 0 && unpaid <= 0) return null;
  const parts: string[] = [];
  if (paid > 0) parts.push(`z płatnej puli ${daysLabel(preview.paid_days)}`);
  if (unpaid > 0) parts.push(`bez wynagrodzenia ${daysLabel(preview.unpaid_days)}`);
  return `Rozliczenie: ${parts.join(" · ")}`;
}

/** Nazwa przycisku zapisu w oknie nieobecności (D4, D5). */
export function submitLabel(options: {
  onBehalf: boolean;
  form: EmploymentType | null | undefined;
  autoApproved: boolean | undefined;
}): string {
  if (options.onBehalf) return "Wpisz nieobecność";
  if (reportsAbsence(options.form)) return employmentTerms(options.form).submit_action;
  return options.autoApproved ? "Zgłoś nieobecność" : "Wyślij do akceptacji";
}

/** Komunikat po zapisie własnej nieobecności. */
export function submittedToast(
  row: Pick<LeaveRequestRow, "status" | "is_report" | "employment_type">,
): string {
  if (row.is_report) return `${capitalize(employmentTerms(row.employment_type).absence)} zgłoszona`;
  return row.status === "approved" ? "Nieobecność zgłoszona" : "Wniosek wysłany do akceptacji";
}

// ── Teksty ekranów urlopów (czyste funkcje wyjęte z komponentów) ─────────────

/** Druga linia wiersza: do kiedy i kto zastępuje (bez rodzaju nieobecności). */
export function absentRowText(row: AbsentTodayRow, today: string): string {
  const until =
    row.half_day && row.until === today
      ? "Dziś pół dnia"
      : row.until === today
        ? "Nieobecność dziś"
        : `Nieobecność do ${formatWeekdayDayPl(row.until)}`;
  if (row.i_substitute) return `${until} · zastępujesz Ty`;
  if (row.substitute_name) return `${until} · zastępuje ${row.substitute_name}`;
  return `${until} · bez zastępcy`;
}

/** Zdania pod wnioskiem w kolejce — co akceptujący powinien wiedzieć. */
export function pendingDetails(row: PendingLeaveRow, viewerIsHr: boolean): string[] {
  const lines: string[] = [];
  lines.push(row.substitute_name ? `zastępca ${row.substitute_name}` : "bez zastępcy");
  for (const kind of row.work_by_kind) {
    lines.push(`${kind.label}: ${kind.count}`);
  }
  if (row.department_absent.length > 0) {
    const names = row.department_absent
      .map((other) => `${other.name} (${formatDayMonthPl(other.start_date)}–${formatDayMonthPl(other.end_date)})`)
      .join(", ");
    lines.push(`w tym czasie nieobecni też: ${names}`);
  }
  if (viewerIsHr && row.manager_name) lines.push(`przełożony: ${row.manager_name}`);
  return lines;
}

/**
 * Liczby salda do nagłówka zakładki (czysta funkcja — test bez renderu).
 *
 * Słowa zależą od formy (17.10.2026): UoP — urlop z pulą, na żądanie i opieką
 * art. 188; B2B/zlecenie z umowną pulą — płatne dni przerwy bez limitów
 * Kodeksu; bez puli — same dni nieobecności, bez „zostało”. Trzy liczby
 * (wykorzystane do dziś, zaplanowane po dziś, czeka) liczy serwer.
 */
export function balanceStats(balance: LeaveBalance): InlineStat[] {
  const kind = absenceCardKind(balance.employment_type, balance);
  // Na B2B i zleceniu nic nie czeka na akceptację (zgłoszenie, D5) — liczba
  // „czeka” pokazuje się tylko, gdy coś zostało sprzed zmiany formy.
  const report = reportsAbsence(balance.employment_type);
  const pending =
    report && !(Number(balance.pending_days) > 0)
      ? []
      : [{ id: "pending", label: "czeka na akceptację", value: daysLabel(balance.pending_days) }];
  const stats: InlineStat[] = [];
  if (kind === "absences") {
    stats.push(
      { id: "used", label: `wykorzystane w ${balance.year}`, value: daysLabel(balance.used_days) },
      { id: "planned", label: `zaplanowane w ${balance.year}`, value: daysLabel(balance.planned_days) },
      ...pending,
    );
    return stats;
  }
  if (balance.has_pool) {
    stats.push(
      {
        id: "remaining",
        label: `zostało w ${balance.year}`,
        value: daysLabel(balance.remaining_days ?? "0"),
        title: "Pula minus wykorzystane, zaplanowane i czekające na akceptację.",
      },
      {
        id: "pool",
        label: kind === "leave" ? "pula z zaległym" : "pula z umowy",
        value: daysLabel(
          Number(balance.entitlement_days ?? 0) + Number(balance.carried_over_days ?? 0),
        ),
        title: Number(balance.used_initial_days ?? 0)
          ? `W tym ${daysLabel(balance.used_initial_days ?? "0")} wykorzystane przed NEXUSEM.`
          : undefined,
      },
    );
  } else {
    stats.push({ id: "remaining", label: `pula ${balance.year}`, value: "nie ustawiona" });
  }
  stats.push(
    { id: "used", label: "wykorzystane", value: daysLabel(balance.used_days) },
    { id: "planned", label: "zaplanowane", value: daysLabel(balance.planned_days) },
    ...pending,
  );
  if (Number(balance.unpaid_days) > 0) {
    stats.push({
      id: "unpaid",
      label: kind === "leave" ? "bezpłatne" : "bez wynagrodzenia",
      value: daysLabel(balance.unpaid_days),
    });
  }
  if (kind === "leave" && balance.on_demand_limit !== null) {
    stats.push({
      id: "on-demand",
      label: "na żądanie",
      value: `${Number(balance.on_demand_used ?? 0).toLocaleString("pl-PL")} / ${Number(
        balance.on_demand_limit,
      )}`,
    });
  }
  if (kind === "leave" && balance.childcare_limit !== null) {
    stats.push({
      id: "childcare",
      label: "opieka nad dzieckiem (art. 188)",
      value: `${Number(balance.childcare_used ?? 0).toLocaleString("pl-PL")} / ${Number(
        balance.childcare_limit,
      )}`,
    });
  }
  return stats;
}

/** Czy osoba może jeszcze przełączyć przekierowanie poczty przy wniosku. */
export function canToggleForward(row: LeaveRequestRow, today: string): boolean {
  return (
    row.substitute_user_id !== null &&
    (row.status === "pending" || row.status === "approved") &&
    row.end_date >= today
  );
}

// ── Dane wniosku z okna nieobecności ─────────────────────────────────────────

/** Wartość pola „Wymiar” dla całego dnia. */
export const FULL_DAY = "full";
/** Wartość pola „Zastępca” bez zastępcy. */
export const NO_SUBSTITUTE = "none";

/** Pola okna nieobecności tak, jak trzyma je formularz. */
export interface LeaveFormValues {
  leaveType: LeaveType;
  start: string;
  end: string;
  /** `FULL_DAY` albo pół dnia; pół dnia liczy się tylko przy jednym dniu. */
  halfDay: string;
  /** Id zastępcy jako tekst albo `NO_SUBSTITUTE`. */
  substitute: string;
  note: string;
  forward: boolean;
  oofInternal: string;
  oofExternal: string;
}

/**
 * `LeaveInput` ze stanu okna (`null`, gdy daty są niepełne albo odwrócone).
 * `preview` — rodzaj, daty, pół dnia i zastępca, bez notatki: pisanie notatki
 * nie pyta serwera o podgląd. `self` — zapis własnego wniosku: notatka, zgoda
 * na przekierowanie poczty (tylko z zastępcą) i teksty OOF. `on_behalf` — wpis
 * za pracownika: notatka bez zgody i OOF (należą do samej osoby).
 */
export function leaveInputFrom(
  values: LeaveFormValues,
  purpose: "preview" | "self" | "on_behalf",
): LeaveInput | null {
  if (!validRange(values.start, values.end)) return null;
  const singleDay = values.start === values.end;
  const input: LeaveInput = {
    leave_type: values.leaveType,
    start_date: values.start,
    end_date: values.end,
    half_day: singleDay && values.halfDay !== FULL_DAY ? (values.halfDay as HalfDay) : null,
    substitute_user_id: values.substitute === NO_SUBSTITUTE ? null : Number(values.substitute),
  };
  if (purpose === "preview") return input;
  const base = { ...input, note: values.note.trim() || null };
  if (purpose === "on_behalf") return base;
  return {
    ...base,
    forward_mail_consent: Boolean(input.substitute_user_id) && values.forward,
    oof_internal_message: values.oofInternal.trim() || null,
    oof_external_message: values.oofExternal.trim() || null,
  };
}


// ── Źródło wniosku, liczniki statusów, edycja (luki z Compassa, 18.10.2026) ──

/** Plakietka źródła wniosku; zwykły wniosek osoby (`self`) jej nie ma. */
export function sourceBadge(source: LeaveRequestRow["source"]): string | null {
  switch (source) {
    case "on_behalf":
      return "Wpis za pracownika";
    case "outlook_oof":
      return "Z Outlooka";
    case "compass_import":
      return "Import z Compassa";
    default:
      return null;
  }
}

/** „Czeka na akceptację (3)” — etykieta filtra statusu z licznikiem serwera. */
export function statusFilterLabel(
  label: string,
  value: LeaveStatus | "all",
  counts: LeaveStatusCounts | null | undefined,
): string {
  const count = counts?.[value];
  return typeof count === "number" ? `${label} (${count})` : label;
}

/** Pola okna edycji wniosku (jak w oknie nieobecności). */
export interface LeaveEditValues {
  leaveType: LeaveType;
  start: string;
  end: string;
  /** `FULL_DAY` albo pół dnia; przy kilku dniach zawsze cały dzień. */
  halfDay: string;
  /** Id zastępcy jako tekst albo `NO_SUBSTITUTE`. */
  substitute: string;
}

export function editValuesFrom(row: LeaveRequestRow): LeaveEditValues {
  return {
    leaveType: row.leave_type ?? "vacation",
    start: row.start_date,
    end: row.end_date,
    halfDay: row.half_day ?? FULL_DAY,
    substitute: row.substitute_user_id ? String(row.substitute_user_id) : NO_SUBSTITUTE,
  };
}

/**
 * Tylko zmienione pola (`PATCH`); `null` = brak zmian albo złe daty.
 * Pół dnia liczy się tylko przy jednym dniu — przy kilku wysyłamy „cały dzień”.
 */
export function editChanges(
  row: LeaveRequestRow,
  values: LeaveEditValues,
): LeaveEditInput | null {
  if (!validRange(values.start, values.end)) return null;
  const halfDay =
    values.start === values.end && values.halfDay !== FULL_DAY
      ? (values.halfDay as HalfDay)
      : null;
  const substitute = values.substitute === NO_SUBSTITUTE ? null : Number(values.substitute);
  const changes: LeaveEditInput = {};
  if (row.leave_type !== null && values.leaveType !== row.leave_type) {
    changes.leave_type = values.leaveType;
  }
  if (values.start !== row.start_date) changes.start_date = values.start;
  if (values.end !== row.end_date) changes.end_date = values.end;
  if (halfDay !== row.half_day) changes.half_day = halfDay;
  if (substitute !== row.substitute_user_id) changes.substitute_user_id = substitute;
  return Object.keys(changes).length > 0 ? changes : null;
}

/** Czy patrzący może zmienić wiersz (zgłoszenie z B2B/zlecenia — tylko Kadry, D5). */
export function canEditRow(row: LeaveRequestRow, viewerIsHr: boolean): boolean {
  if (row.status !== "pending" && row.status !== "approved") return false;
  return viewerIsHr || !row.is_report;
}

// ── Kalendarz zespołu: praca zdalna, delegacja, filtr (Compass) ──────────────

export const PRESENCE_LABELS: Record<CalendarPresenceKind, string> = {
  remote: "praca zdalna",
  business_trip: "delegacja",
};

/** Dzień → wyjątek obecności osoby (zdalnie albo delegacja). */
export function presenceByDay(
  presence: readonly CalendarPresence[] | undefined,
): Map<string, CalendarPresenceKind> {
  const map = new Map<string, CalendarPresenceKind>();
  for (const item of presence ?? []) map.set(item.date, item.kind);
  return map;
}

export type CalendarStatusFilter = "all" | "absent" | "remote";

/**
 * Filtr „wszyscy / nieobecni / zdalnie” (Compass `VacationCalendar`): gdy
 * dziś jest w oglądanym miesiącu — stan na dziś, inaczej — ktokolwiek
 * w miesiącu (przeglądanie innych miesięcy nie daje pustej listy).
 * Delegacja liczy się do „nieobecnych” (poza biurem, jak „OOO” w Compassie).
 */
export function matchesStatusFilter(
  person: TeamCalendarPerson,
  filter: CalendarStatusFilter,
  today: string,
  month: string,
): boolean {
  if (filter === "all") return true;
  const todayInView = today.startsWith(month);
  const presence = person.presence ?? [];
  if (filter === "remote") {
    return presence.some(
      (item) => item.kind === "remote" && (!todayInView || item.date === today),
    );
  }
  const trip = presence.some(
    (item) => item.kind === "business_trip" && (!todayInView || item.date === today),
  );
  const absent = person.absences.some(
    (absence) =>
      absence.status === "approved" &&
      (!todayInView || (absence.start_date <= today && today <= absence.end_date)),
  );
  return trip || absent;
}
