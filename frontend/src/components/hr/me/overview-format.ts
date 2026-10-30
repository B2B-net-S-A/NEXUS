// „Mój czas → Przegląd” i „Premie i stawka” (etap 2, D1–D3) — czyste funkcje
// bez renderu (`__tests__/overview-format.test.ts`).
//
// Forma zatrudnienia decyduje o słowach: B2B i zlecenie nie mają urlopu
// w rozumieniu Kodeksu pracy (17.10.2026), więc tam „Płatne dni przerwy
// (z umowy)” albo „Nieobecności”, a karta miesiąca to „Raport godzin” albo
// „Potwierdzenie godzin”. Słowa formy są we wspólnym słowniku
// `@/lib/hr-employment-terms` (lustro backendu); liczby liczy serwer, tu tylko
// wybór i składanie.

import type { ProtocolRef } from "@/lib/api/equipment";
import type { EmploymentType } from "@/lib/api/hr";
import type { MyLifecycleTask } from "@/lib/api/hr-lifecycle";
import type { LeaveBalance, LeaveRequestRow } from "@/lib/api/hr-leave";
import type { BonusForecast, BonusRow, MyPayroll } from "@/lib/api/hr-payroll";
import type { MonthDay, MonthTotals, MonthView, TimesheetHistoryItem } from "@/lib/api/hr-time";
import { MONTHS_PL, formatDayMonthPl, monthYearPl, type YearMonth } from "@/lib/date-pl";
import { employmentTerms, timesheetAccusative } from "@/lib/hr-employment-terms";
import { formatMoney } from "@/lib/money";
import { warsawDateOf } from "@/lib/warsaw-date";

import { shortName } from "../leave/leave-format";
import { cancelReasonLabel, progressPercent } from "../payroll/payroll-format";

export {
  MANDATE_HOURS_NOTE,
  absenceActionLabel,
  timesheetAccusative,
  timesheetCardTitle,
} from "@/lib/hr-employment-terms";

// ── Nieobecności ─────────────────────────────────────────────────────────────

/** `leave` — urlop (UoP); `paid_days` — umowna pula płatnych dni; `absences` — bez puli. */
export type AbsenceCardKind = "leave" | "paid_days" | "absences";

/**
 * Która karta nieobecności: UoP → urlop; B2B albo zlecenie z płatną pulą
 * (> 0) → płatne dni przerwy; reszta → same nieobecności, bez „zostało”.
 * Zlecenie z pulą (dziś nikt) idzie jak B2B z pulą — serwer i tak ją potrąca.
 */
export function absenceCardKind(
  form: EmploymentType,
  balance: Pick<LeaveBalance, "has_paid_pool"> | null | undefined,
): AbsenceCardKind {
  if (form === "uop") return "leave";
  return balance?.has_paid_pool ? "paid_days" : "absences";
}

export function absenceCardTitle(kind: AbsenceCardKind, year: number): string {
  if (kind === "leave") return `Urlop ${year}`;
  if (kind === "paid_days") return "Płatne dni przerwy (z umowy)";
  return `Nieobecności ${year}`;
}

export interface PoolSegments {
  used: number;
  planned: number;
  pending: number;
  remaining: number;
  total: number;
}

/** Części paska puli (wykorzystane, zaplanowane, czeka, zostało); bez płatnej puli — `null`. */
export function poolSegments(balance: LeaveBalance): PoolSegments | null {
  if (!balance.has_paid_pool) return null;
  const used = Number(balance.used_days) || 0;
  const planned = Number(balance.planned_days) || 0;
  const pending = Number(balance.pending_days) || 0;
  const remaining = Math.max(0, Number(balance.remaining_days ?? 0) || 0);
  return { used, planned, pending, remaining, total: used + planned + pending + remaining };
}

/** Szerokość części paska w procentach (0–100). */
export function segmentPercent(value: number, total: number): number {
  if (!total || total <= 0) return 0;
  return Math.max(0, Math.min(100, (value / total) * 100));
}

export interface RingArc {
  key: "used" | "planned" | "pending";
  /** Długość łuku w procentach obwodu (0–100). */
  percent: number;
  /** Gdzie łuk się zaczyna (suma poprzednich łuków, 0–100). */
  start: number;
}

