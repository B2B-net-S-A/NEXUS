// Teksty i daty modułu urlopów — czyste funkcje (testowane bez renderu).
//
// Daty przychodzą z serwera jako „YYYY-MM-DD” (dzień kalendarza firmy) i tak
// zostają: żadnego `new Date(iso)` z przesunięciem strefy ani
// `toISOString().slice(0, 10)` (to dzień UTC — wieczorem już jutro).

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
  /** Kto wrzuca do Cpro w tym czasie (id jako tekst) — tylko osoba od Cpro. */
  cproSubstitute?: string;
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
 * za pracownika: notatka bez zgody i OOF (należą do samej osoby). Osoba,
 * która wrzuca do Cpro, wybrana w obu trybach zapisu (podgląd jej nie potrzebuje).
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
  const cpro =
    values.cproSubstitute && values.cproSubstitute !== NO_SUBSTITUTE
      ? { cpro_substitute_user_id: Number(values.cproSubstitute) }
      : {};
  const base = { ...input, ...cpro, note: values.note.trim() || null };
  if (purpose === "on_behalf") return base;
  return {
    ...base,
    forward_mail_consent: Boolean(input.substitute_user_id) && values.forward,
    oof_internal_message: values.oofInternal.trim() || null,
    oof_external_message: values.oofExternal.trim() || null,
  };
}

/**
 * Własny wniosek osoby od Cpro na pełne dni bez wskazania, kto wrzuca do Cpro
 * (decyzja Artura 29.10.2026; serwer odmawia tym samym warunkiem). Pół dnia
 * i wpis za pracownika nie wymagają wyboru.
 */
export function cproSubstituteMissing(
  values: Pick<LeaveFormValues, "start" | "end" | "halfDay" | "cproSubstitute">,
  cproSender: boolean | undefined,
  onBehalf: boolean,
): boolean {
  if (onBehalf || cproSender !== true) return false;
  const halfDay = values.start === values.end && values.halfDay !== FULL_DAY;
  if (halfDay) return false;
  return !values.cproSubstitute || values.cproSubstitute === NO_SUBSTITUTE;
}

// ── Źródło wniosku, liczniki statusów, edycja (luki z Compassa, 18.10.2026) ──

