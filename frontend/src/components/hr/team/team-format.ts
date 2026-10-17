// „Mój zespół” — teksty komórek (czyste funkcje, testowalne bez zapytań).
//
// `null` z serwera = moduł wyłączony albo brak prawa → „—”, nigdy „0”.

import { daysLabel, formatRange } from "@/components/hr/leave/leave-format";
import type { EmploymentType } from "@/lib/api/hr";
import type {
  MyTeam,
  TeamBonuses,
  TeamLeave,
  TeamPerson,
  TeamToday,
} from "@/lib/api/hr-team";
import { TIMESHEET_STATUS_LABELS } from "@/lib/api/hr-time";
import { formatWeekdayDayPl, monthYearPl } from "@/lib/date-pl";
import { formatMoney } from "@/lib/money";
import { countPl } from "@/lib/plural-pl";

export interface Cell {
  text: string;
  sub?: string;
  tone?: "warning" | "muted";
}

const DASH: Cell = { text: "—", tone: "muted" };

/** Dziś: „w pracy” albo rodzaj nieobecności do kiedy (rodzaj widzi krąg D6). */
export function todayCell(today: TeamToday | null, coveringFor: readonly string[]): Cell {
  if (!today) return DASH;
  const covering = coveringFor.length ? `zastępuje: ${coveringFor.join(", ")}` : undefined;
  if (!today.absent) return { text: "w pracy", sub: covering };
  const kind = today.leave_type_label ?? "Nieobecność";
  const half = today.half_day ? " (pół dnia)" : "";
  return {
    text: `${kind}${half} do ${formatWeekdayDayPl(today.until ?? null)}`,
    sub: today.substitute_name ? `zastępca: ${today.substitute_name}` : covering,
    tone: "warning",
  };
}

/**
 * Nieobecności: pula tylko u osób z płatną pulą (UoP albo B2B z umowną pulą
 * > 0 — sam wiersz z zerem to nie pula), u reszty zaplanowane dni (decyzja
 * Artura 17.10.2026).
 */
export function leaveCell(leave: TeamLeave | null, form?: EmploymentType): Cell {
  if (!leave) return DASH;
  const planned = Number(leave.planned_days);
  const pending = Number(leave.pending_days);
  const parts: string[] = [];
  if (planned > 0) parts.push(`zaplanowane ${daysLabel(planned)}`);
  if (pending > 0) parts.push(`czeka ${daysLabel(pending)}`);
  if (leave.has_paid_pool && leave.remaining_days !== null) {
    return {
      // Pula B2B jest umowna — „urlop” tylko przy umowie o pracę (D4).
      text: `zostało ${daysLabel(leave.remaining_days)} ${form && form !== "uop" ? "z puli" : "urlopu"}`,
      sub: parts.join(" · ") || undefined,
    };
  }
  if (parts.length === 0) return { text: "nic zaplanowanego", tone: "muted" };
  return { text: parts[0], sub: parts.slice(1).join(" · ") || undefined };
}

/** „121/176 h · szkic” — status timesheetu ze wspólnego słownika. */
export function monthCell(person: TeamPerson, team: MyTeam): Cell {
  if (!team.month) return DASH;
  if (!person.month) {
    return person.timesheet_required ? DASH : { text: "bez timesheetu", tone: "muted" };
  }
  const hours = person.month.hours.toLocaleString("pl-PL", { maximumFractionDigits: 1 });
  return {
    text: `${hours}/${team.month.norm_hours} h`,
    sub: TIMESHEET_STATUS_LABELS[person.month.status].toLowerCase(),
  };
}

/** Premie w drodze: liczba i suma (bez stawek, D2); propozycje do wiadomości. */
export function bonusCell(bonuses: TeamBonuses | null): Cell {
  if (!bonuses || bonuses.count === 0) return DASH;
  const total = bonuses.totals.map((item) => formatMoney(item.amount, item.currency)).join(" + ");
  return {
    text: `${bonuses.count} · ${total}`,
    sub: bonuses.proposals
      ? `${countPl(bonuses.proposals, "propozycja", "propozycje", "propozycji")} — decydują Płace`
      : undefined,
  };
}

/** Rzeczy do decyzji: wnioski („wniosek 23–31.12.2026”) i timesheety („timesheet: październik 2026”). */
export function decisionItems(person: TeamPerson): { key: string; text: string; href: string }[] {
  const leave = person.to_decide.leave_requests.map((item) => ({
    key: `leave-${item.id}`,
    text: `wniosek ${formatRange(item.start_date, item.end_date)}`,
    href: "/people/approvals",
  }));
  const timesheets = person.to_decide.timesheets.map((item) => ({
    key: `timesheet-${item.id}`,
    text: `timesheet: ${monthYearPl(item)}`,
    href: item.link,
  }));
  return [...leave, ...timesheets];
}