/**
 * Łuki pierścienia puli: wykorzystane → zaplanowane → czeka, jeden za drugim
 * od góry; reszta obwodu to „zostało” (tło pierścienia).
 */
export function ringArcs(parts: PoolSegments): RingArc[] {
  let start = 0;
  return (["used", "planned", "pending"] as const).map((key) => {
    const percent = segmentPercent(parts[key], parts.total);
    const arc = { key, percent, start };
    start += percent;
    return arc;
  });
}

/**
 * Najbliższa nieobecność, która się jeszcze nie skończyła. `approvedOnly` —
 * tylko zatwierdzona (karta z pulą); bez tego także czekająca („zgłoszona”).
 */
export function nextAbsence(
  rows: readonly LeaveRequestRow[],
  today: string,
  approvedOnly = false,
): LeaveRequestRow | null {
  const upcoming = rows
    .filter(
      (row) =>
        (row.status === "approved" || (!approvedOnly && row.status === "pending")) &&
        row.end_date >= today,
    )
    .sort((a, b) => a.start_date.localeCompare(b.start_date));
  return upcoming[0] ?? null;
}

// ── Miesiąc ──────────────────────────────────────────────────────────────────

/** Dni robocze do dziś włącznie bez wpisu i bez pełnego dnia nieobecności. */
export function missingDaysUntil(view: Pick<MonthView, "days">, today: string): string[] {
  return view.days
    .filter(
      (day) =>
        day.working_day &&
        day.date <= today &&
        day.entries.length === 0 &&
        !day.leave?.full &&
        !day.leave?.paid_work,
    )
    .map((day) => day.date);
}

/** „19, 20, 21, 22.10” — dni jednego miesiąca w skrócie. */
export function compactDays(dates: readonly string[]): string {
  if (dates.length === 0) return "";
  const last = dates[dates.length - 1];
  const days = dates.slice(0, -1).map((iso) => String(Number(iso.slice(8, 10))));
  return [...days, formatDayMonthPl(last)].join(", ");
}

/**
 * Dzień mini-kalendarza: `filled` — wpis w biurze, `remote` — wpis zdalnie,
 * `leave` — pełny dzień nieobecności (albo płatny dzień puli B2B), `missing` —
 * dzień roboczy do dziś bez wpisu (klik = uzupełnij), `empty` — to samo u osoby
 * bez obowiązku raportu, `future` — dzień roboczy po dziś, `off` — weekend,
 * święto, dzień wolny firmy.
 */
export type CalendarDayKind = "filled" | "remote" | "leave" | "missing" | "empty" | "future" | "off";

export interface CalendarDay {
  date: string;
  day: number;
  kind: CalendarDayKind;
  /** Opis dla czytnika i podpowiedzi. */
  label: string;
}

export interface MonthCalendar {
  /** Puste pola przed 1. dniem (poniedziałek = 0). */
  offset: number;
  days: CalendarDay[];
}

const CALENDAR_LABELS: Record<CalendarDayKind, string> = {
  filled: "uzupełniony",
  remote: "uzupełniony, zdalnie",
  leave: "nieobecność",
  missing: "brak wpisu — uzupełnij",
  empty: "bez wpisu",
  future: "jeszcze przed nami",
  off: "dzień wolny",
};

function calendarKind(
  day: Pick<MonthDay, "date" | "working_day" | "entries" | "leave" | "location">,
  today: string,
  timesheetRequired: boolean,
): CalendarDayKind {
  if (!day.working_day) return "off";
  if (day.leave?.full || day.leave?.paid_work) return "leave";
  if (day.date > today) return "future";
  if (day.entries.length === 0) return timesheetRequired ? "missing" : "empty";
  return day.location === "remote" ? "remote" : "filled";
}

/** Mini-kalendarz miesiąca z „Mojego miesiąca” (tydzień od poniedziałku). */
export function monthCalendar(
  view: Pick<MonthView, "days">,
  today: string,
  timesheetRequired: boolean,
): MonthCalendar {
  const first = view.days[0];
  return {
    offset: first ? Math.max(0, Math.min(6, first.weekday - 1)) : 0,
    days: view.days.map((day) => {
      const kind = calendarKind(day, today, timesheetRequired);
      const extra = kind === "off" ? (day.holiday ?? day.day_off) : kind === "leave" ? day.leave?.label : null;
      return {
        date: day.date,
        day: Number(day.date.slice(8, 10)),
        kind,
        label: `${formatDayMonthPl(day.date)}: ${extra ? `${CALENDAR_LABELS[kind]} (${extra})` : CALENDAR_LABELS[kind]}`,
      };
    }),
  };
}

