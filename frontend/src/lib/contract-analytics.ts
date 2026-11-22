/**
 * Analityka kontraktów (wariant A z tabelą z wariantu B, decyzja Artura
 * z 19.11.2026, makiety modułu Kontrakty): cztery liczby, „Najbliższe
 * 3 miesiące”, smukła linia prognozy marży i tabela „kto ile przynosi”.
 * Tu są reguły tych bloków; strona i komponenty tylko je renderują.
 *
 * Sumy firmy liczy serwer (`/api/contract-analytics/*`, waluty przeliczone
 * kursem NBP). Okno 90 dni bierze kontrakty z listy `/api/contracts` (te same
 * filtry co lista kontraktów) i liczy ich marżę z bieżących stawek wyłącznie
 * w PLN: kwot w innej walucie nie sumujemy bez przeliczenia, tylko je liczymy
 * osobno („poza sumą”).
 */

import { CONTRACT_TERMINATION_REASONS } from "@/lib/api";
import { formatPctPl } from "@/lib/money";
import { countPl } from "@/lib/plural-pl";
import { HOURS_PER_MONTH, MD_PER_MONTH } from "@/lib/work-time";

// ── Dane z `/api/contract-analytics/*` ─────────────────────────────────────

export interface MarginRow {
  candidate_id?: number;
  candidate_name?: string;
  client_id?: number;
  client_name?: string;
  active_contracts: number;
  total_monthly_margin: number;
  total_monthly_revenue: number;
  margin_pct: number | null;
  // Gdy true, backend pominął co najmniej jedną nogę bez kursu FX. Kwoty są
  // wtedy częściowe i nie wolno prezentować ich jak kompletnego agregatu.
  fx_missing?: boolean;
  // Kontrakty z przychodem bez stawki kosztowej — w przychodzie, poza marżą.
  contracts_without_cost_leg?: number;
  // Kontrakty bez stawki przychodowej — poza każdą kwotą wiersza (runda 10).
  contracts_without_revenue_leg?: number;
}

export interface MarginTotals {
  clients: number;
  active_contracts: number;
  total_monthly_revenue: number;
  total_monthly_margin: number;
  // Liczy serwer: marża / przychód kontraktów ze ZNANĄ marżą. Front nie
  // dzieli marży przez przychód — przychód obejmuje też kontrakty bez stawki
  // kosztowej, więc procent wychodził zaniżony.
  margin_pct: number | null;
  fx_missing: boolean;
  contracts_without_cost_leg?: number;
  contracts_without_revenue_leg?: number;
}

export interface UtilizationData {
  total_candidates: number;
  candidates_active: number;
  active_contracts: number;
  candidates_on_bench: number;
  utilization_pct: number | null;
  avg_bench_days: number | null;
}

export interface ForecastMonth {
  month: string;
  month_label: string;
  revenue: number;
  margin: number;
  active_count: number;
}

export interface Forecast {
  horizon_months: number;
  months: ForecastMonth[];
  // Backend CELOWO degraduje prognozę, gdy brakuje kursu NBP: kwoty w tych
  // walutach są POMIJANE, nie przeliczane 1:1.
  fx_missing?: boolean;
  fx_warnings?: string[];
}

/** Kontrakt z listy `/api/contracts` — tylko pola, których używa okno 90 dni. */
export interface WindowContract {
  id: number;
  candidate_id: number | null;
  candidate_name: string | null;
  client_id: number;
  client_name: string | null;
  start_date: string | null;
  end_date: string | null;
  rate_client: number | null;
  rate_candidate: number | null;
  /** Stawka klienta − stawka kandydata w tej samej walucie (inaczej `null`). */
  margin?: number | null;
  currency?: string | null;
  rate_client_currency?: string | null;
  rate_candidate_currency?: string | null;
  rate_unit?: string | null;
  billing_hours_per_month?: number | null;
  termination_reason?: string | null;
  prolongation_status?: string | null;
}

// ── Liczby na górze ────────────────────────────────────────────────────────

/** Zdanie o kontraktach bez stawki przychodowej — poza każdą sumą (runda 10). */
export function withoutRevenueNote(count: number | undefined): string | undefined {
  const n = count ?? 0;
  if (n <= 0) return undefined;
  return `Niepełne: ${countPl(n, "kontrakt", "kontrakty", "kontraktów")} bez stawki przychodowej poza sumą`;
}