/** Plakietka źródła wniosku; zwykły wniosek osoby (`self`) jej nie ma. */
export function sourceBadge(source: LeaveRequestRow["source"]): string | null {
  switch (source) {
    case "on_behalf":
      return "Wpis za konsultanta/kontraktora";
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

/**
 * Historia wniosków przychodzi z limitem (najnowsze terminy); gdy filtr ma
 * więcej wniosków, niż przyszło, mówimy to wprost — inaczej najstarsze
 * znikają bez śladu (audyt 19.10.2026).
 */
export function historyCapNote(
  shown: number,
  status: LeaveStatus | "all",
  counts: LeaveStatusCounts | null | undefined,
): string | null {
  const total = counts?.[status];
  if (typeof total !== "number" || total <= shown) return null;
  return `Pokazano ${shown} z ${total} — najnowsze terminy. Wybierz osobę albo status, żeby zobaczyć starsze.`;
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

/**
 * Cofnięcie przez przełożonego albo Kadry od pierwszego dnia wymaga powodu
 * (decyzja Artura 28.10.2026; backend: `leave_policy.approver_cancel_refusal`).
 * `today` = `warsawToday()`.
 */
export function cancelNeedsReason(row: Pick<LeaveRequestRow, "start_date">, today: string): boolean {
  return row.start_date <= today;
}

/** Tytuł i zdanie okna cofnięcia terminu, który już trwa albo minął (słowa formy osoby). */
export function pastCancelText(
  row: Pick<LeaveRequestRow, "status" | "start_date" | "end_date" | "employment_type">,
  today: string,
): { title: string; text: string } {
  const range = formatRange(row.start_date, row.end_date);
  const notice = "Osoba dostanie powiadomienie z powodem.";
  if (row.status === "pending") {
    return {
      title: `Anulować wniosek ${range}?`,
      text: `Wniosek nie ma decyzji, a jego termin już się zaczął. ${notice}`,
    };
  }
  const timesheet = employmentTerms(row.employment_type).timesheet_genitive;
  const back = `do ${timesheet} jako dni robocze do uzupełnienia i do statów.`;
  return {
    title: `Cofnąć nieobecność ${range}?`,
    text:
      row.end_date < today
        ? `Te dni już minęły. Po cofnięciu wrócą ${back} ${notice}`
        : `Ten termin już trwa. Po cofnięciu minione dni wrócą ${back} ${notice}`,
  };
}

/** Czy patrzący może zmienić wiersz (zgłoszenie z B2B/zlecenia — tylko Kadry, D5). */
export function canEditRow(row: LeaveRequestRow, viewerIsHr: boolean): boolean {
  if (row.status !== "pending" && row.status !== "approved") return false;
  return viewerIsHr || !row.is_report;
}

// ── Kalendarz zespołu: praca zdalna, delegacja, filtr (Compass) ──────────────

export const PRESENCE_LABELS: Record<CalendarPresenceKind, string> = {
  remote: "zdalnie",
  business_trip: "wyjazd",
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
 * dziś jest w oglądanym oknie (miesiąc albo dwa tygodnie) — stan na dziś,
 * inaczej — ktokolwiek w tym oknie (przeglądanie innych okresów nie daje
 * pustej listy). Dane przychodzą całymi miesiącami, więc wpisy spoza okna
 * odcinamy datami. Delegacja liczy się do „nieobecnych” (poza biurem, jak
 * „OOO” w Compassie).
 */
export function matchesStatusFilter(
  person: TeamCalendarPerson,
  filter: CalendarStatusFilter,
  today: string,
  window: { start: string; end: string },
): boolean {
  if (filter === "all") return true;
  const todayInView = window.start <= today && today <= window.end;
  const from = todayInView ? today : window.start;
  const to = todayInView ? today : window.end;
  const presence = person.presence ?? [];
  const onDay = (date: string) => from <= date && date <= to;
  if (filter === "remote") {
    return presence.some((item) => item.kind === "remote" && onDay(item.date));
  }
  const trip = presence.some((item) => item.kind === "business_trip" && onDay(item.date));
  const absent = person.absences.some(
    (absence) =>
      absence.status === "approved" && absence.start_date <= to && from <= absence.end_date,
  );
  return trip || absent;
}

// ── „Mój rok” w zakładce nieobecności (runda 2 makiet, 21.10.2026) ────────────

const MONTH_SHORT = ["sty", "lut", "mar", "kwi", "maj", "cze", "lip", "sie", "wrz", "paź", "lis", "gru"];

export interface YearMonthCell {
  month: number;
  label: string;
  past: boolean;
  current: boolean;
  items: { id: string; label: string; status: LeaveStatus }[];
}

/**
 * Dwanaście miesięcy roku z moimi nieobecnościami (zatwierdzone i czekające;
 * odrzucone i anulowane pomijamy). Wpis przez przełom miesiąca jest w obu.
 */
export function yearMonths(
  rows: readonly Pick<LeaveRequestRow, "id" | "start_date" | "end_date" | "status" | "leave_type_label">[],
  year: number,
  today: string,
): YearMonthCell[] {
  const [ty, tm] = today.split("-").map(Number);
  return MONTH_SHORT.map((label, index) => {
    const month = index + 1;
    const first = `${year}-${pad(month)}-01`;
    const last = `${year}-${pad(month)}-31`;
    const items = rows
      .filter((row) => row.status === "approved" || row.status === "pending")
      .filter((row) => row.start_date <= last && row.end_date >= first)
      .map((row) => ({ id: row.id, label: row.leave_type_label, status: row.status }));
    return {
      month,
      label,
      past: year < ty || (year === ty && month < tm),
      current: year === ty && month === tm,
      items,
    };
  });
}