/** Pasek godzin miesiąca: przepracowane i płatna nieobecność wobec normy (0–100). */
export function monthHoursPercent(totals: Pick<MonthTotals, "work_hours" | "leave_paid_hours" | "norm_hours">): number {
  return segmentPercent(totals.work_hours + totals.leave_paid_hours, totals.norm_hours);
}

/** Najwięcej dat wypisanych w linii braków; dłuższą listę pokazuje kalendarz karty. */
const MISSING_DAYS_LISTED = 3;

/**
 * „Brakuje dziś (19.10)” / „Brakuje 3 dni: 15, 16, 19.10” / „Brakuje 15 dni”
 * (dłuższej listy nie wypisujemy — dni są zaznaczone w kalendarzu karty,
 * makieta 21.10.2026); nic nie brakuje — `null`.
 */
export function missingLine(missing: readonly string[], today: string): string | null {
  if (missing.length === 0) return null;
  if (missing.length === 1) {
    return missing[0] === today
      ? `Brakuje dziś (${formatDayMonthPl(today)})`
      : `Brakuje ${formatDayMonthPl(missing[0])}`;
  }
  if (missing.length > MISSING_DAYS_LISTED) return `Brakuje ${missing.length} dni`;
  return `Brakuje ${missing.length} dni: ${compactDays(missing)}`;
}

// ── Premie ───────────────────────────────────────────────────────────────────

const MONTHS_INSTRUMENTAL = [
  "styczniem",
  "lutym",
  "marcem",
  "kwietniem",
  "majem",
  "czerwcem",
  "lipcem",
  "sierpniem",
  "wrześniem",
  "październikiem",
  "listopadem",
  "grudniem",
] as const;

export type StageState = "done" | "current" | "todo";

export interface BonusStage {
  label: string;
  state: StageState;
}

export interface MyBonusItem {
  key: string;
  title: string;
  subtitle: string;
  stages: BonusStage[];
  amount: string | null;
  currency: string;
  /** Kwota to szacunek („~”), nie decyzja Płac. */
  estimate: boolean;
  /** Kolumna „Kiedy”. */
  when: string;
  cancelled: boolean;
  /** Premia jeszcze nie przyznana (propozycja albo prognoza) — liczy się do „w drodze”. */
  inTransit: boolean;
  /** Pasek dni do terminu (0–100); `null` — premia bez odliczania (ręczna, przyznana). */
  progress: number | null;
  /** Linia pod paskiem w „Przeglądzie”: dni, termin, start umowy. */
  timeline: string;
}

/** „Premia rekrutera — placement: Jan Przykładowy (Firma)” → „Jan Przykładowy (Firma)”. */
export function placementLabel(description: string | null | undefined): string | null {
  const text = description?.trim();
  if (!text) return null;
  const marker = "placement:";
  const at = text.toLowerCase().indexOf(marker);
  return at >= 0 ? text.slice(at + marker.length).trim() || text : text;
}

function stages(labels: string[], current: number): BonusStage[] {
  return labels.map((label, index) => ({
    label,
    state: index < current ? "done" : index === current ? "current" : "todo",
  }));
}

/**
 * Premia „wypłacona” (R11, etap 4): przy włączonych rozliczeniach `/me` niesie
 * `paid` — premia jest wypłacona dopiero z opłaconym rozliczeniem miesiąca.
 * Bez pola (moduł rozliczeń wyłączony) zostaje stara reguła: miesiąc zamknięty
 * w płacach = rozliczona.
 */
export function bonusSettled(row: BonusRow): boolean {
  const paid = (row as BonusRow & { paid?: boolean | null }).paid;
  return typeof paid === "boolean" ? paid : Boolean(row.period_closed);
}