/** Podpis marży: procent od serwera i kontrakty bez jednej ze stawek. */
export function marginFigureNote(
  totals:
    | Pick<MarginTotals, "margin_pct" | "contracts_without_cost_leg" | "contracts_without_revenue_leg">
    | undefined,
): string | undefined {
  if (!totals) return undefined;
  const parts: string[] = [];
  if (totals.margin_pct != null) parts.push(`${formatPctPl(totals.margin_pct)} z przychodu`);
  const withoutCost = totals.contracts_without_cost_leg ?? 0;
  if (withoutCost > 0) {
    parts.push(
      `${countPl(withoutCost, "kontrakt", "kontrakty", "kontraktów")} bez stawki kosztowej poza marżą`,
    );
  }
  const withoutRevenue = withoutRevenueNote(totals.contracts_without_revenue_leg);
  if (withoutRevenue) parts.push(withoutRevenue);
  return parts.length > 0 ? parts.join(" · ") : undefined;
}

// ── Okno 90 dni ────────────────────────────────────────────────────────────

/** „Najbliższe 3 miesiące” — 90 dni, jak filtr listy „kończy się w 90 dni”. */
export const WINDOW_DAYS = 90;

/** Data ISO przesunięta o `days` dni (arytmetyka w UTC, bez strefy). */
export function addDaysIso(iso: string, days: number): string {
  return new Date(Date.parse(`${iso.slice(0, 10)}T00:00:00Z`) + days * 86_400_000)
    .toISOString()
    .slice(0, 10);
}

/** Ile dni od `from` do `to` (ujemne = minęło). */
export function daysBetweenIso(from: string, to: string): number {
  return Math.round(
    (Date.parse(`${to.slice(0, 10)}T00:00:00Z`) - Date.parse(`${from.slice(0, 10)}T00:00:00Z`)) /
      86_400_000,
  );
}

function legCurrency(c: WindowContract, leg: "client" | "candidate"): string {
  const own = leg === "client" ? c.rate_client_currency : c.rate_candidate_currency;
  return (own || c.currency || "PLN").toUpperCase();
}

/** Dlaczego marży kontraktu nie liczymy: brak stawek (albo ukryte) lub inna waluta. */
export function windowMarginGap(c: WindowContract): "no_rates" | "other_currency" | null {
  if (c.rate_client == null || c.rate_candidate == null) return "no_rates";
  if (legCurrency(c, "client") !== "PLN" || legCurrency(c, "candidate") !== "PLN") {
    return "other_currency";
  }
  return null;
}

/**
 * Marża miesięczna kontraktu w PLN z bieżących stawek — ta sama reguła co
 * `Contract.monthly_rate` w backendzie: godzinowa × godziny rozliczeniowe
 * (domyślnie 168), MD × 21, miesięczna bez zmian. Brak stawki, kwoty ukryte
 * albo waluta inna niż PLN → `null` (nie przeliczamy i nie udajemy zera).
 */
export function windowMonthlyMargin(c: WindowContract): number | null {
  if (windowMarginGap(c) !== null) return null;
  const perUnit = c.margin ?? (c.rate_client as number) - (c.rate_candidate as number);
  const factor =
    c.rate_unit === "monthly"
      ? 1
      : c.rate_unit === "daily"
        ? MD_PER_MONTH
        : c.billing_hours_per_month || HOURS_PER_MONTH;
  return perUnit * factor;
}

export interface WindowSummary {
  contracts: number;
  people: number;
  /** Suma marż znanych (PLN). */
  margin: number;
  withoutRates: number;
  otherCurrency: number;
}

export function summarizeWindow(items: WindowContract[]): WindowSummary {
  const people = new Set(items.map((c) => (c.candidate_id != null ? `p${c.candidate_id}` : `c${c.id}`)));
  let margin = 0;
  let withoutRates = 0;
  let otherCurrency = 0;
  for (const c of items) {
    const gap = windowMarginGap(c);
    if (gap === "no_rates") withoutRates += 1;
    else if (gap === "other_currency") otherCurrency += 1;
    else margin += windowMonthlyMargin(c) ?? 0;
  }
  return { contracts: items.length, people: people.size, margin, withoutRates, otherCurrency };
}

/** „2 kontrakty bez stawek — ich marży nie liczymy · 1 w innej walucie — poza sumą”. */
export function windowGapNote(summary: WindowSummary): string | null {
  const parts: string[] = [];
  if (summary.withoutRates > 0) {
    parts.push(
      `${countPl(summary.withoutRates, "kontrakt", "kontrakty", "kontraktów")} bez stawek — ich marży nie liczymy`,
    );
  }
  if (summary.otherCurrency > 0) {
    parts.push(
      `${countPl(summary.otherCurrency, "kontrakt", "kontrakty", "kontraktów")} w innej walucie — poza sumą`,
    );
  }
  return parts.length > 0 ? parts.join(" · ") : null;
}

