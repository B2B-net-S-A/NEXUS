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
import type { MonthView, TimesheetHistoryItem } from "@/lib/api/hr-time";
import { MONTHS_PL, formatDayMonthPl, monthYearPl, type YearMonth } from "@/lib/date-pl";
import { timesheetAccusative } from "@/lib/hr-employment-terms";
import { formatMoney } from "@/lib/money";

import { cancelReasonLabel } from "../payroll/payroll-format";

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

function payoutLabel(year: number, month: number, closed: boolean, currentYear: number): string {
  const suffix = year === currentYear ? "" : ` ${year}`;
  return closed
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
  };
  if (row.status === "cancelled") {
    const reason = cancelReasonLabel(row.cancel_reason, requiredDays);
    return {
      ...base,
      cancelled: true,
      stages: [{ label: "anulowana", state: "current" }],
      when: reason ?? "anulowana",
    };
  }
  const payout = payoutLabel(row.period_year, row.period_month, Boolean(row.period_closed), currentYear);
  if (row.status === "assigned") {
    const who = row.assigned_by_name ? ` · ${row.assigned_by_name}` : "";
    const when = row.assigned_at ? `przyznano ${formatDayMonthPl(row.assigned_at.slice(0, 10))}${who}` : "przyznana";
    const labels = placement
      ? ["umowa", `${requiredDays} dni`, "przyznana", payout]
      : ["przyznana", payout];
    return {
      ...base,
      stages: stages(labels, row.period_closed ? labels.length : labels.length - 1),
      when,
    };
  }
  // Propozycja: placement przed terminem albo czekająca na decyzję Płac.
  const required = row.business_days_required ?? requiredDays;
  const beforeDeadline = row.eligible === false;
  if (placement) {
    const labels = [
      "umowa",
      beforeDeadline ? daysStage(row.business_days_elapsed, required) : `${required} dni`,
      "decyzja Płac",
      "wypłata",
    ];
    const current = !beforeDeadline ? 2 : (row.business_days_elapsed ?? 0) > 0 ? 1 : 0;
    if (current === 0) labels[0] = "umowa podpisana";
    return {
      ...base,
      inTransit: true,
      stages: stages(labels, current),
      when: row.eligible_on
        ? beforeDeadline
          ? `od ${formatDayMonthPl(row.eligible_on)}`
          : "czeka na decyzję Płac"
        : "czeka na decyzję Płac",
    };
  }
  return {
    ...base,
    inTransit: true,
    stages: stages(["propozycja", "decyzja Płac", "wypłata"], 1),
    when: "czeka na decyzję Płac",
  };
}

/** Prognoza z podpisanej umowy (bez wiersza w bazie): kwota to szacunek „~”. */
export function bonusItemFromForecast(item: BonusForecast): MyBonusItem {
  const labels = [
    item.started ? "umowa" : "umowa podpisana",
    item.started
      ? daysStage(item.business_days_elapsed, item.business_days_required)
      : `${item.business_days_required} dni`,
    "decyzja Płac",
    "wypłata",
  ];
  return {
    key: item.key,
    title: `Placement: ${placementLabel(item.description) ?? "konsultant"}`,
    subtitle: item.category_label,
    stages: stages(labels, item.started ? 1 : 0),
    amount: item.amount,
    currency: item.currency,
    estimate: true,
    when: item.started
      ? `~ od ${formatDayMonthPl(item.eligible_on)}`
      : `~ od ${formatDayMonthPl(item.eligible_on)} (start ${formatDayMonthPl(item.start_date)})`,
    cancelled: false,
    inTransit: true,
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
  detail: string;
  href?: string;
  /** Zakładka „Mojego czasu” do otwarcia, gdy pozycja nie ma linku. */
  tab?: "month";
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
      detail: [task.person_name, task.due_date ? `do ${formatDayMonthPl(task.due_date)}` : null]
        .filter(Boolean)
        .join(" · "),
      href: task.link,
      overdue: task.overdue,
    });
  }
  for (const protocol of sources.protocols ?? []) {
    if (protocol.status !== "oczekuje") continue;
    items.push({
      key: `protocol-${protocol.id}`,
      title: `Podpisz protokół ${protocol.number}`,
      detail: `Recepcja · link w mailu · z ${formatDayMonthPl(protocol.protocol_date)}`,
    });
  }
  if (!sources.timesheets) return items;
  for (const item of sources.timesheets.history) {
    const older = item.year * 12 + item.month < current.year * 12 + current.month;
    if (older && item.status === "draft") {
      items.push({
        key: `ts-${item.id}`,
        title: `Wyślij ${form} za ${monthYearPl(item)}`,
        detail: "termin minął",
        tab: "month",
        overdue: true,
      });
    }
  }
  const view = sources.timesheets.month;
  if (view && (view.timesheet?.status ?? "draft") === "draft") {
    const monthName = MONTHS_PL[current.month - 1];
    const returned = Boolean(view.timesheet?.return_note);
    items.push({
      key: "ts-current",
      title: `${returned ? "Popraw" : "Wyślij"} ${form} za ${monthName}`,
      detail: returned
        ? `zwrócono do poprawy · do ${formatDayMonthPl(view.deadline)}`
        : `do ${formatDayMonthPl(view.deadline)}`,
      tab: "month",
    });
  }
  return items;
}