function payoutLabel(row: BonusRow, currentYear: number): string {
  const { period_year: year, period_month: month } = row;
  const suffix = year === currentYear ? "" : ` ${year}`;
  const paid = (row as BonusRow & { paid?: boolean | null }).paid;
  if (paid === true) return `wypłacona z rozliczeniem za ${MONTHS_PL[month - 1]}${suffix}`;
  if (paid === false && row.period_closed) {
    return `rozliczona za ${MONTHS_PL[month - 1]}${suffix} · czeka na zapłatę`;
  }
  return row.period_closed
    ? `rozliczona za ${MONTHS_PL[month - 1]}${suffix}`
    : `wypłata z ${MONTHS_INSTRUMENTAL[month - 1]}${suffix}`;
}

function daysStage(elapsed: number | null | undefined, required: number): string {
  return `${elapsed ?? 0} z ${required} dni`;
}

/** Premia z bazy jako wiersz z etapami: umowa → 21 dni → decyzja Płac → wypłata. */
export function bonusItemFromRow(
  row: BonusRow,
  today: string,
  requiredDays = 21,
): MyBonusItem {
  const currentYear = Number(today.slice(0, 4));
  const placement = row.source === "contract_placement";
  const title = placement
    ? `Placement: ${placementLabel(row.description) ?? "konsultant"}`
    : row.description?.trim() || row.category_label;
  const subtitle = row.category_label;
  const base = {
    key: `bonus-${row.id}`,
    title,
    subtitle,
    amount: row.amount,
    currency: row.currency,
    estimate: false,
    cancelled: false,
    inTransit: false,
    progress: null,
  };
  if (row.status === "cancelled") {
    const reason = cancelReasonLabel(row.cancel_reason, requiredDays);
    return {
      ...base,
      cancelled: true,
      stages: [{ label: "anulowana", state: "current" }],
      when: reason ?? "anulowana",
      timeline: reason ?? "anulowana",
    };
  }
  const payout = payoutLabel(row, currentYear);
  if (row.status === "assigned") {
    const who = row.assigned_by_name ? ` · ${row.assigned_by_name}` : "";
    // `assigned_at` to chwila UTC — dzień liczy kalendarz firmy (00:30 w Warszawie to jeszcze wczoraj w UTC).
    const when = row.assigned_at ? `przyznano ${formatDayMonthPl(warsawDateOf(row.assigned_at))}${who}` : "przyznana";
    const labels = placement
      ? ["umowa", `${requiredDays} dni`, "przyznana", payout]
      : ["przyznana", payout];
    return {
      ...base,
      stages: stages(labels, bonusSettled(row) ? labels.length : labels.length - 1),
      when,
      timeline: when,
    };
  }
  // Propozycja: placement przed terminem albo czekająca na decyzję Płac.
  const required = row.business_days_required ?? requiredDays;
  const beforeDeadline = row.eligible === false;
  if (placement) {
    const days = beforeDeadline ? daysStage(row.business_days_elapsed, required) : `${required} dni`;
    const facts = row.stages;
    let labels = ["umowa", days, "decyzja Płac", "wypłata"];
    let current = !beforeDeadline ? 2 : (row.business_days_elapsed ?? 0) > 0 ? 1 : 0;
    if (current === 0) labels[0] = "umowa podpisana";
    if (facts) {
      // Pełna ścieżka: pierwszy niespełniony etap jest bieżący. Zamówienie
      // pokazuje start, a termin to dni robocze, nie policzone godziny.
      labels = ["podpis", "kontrakt", "zamówienie", "start", days, "decyzja Płac", "wypłata"];
      const passed = [facts.signed, facts.contract_active, facts.order, facts.started, !beforeDeadline];
      const firstOpen = passed.indexOf(false);
      current = firstOpen === -1 ? 5 : firstOpen;
    }
    const counting = beforeDeadline && row.eligible_on;
    return {
      ...base,
      inTransit: true,
      stages: stages(labels, current),
      when: counting ? `od ${formatDayMonthPl(row.eligible_on as string)}` : "czeka na decyzję Płac",
      progress: beforeDeadline ? progressPercent(row.business_days_elapsed ?? 0, required) : 100,
      timeline: counting
        ? `${daysStage(row.business_days_elapsed, required)} · liczy się do ${formatDayMonthPl(row.eligible_on as string)}`
        : "czeka na decyzję Płac",
    };
  }
  return {
    ...base,
    inTransit: true,
    stages: stages(["propozycja", "decyzja Płac", "wypłata"], 1),
    when: "czeka na decyzję Płac",
    timeline: "czeka na decyzję Płac",
  };
}

