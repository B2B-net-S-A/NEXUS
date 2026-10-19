// Kartoteka osoby wg makiety 19.10.2026 (kanwa „Ludzie i Sprzęt”, n_pe2):
// zakładki, pierścień dni przerwy, premie roku i oś „Ostatnio”. Czyste
// funkcje — testy bez zapytań (`__tests__/person-view.test.ts`).

import type { AssignmentRow } from "@/lib/api/equipment";
import type { LeaveRing } from "@/lib/api/hr";
import type { BonusRow, RateRow } from "@/lib/api/hr-payroll";
import { formatMoney } from "@/lib/money";

export type ProfileTab =
  | "overview"
  | "time"
  | "payroll"
  | "documents"
  | "agreements"
  | "equipment"
  | "history";

/**
 * Zakładka z adresu: `#place` (dzwonek Płac „stawka z umowy do przepisania”)
 * otwiera „Płace i premie”, `#dokumenty`, `#umowy`, `#sprzet` — swoje.
 */
export function tabFromHash(hash: string): ProfileTab {
  switch (hash.replace(/^#/, "")) {
    case "place":
      return "payroll";
    case "dokumenty":
      return "documents";
    case "umowy":
      return "agreements";
    case "sprzet":
      return "equipment";
    case "czas":
      return "time";
    case "historia":
      return "history";
    default:
      return "overview";
  }
}

export const TAB_HASH: Record<ProfileTab, string> = {
  overview: "",
  time: "czas",
  payroll: "place",
  documents: "dokumenty",
  agreements: "umowy",
  equipment: "sprzet",
  history: "historia",
};

export interface RingParts {
  pool: number;
  used: number;
  planned: number;
  remaining: number;
  /** Udział wykorzystanych i zaplanowanych w puli (0–100) — do `conic-gradient`. */
  usedPct: number;
  plannedPct: number;
}

function num(value: string | number | null | undefined): number {
  const parsed = Number(value ?? 0);
  return Number.isFinite(parsed) ? parsed : 0;
}

/** Pierścień „wykorzystane / zaplanowane / zostało”; bez puli = `null`. */
export function ringParts(balance: LeaveRing | null | undefined): RingParts | null {
  if (!balance || !balance.has_paid_pool) return null;
  const pool = num(balance.entitlement_days) + num(balance.carried_over_days);
  if (pool <= 0) return null;
  const used = num(balance.used_days);
  const planned = num(balance.planned_days);
  const remaining = num(balance.remaining_days);
  const clamp = (value: number) => Math.max(0, Math.min(100, value));
  const usedPct = clamp((used / pool) * 100);
  const plannedPct = clamp(Math.min((planned / pool) * 100, 100 - usedPct));
  return { pool, used, planned, remaining, usedPct, plannedPct };
}

export interface BonusTotals {
  granted: number;
  waiting: number;
  currency: string;
  waitingCount: number;
}

/** Premie roku: przyznane i czekające (propozycje); anulowane się nie liczą. */
export function bonusTotals(bonuses: readonly BonusRow[], year: number): BonusTotals {
  let granted = 0;
  let waiting = 0;
  let waitingCount = 0;
  let currency = "PLN";
  for (const bonus of bonuses) {
    if (bonus.period_year !== year || bonus.status === "cancelled") continue;
    currency = bonus.currency;
    if (bonus.status === "assigned") granted += num(bonus.amount);
    else {
      waiting += num(bonus.amount);
      waitingCount += 1;
    }
  }
  return { granted, waiting, currency, waitingCount };
}

/** Poprzednia stawka przed bieżącą (do „było 110”). */
export function previousRate(
  rates: readonly RateRow[],
  current: RateRow | null | undefined,
): RateRow | null {
  if (!current) return null;
  const earlier = rates
    .filter((rate) => rate.id !== current.id && rate.effective_from < current.effective_from)
    .sort((a, b) => b.effective_from.localeCompare(a.effective_from));
  return earlier[0] ?? null;
}

export type TimelineTone = "success" | "primary" | "neutral" | "warning";

export interface TimelineEntry {
  key: string;
  date: string;
  title: string;
  detail: string | null;
  tone: TimelineTone;
}

export interface TimelineInput {
  workStart?: string | null;
  lastWorkingDay?: string | null;
  rates?: readonly RateRow[];
  bonuses?: readonly BonusRow[];
  equipment?: readonly AssignmentRow[];
  today: string;
}

/**
 * Oś „Ostatnio” — zmiany stawki, premie, wydania sprzętu, start i odejście,
 * najnowsze na górze. Tylko z danych, które patrzący już dostał z serwera
 * (stawki tylko Płace — przełożony ich nie ma, D2).
 */
export function buildTimeline(input: TimelineInput): TimelineEntry[] {
  const entries: TimelineEntry[] = [];
  const rates = [...(input.rates ?? [])].sort((a, b) =>
    a.effective_from.localeCompare(b.effective_from),
  );
  rates.forEach((rate, index) => {
    const first = index === 0;
    entries.push({
      key: `rate-${rate.id}`,
      date: rate.effective_from,
      title: `${first ? "Stawka startowa" : "Nowa stawka"} · ${formatMoney(rate.hourly_rate, rate.currency)}/h`,
      detail: rate.reason,
      tone: first ? "neutral" : "primary",
    });
  });
  for (const bonus of input.bonuses ?? []) {
    if (bonus.status === "cancelled") continue;
    const date =
      bonus.eligible_on ?? `${bonus.period_year}-${String(bonus.period_month).padStart(2, "0")}-01`;
    entries.push({
      key: `bonus-${bonus.id}`,
      date,
      title: `${bonus.category_label} · ${formatMoney(bonus.amount, bonus.currency)}`,
      detail: bonus.status === "assigned" ? "przyznana" : "propozycja — czeka na Płace",
      tone: bonus.status === "assigned" ? "success" : "warning",
    });
  }
  const issues = new Map<string, AssignmentRow[]>();
  for (const row of input.equipment ?? []) {
    const key = row.issue_protocol ?? `${row.issued_at.slice(0, 10)}-${row.assignment_id}`;
    issues.set(key, [...(issues.get(key) ?? []), row]);
  }
  for (const [key, rows] of issues) {
    entries.push({
      key: `eq-${key}`,
      date: rows[0].issued_at.slice(0, 10),
      title: `Wydanie sprzętu · ${rows.length} ${rows.length === 1 ? "pozycja" : rows.length < 5 ? "pozycje" : "pozycji"}`,
      detail: rows[0].issue_protocol,
      tone: "neutral",
    });
  }
  if (input.workStart && input.workStart <= input.today) {
    entries.push({
      key: "start",
      date: input.workStart,
      title: "Start pracy",
      detail: null,
      tone: "neutral",
    });
  }
  if (input.lastWorkingDay) {
    entries.push({
      key: "exit",
      date: input.lastWorkingDay,
      title: input.lastWorkingDay < input.today ? "Ostatni dzień pracy" : "Ostatni dzień pracy (zaplanowany)",
      detail: null,
      tone: "warning",
    });
  }
  return entries.sort((a, b) => b.date.localeCompare(a.date) || a.key.localeCompare(b.key));
}