/** Powód końca albo decyzja o przedłużeniu — małą literą, do drugiej linii wiersza. */
export function endingNote(c: WindowContract): string {
  if (c.termination_reason) {
    const label =
      CONTRACT_TERMINATION_REASONS.find((r) => r.value === c.termination_reason)?.label ??
      c.termination_reason;
    return label.toLowerCase();
  }
  if (c.prolongation_status === "yes") return "klient przedłuża";
  if (c.prolongation_status === "no") return "klient nie przedłuża";
  if (c.prolongation_status === "negotiate") return "w negocjacjach";
  return "bez decyzji o przedłużeniu";
}

/** „9 z zapisanym powodem końca · 4 bez decyzji o przedłużeniu · 1 klient przedłuża”. */
export function endingDecisionLine(items: WindowContract[]): string {
  const decided = items.filter((c) => c.termination_reason || c.prolongation_status === "no").length;
  const extending = items.filter((c) => !c.termination_reason && c.prolongation_status === "yes").length;
  const open = items.length - decided - extending;
  return [
    decided ? `${decided} z decyzją o końcu` : null,
    open ? `${open} bez decyzji o przedłużeniu` : null,
    extending ? `${extending} klient przedłuża` : null,
  ]
    .filter(Boolean)
    .join(" · ");
}

/** Najbliższe najpierw; przy tej samej dacie większa marża wyżej. */
export function sortWindow(items: WindowContract[], dateKey: "end_date" | "start_date"): WindowContract[] {
  return [...items].sort(
    (a, b) =>
      (a[dateKey] ?? "").localeCompare(b[dateKey] ?? "") ||
      (windowMonthlyMargin(b) ?? -Infinity) - (windowMonthlyMargin(a) ?? -Infinity),
  );
}

// ── Tabela „kto ile przynosi” ──────────────────────────────────────────────

export type SortDir = "asc" | "desc";

export interface SortState<K extends string> {
  key: K;
  dir: SortDir;
}

/** Puste wartości zawsze na końcu, niezależnie od kierunku. */
export function compareNullable(
  a: string | number | null | undefined,
  b: string | number | null | undefined,
  dir: SortDir,
): number {
  const aEmpty = a == null || a === "";
  const bEmpty = b == null || b === "";
  if (aEmpty && bEmpty) return 0;
  if (aEmpty) return 1;
  if (bEmpty) return -1;
  const r =
    typeof a === "string" && typeof b === "string" ? a.localeCompare(b, "pl") : Number(a) - Number(b);
  return dir === "asc" ? r : -r;
}

/** Klik w aktywną kolumnę odwraca kierunek; nowa kolumna: nazwa rosnąco, liczby malejąco. */
export function nextSort<K extends string>(current: SortState<K>, key: K): SortState<K> {
  if (current.key === key) return { key, dir: current.dir === "asc" ? "desc" : "asc" };
  return { key, dir: key === "name" ? "asc" : "desc" };
}

export interface ClientReportRow {
  clientId: number;
  name: string;
  /** Kontrakty żywe dziś; `null` = klient tylko ze startem w oknie. */
  contracts: number | null;
  revenue: number | null;
  margin: number | null;
  pct: number | null;
  fxMissing: boolean;
  withoutRevenue: number;
  withoutCost: number;
  ending: WindowContract[];
  starting: WindowContract[];
}

export type ClientSortKey = "name" | "contracts" | "revenue" | "margin" | "pct" | "ending" | "starting";

function groupByClient(items: WindowContract[]): Map<number, WindowContract[]> {
  const map = new Map<number, WindowContract[]>();
  for (const c of items) map.set(c.client_id, [...(map.get(c.client_id) ?? []), c]);
  return map;
}

/**
 * Wiersz na klienta z rankingiem marży (`margin-by-client`) i tym, co się
 * u niego zmieni w 90 dni. Klient, u którego dopiero ktoś startuje, nie ma
 * jeszcze marży, ale musi być widać, że przybywa — dostaje własny wiersz.
 * Kwot z `fx_missing` nie pokazujemy (są częściowe).
 */
export function buildClientReport(
  clients: MarginRow[],
  ending: WindowContract[],
  starting: WindowContract[],
): ClientReportRow[] {
  const endBy = groupByClient(ending);
  const startBy = groupByClient(starting);
  const rows: ClientReportRow[] = clients.map((r) => {
    const id = r.client_id ?? 0;
    const fx = r.fx_missing === true;
    return {
      clientId: id,
      name: r.client_name ?? "—",
      contracts: r.active_contracts,
      revenue: fx ? null : r.total_monthly_revenue,
      margin: fx ? null : r.total_monthly_margin,
      pct: fx ? null : r.margin_pct,
      fxMissing: fx,
      withoutRevenue: r.contracts_without_revenue_leg ?? 0,
      withoutCost: r.contracts_without_cost_leg ?? 0,
      ending: endBy.get(id) ?? [],
      starting: startBy.get(id) ?? [],
    };
  });
  const known = new Set(rows.map((r) => r.clientId));
  for (const c of [...ending, ...starting]) {
    if (known.has(c.client_id)) continue;
    known.add(c.client_id);
    rows.push({
      clientId: c.client_id,
      name: c.client_name ?? "—",
      contracts: null,
      revenue: null,
      margin: null,
      pct: null,
      fxMissing: false,
      withoutRevenue: 0,
      withoutCost: 0,
      ending: endBy.get(c.client_id) ?? [],
      starting: startBy.get(c.client_id) ?? [],
    });
  }
  return rows;
}