/** Prognoza z podpisanej umowy (bez wiersza w bazie): kwota to szacunek „~”. */
export function bonusItemFromForecast(item: BonusForecast): MyBonusItem {
  const days = item.started
    ? daysStage(item.business_days_elapsed, item.business_days_required)
    : `${item.business_days_required} dni`;
  const facts = item.stages;
  const labels = facts
    ? ["podpis", "kontrakt", "zamówienie", "start", days, "decyzja Płac", "wypłata"]
    : [item.started ? "umowa" : "umowa podpisana", days, "decyzja Płac", "wypłata"];
  const firstOpen = facts
    ? [facts.signed, facts.contract_active, facts.order, facts.started].indexOf(false)
    : -1;
  const current = facts ? (firstOpen === -1 ? 4 : firstOpen) : item.started ? 1 : 0;
  return {
    key: item.key,
    title: `Placement: ${placementLabel(item.description) ?? "konsultant"}`,
    subtitle: item.category_label,
    stages: stages(labels, current),
    amount: item.amount,
    currency: item.currency,
    estimate: true,
    when: item.started
      ? `~ od ${formatDayMonthPl(item.eligible_on)}`
      : `~ od ${formatDayMonthPl(item.eligible_on)} (start ${formatDayMonthPl(item.start_date)})`,
    cancelled: false,
    inTransit: true,
    progress: progressPercent(item.started ? item.business_days_elapsed : 0, item.business_days_required),
    timeline: item.started
      ? `${daysStage(item.business_days_elapsed, item.business_days_required)} · liczy się do ~${formatDayMonthPl(item.eligible_on)}`
      : `umowa podpisana · start ${formatDayMonthPl(item.start_date)} · liczy się do ~${formatDayMonthPl(item.eligible_on)}`,
  };
}

/** Wszystkie wiersze „Premii i stawki”: w drodze (najbliższe najpierw), potem reszta jak z serwera. */
export function myBonusItems(data: MyPayroll, today: string): MyBonusItem[] {
  const required = data.business_days_required ?? 21;
  const rows = data.bonuses.map((row) => bonusItemFromRow(row, today, required));
  const forecast = (data.forecast ?? []).map(bonusItemFromForecast);
  return [...forecast, ...rows.filter((r) => r.inTransit), ...rows.filter((r) => !r.inTransit)];
}

export interface InTransitSummary {
  count: number;
  /** Sumy znanych kwot per waluta. */
  totals: Record<string, number>;
  /** Ile pozycji bez kwoty (brak stawki klienta albo kursu). */
  unknown: number;
}

/** „W drodze”: propozycje bez decyzji + prognozy z podpisanych umów. */
export function inTransitSummary(items: readonly MyBonusItem[]): InTransitSummary {
  const totals: Record<string, number> = {};
  let count = 0;
  let unknown = 0;
  for (const item of items) {
    if (!item.inTransit) continue;
    count += 1;
    if (item.amount == null) {
      unknown += 1;
      continue;
    }
    totals[item.currency] = (totals[item.currency] ?? 0) + Number(item.amount);
  }
  return { count, totals, unknown };
}

/** „~ 3 500,00 zł” (kilka walut po kropce); bez znanych kwot — „kwota po uzupełnieniu stawek”. */
export function inTransitLabel(summary: InTransitSummary): string {
  const entries = Object.entries(summary.totals);
  if (entries.length === 0) return summary.count > 0 ? "kwota po uzupełnieniu stawek" : formatMoney(0);
  return entries.map(([currency, total]) => `~ ${formatMoney(total, currency)}`).join(" · ");
}

/** Suma premii przyznanych z okresem w danym roku (per waluta). */
export function assignedInYear(bonuses: readonly BonusRow[], year: number): Record<string, number> {
  const sums: Record<string, number> = {};
  for (const bonus of bonuses) {
    if (bonus.status !== "assigned" || bonus.period_year !== year) continue;
    sums[bonus.currency] = (sums[bonus.currency] ?? 0) + Number(bonus.amount);
  }
  return sums;
}

