// „Kończące się” jako odejścia do domknięcia (przebudowa 20.11.2026, wariant A
// z osią czasu z B). Zbiór liczy serwer (`bucket=ending`: status „Kończący
// się” albo żywa umowa z końcem w 30 dni); tu tylko to, co z niego widać:
// ostatni dzień, stan umowy B2B, niespójność z zamówieniem i oś czasu.
import { fmtDatePl } from "@/lib/contract-happening";
import { agreementOpen, sumMonthlyMarginPln, type ListRowFacts } from "@/lib/contract-list-next";

export interface EndingRowFacts extends ListRowFacts {
  id: number;
  candidate_id?: number | null;
  latest_order_end_date?: string | null;
}

/** Ostatni dzień pracy: koniec umowy, a bez niego koniec zamówienia. */
export function lastWorkingDay(f: EndingRowFacts): string | null {
  const day = f.end_date ?? f.terminated_at ?? f.client_order_end_date ?? f.latest_order_end_date ?? null;
  return day ? day.slice(0, 10) : null;
}

export type AgreementState = "open" | "notice" | "mutual_agreement" | "not_applicable";

export function agreementState(f: ListRowFacts): AgreementState {
  if (f.contract_type !== "b2b") return "not_applicable";
  if (agreementOpen(f)) return "open";
  return f.agreement_termination_mode === "notice" ? "notice" : "mutual_agreement";
}

export const AGREEMENT_STATE_LABEL: Record<AgreementState, string> = {
  open: "nierozwiązana",
  notice: "wypowiedziana",
  mutual_agreement: "rozwiązana porozumieniem",
  not_applicable: "nie dotyczy",
};

/**
 * Co się nie zgadza: zamówienie klienta trwa po ostatnim dniu (także
 * zamówienie bez daty końca). Zakończenie skraca otwarte zamówienia, więc
 * taki stan to zwykle zamówienie dopisane po zakończeniu albo zła data.
 */
export function orderConflict(f: EndingRowFacts): string | null {
  const last = lastWorkingDay(f);
  const orderStart = f.client_order_start_date?.slice(0, 10);
  if (!last || !orderStart) return null;
  const orderEnd = f.client_order_end_date?.slice(0, 10) ?? null;
  if (orderEnd && orderEnd <= last) return null;
  return orderEnd
    ? `Zamówienie ${fmtDatePl(orderStart)} – ${fmtDatePl(orderEnd)} trwa po odejściu — sprawdź zakończenie`
    : `Zamówienie od ${fmtDatePl(orderStart)} bez daty końca trwa po odejściu — sprawdź zakończenie`;
}

/** Odejścia od najbliższego ostatniego dnia; bez daty na końcu. */
export function sortByLastDay<T extends EndingRowFacts>(rows: readonly T[]): T[] {
  return [...rows].sort((a, b) => {
    const da = lastWorkingDay(a);
    const db = lastWorkingDay(b);
    if (da === db) return a.id - b.id;
    if (!da) return 1;
    if (!db) return -1;
    return da.localeCompare(db);
  });
}

export interface EndingSummary {
  contracts: number;
  people: number;
  latest: string | null;
  margin: { total: number; unpriced: number };
  b2b: number;
  openAgreements: number;
}

export function endingSummary(rows: readonly EndingRowFacts[]): EndingSummary {
  const days = rows.map(lastWorkingDay).filter((d): d is string => Boolean(d)).sort();
  const b2b = rows.filter((row) => row.contract_type === "b2b");
  return {
    contracts: rows.length,
    people: new Set(rows.map((row) => (row.candidate_id != null ? `c${row.candidate_id}` : `k${row.id}`))).size,
    latest: days.length ? days[days.length - 1] : null,
    margin: sumMonthlyMarginPln(rows),
    b2b: b2b.length,
    openAgreements: b2b.filter(agreementOpen).length,
  };
}

// ── Oś czasu ────────────────────────────────────────────────────────────────

const ms = (iso: string) => Date.parse(`${iso.slice(0, 10)}T00:00:00Z`);

export function monthStart(iso: string): string {
  return `${iso.slice(0, 7)}-01`;
}

export function addMonths(iso: string, n: number): string {
  const d = new Date(`${iso.slice(0, 10)}T00:00:00Z`);
  d.setUTCDate(1);
  d.setUTCMonth(d.getUTCMonth() + n);
  return d.toISOString().slice(0, 10);
}

export interface TimelineScale {
  from: string;
  to: string;
  /** Pierwsze dni kolejnych miesięcy na osi. */
  months: string[];
  /** Pozycja dnia na osi w procentach (0–100, poza zakresem przycięta). */
  pos: (iso: string) => number;
}

/**
 * Oś od początku bieżącego miesiąca do końca miesiąca po najpóźniejszym
 * odejściu (co najmniej dwa miesiące, żeby pasek nie był kreską). Zamówienie
 * trwające po odejściu nie poszerza osi — przerywany pasek dochodzi do końca.
 */
export function timelineScale(today: string, lastDays: readonly (string | null)[]): TimelineScale {
  const from = monthStart(today);
  const latest = lastDays.reduce<string>((max, day) => (day && day > max ? day : max), today);
  const to = addMonths(monthStart(latest), latest.slice(0, 7) === today.slice(0, 7) ? 2 : 1);
  const span = ms(to) - ms(from);
  const months: string[] = [];
  for (let m = from; m < to; m = addMonths(m, 1)) months.push(m);
  return {
    from,
    to,
    months,
    pos: (iso: string) => Math.min(100, Math.max(0, ((ms(iso) - ms(from)) / span) * 100)),
  };
}

const MONTH_YEAR = new Intl.DateTimeFormat("pl-PL", { month: "long", year: "numeric", timeZone: "UTC" });

/** „Listopad 2026”. */
export function monthYearLabel(iso: string): string {
  const text = MONTH_YEAR.format(new Date(`${iso.slice(0, 7)}-01T00:00:00Z`));
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** Odejścia w grupach po miesiącu ostatniego dnia (kolejność zachowana). */
export function groupByMonth<T extends EndingRowFacts>(rows: readonly T[]): { month: string; rows: T[] }[] {
  const out: { month: string; rows: T[] }[] = [];
  for (const row of rows) {
    const day = lastWorkingDay(row);
    const month = day ? day.slice(0, 7) : "";
    const last = out[out.length - 1];
    if (last && last.month === month) last.rows.push(row);
    else out.push({ month, rows: [row] });
  }
  return out;
}