function clientSortValue(r: ClientReportRow, key: ClientSortKey): string | number | null {
  switch (key) {
    case "name":
      return r.name;
    case "contracts":
      return r.contracts;
    case "revenue":
      return r.revenue;
    case "margin":
      return r.margin;
    case "pct":
      return r.pct;
    case "ending":
      return r.ending.length || null;
    case "starting":
      return r.starting.length || null;
  }
}

export function sortClientReport(rows: ClientReportRow[], sort: SortState<ClientSortKey>): ClientReportRow[] {
  return [...rows].sort(
    (a, b) =>
      compareNullable(clientSortValue(a, sort.key), clientSortValue(b, sort.key), sort.dir) ||
      a.name.localeCompare(b.name, "pl"),
  );
}

export type PersonSortKey = "name" | "contracts" | "revenue" | "margin" | "pct" | "ending";

export function sortPeopleReport(
  rows: MarginRow[],
  sort: SortState<PersonSortKey>,
  endingByPerson: Map<number, WindowContract>,
): MarginRow[] {
  const value = (r: MarginRow): string | number | null => {
    const fx = r.fx_missing === true;
    switch (sort.key) {
      case "name":
        return r.candidate_name ?? null;
      case "contracts":
        return r.active_contracts;
      case "revenue":
        return fx ? null : r.total_monthly_revenue;
      case "margin":
        return fx ? null : r.total_monthly_margin;
      case "pct":
        return fx ? null : r.margin_pct;
      case "ending":
        return endingByPerson.get(r.candidate_id ?? -1)?.end_date ?? null;
    }
  };
  return [...rows].sort(
    (a, b) =>
      compareNullable(value(a), value(b), sort.dir) ||
      (a.candidate_name ?? "").localeCompare(b.candidate_name ?? "", "pl"),
  );
}

/** Najbliższy koniec umowy w oknie dla każdej osoby. */
export function endingByPerson(ending: WindowContract[]): Map<number, WindowContract> {
  const map = new Map<number, WindowContract>();
  for (const c of sortWindow(ending, "end_date")) {
    if (c.candidate_id != null && !map.has(c.candidate_id)) map.set(c.candidate_id, c);
  }
  return map;
}

// ── Prognoza ───────────────────────────────────────────────────────────────

/**
 * Etykieta miesiąca prognozy po polsku („wrz 2026”). Backend składa
 * `month_label` przez `strftime("%b %Y")`, czyli w locale procesu — na
 * produkcji po angielsku („Sep 2026”). `month` (RRRR-MM) jest stabilny.
 */
export function forecastMonthLabel(month: string, fallback: string): string {
  const match = /^(\d{4})-(\d{2})$/.exec(month);
  if (!match) return fallback;
  const date = new Date(Number(match[1]), Number(match[2]) - 1, 1);
  return new Intl.DateTimeFormat("pl-PL", { month: "short", year: "numeric" })
    .format(date)
    .replace(".", "");
}

/**
 * Oś pionowa przycięta do zakresu zmian: najwyższy punkt na 30 % wysokości,
 * najniższy na 80 % — zmiana marży o 2–3 % nie jest płaską kreską. Płaska
 * seria dostaje sztuczny zakres 1 %, żeby nie dzielić przez zero.
 */
export function forecastAxis(values: number[]): { hi: number; lo: number } {
  if (values.length === 0) return { hi: 1, lo: 0 };
  const max = Math.max(...values);
  const min = Math.min(...values);
  const range = max - min || Math.max(1, Math.abs(max) * 0.01);
  const hi = max + range * 0.6;
  return { hi, lo: hi - range * 2 };
}

/** Zmiana marży od pierwszego do ostatniego miesiąca: kwota i procent. */
export function forecastChange(months: ForecastMonth[]): { change: number; pct: number | null } | null {
  if (months.length < 2) return null;
  const first = months[0].margin;
  const last = months[months.length - 1].margin;
  return { change: last - first, pct: first ? ((last - first) / Math.abs(first)) * 100 : null };
}