export function totalsLabel(totals: Record<string, number | string>): string {
  const entries = Object.entries(totals);
  if (entries.length === 0) return formatMoney(0);
  return entries.map(([currency, total]) => formatMoney(total, currency)).join(" · ");
}

// ── Do zrobienia ─────────────────────────────────────────────────────────────

export interface TodoItem {
  key: string;
  title: string;
  /** Skąd sprawa (osoba, recepcja, kto potwierdza) — bez terminu. */
  detail: string;
  /** Termin jako pigułka: „do 21.10”, „z 20.10”, „termin minął”. */
  due?: string;
  /** Jedyna akcja wiersza (przycisk); bez niej — sama informacja (np. link w mailu). */
  action?: string;
  href?: string;
  /** Zakładka „Mojego czasu” do otwarcia, gdy pozycja nie ma linku. */
  tab?: "month";
  /** Miesiąc raportu, który zakładka ma otworzyć (zaległy to nie bieżący). */
  month?: YearMonth;
  overdue?: boolean;
}

/** Źródła karty; `null` = moduł zamknięty albo osoba bez timesheetu. */
export interface TodoSources {
  current: YearMonth;
  employmentType: EmploymentType;
  tasks: readonly MyLifecycleTask[] | null;
  protocols: readonly Pick<ProtocolRef, "id" | "number" | "status" | "protocol_date">[] | null;
  timesheets: { history: readonly TimesheetHistoryItem[]; month: MonthView | undefined } | null;
}

/**
 * „Do zrobienia”: moje zadania wejścia/odejścia, protokoły sprzętu do podpisu,
 * zaległe timesheety i bieżący miesiąc do wysłania (albo poprawy).
 */
export function todoItems(sources: TodoSources): TodoItem[] {
  const { current } = sources;
  const form = timesheetAccusative(sources.employmentType);
  const items: TodoItem[] = [];
  for (const task of sources.tasks ?? []) {
    items.push({
      key: `task-${task.task_id}`,
      title: task.title,
      detail: task.person_name ?? "",
      due: task.due_date ? `do ${formatDayMonthPl(task.due_date)}` : undefined,
      action: task.link ? "Otwórz" : undefined,
      href: task.link,
      overdue: task.overdue,
    });
  }
  for (const protocol of sources.protocols ?? []) {
    if (protocol.status !== "oczekuje") continue;
    // Podpis biegnie linkiem z maila recepcji — w NEXUSIE nie ma czego kliknąć.
    items.push({
      key: `protocol-${protocol.id}`,
      title: `Podpisz protokół ${protocol.number}`,
      detail: "Recepcja · link w mailu",
      due: `z ${formatDayMonthPl(protocol.protocol_date)}`,
    });
  }
  if (!sources.timesheets) return items;
  for (const item of sources.timesheets.history) {
    const older = item.year * 12 + item.month < current.year * 12 + current.month;
    if (older && item.status === "draft") {
      items.push({
        key: `ts-${item.id}`,
        title: `Wyślij ${form} za ${monthYearPl(item)}`,
        detail: "",
        due: "termin minął",
        action: "Wyślij",
        tab: "month",
        month: { year: item.year, month: item.month },
        overdue: true,
      });
    }
  }
  const view = sources.timesheets.month;
  if (view && (view.timesheet?.status ?? "draft") === "draft") {
    const monthName = MONTHS_PL[current.month - 1];
    const returned = Boolean(view.timesheet?.return_note);
    // Raport przyjmuje przełożony („akceptuje”) albo koordynator („potwierdza”) — D4.
    const reviewer = view.approver_name
      ? `${employmentTerms(sources.employmentType).review_verb} ${shortName(view.approver_name)}`
      : "";
    items.push({
      key: "ts-current",
      title: `${returned ? "Popraw" : "Wyślij"} ${form} za ${monthName}`,
      detail: returned ? "zwrócono do poprawy" : reviewer,
      due: `do ${formatDayMonthPl(view.deadline)}`,
      action: returned ? "Popraw" : "Wyślij",
      tab: "month",
      month: { year: current.year, month: current.month },
    });
  }
  return items;
}
