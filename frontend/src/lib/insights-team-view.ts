/**
 * Zakładka Zespół (05.11.2026): zdanie z odpowiedzią, tempo, kolejność sygnałów,
 * grupy osób i serie przejść w czasie. Czyste funkcje: widok tylko rysuje,
 * a reguły mają test (`__tests__/insights-team-view.test.ts`).
 */

import type {
  InFlightColumn,
  InFlightResponse,
  MonthlyTrendResponse,
  RecruitmentFunnelResponse,
  TeamGoalsResponse,
  WeeklyTrendResponse,
} from "@/lib/insights-api";
import { forecastLabel, monthForecast } from "@/lib/insights-in-flight";
import type { TeamAttentionItem, TeamPeopleRow } from "@/lib/insights-team-api";
import { reportHref, type ReportId } from "@/lib/insights-reports";
import { countPl } from "@/lib/plural-pl";
import type { WhoCountsMetric } from "@/lib/kpi-who-counts";

export type TrendStageKey = "verified" | "cv_sent" | "client_interview" | "acceptance" | "hired";

export interface TeamStage {
  stage: TrendStageKey;
  label: string;
  shortLabel: string;
  metric: WhoCountsMetric;
  rowKey: "verifications" | "recommendations" | "interviews" | "acceptances" | "placements";
  column: InFlightColumn["column"] | null;
  waits: string;
}

export const TEAM_STAGES: readonly TeamStage[] = [
  { stage: "verified", label: "Weryfikacje", shortLabel: "Weryfikacje", metric: "verification", rowKey: "verifications", column: "cv_qc", waits: "czeka na wysyłkę CV" },
  { stage: "cv_sent", label: "Rekomendacje", shortLabel: "Rekomendacje", metric: "recommendation", rowKey: "recommendations", column: "cv_sent", waits: "czeka na decyzję klienta" },
  { stage: "client_interview", label: "Rozmowy u klienta", shortLabel: "Rozmowy", metric: "interview", rowKey: "interviews", column: "client_interview", waits: "ma rozmowy w toku" },
  { stage: "acceptance", label: "Akceptacje", shortLabel: "Akceptacje", metric: "acceptance", rowKey: "acceptances", column: "contract", waits: "czeka na domknięcie" },
  { stage: "hired", label: "Placementy", shortLabel: "Placementy", metric: "placement", rowKey: "placements", column: null, waits: "" },
];

export function stageCount(funnel: RecruitmentFunnelResponse | undefined, stage: string): number {
  return funnel?.stages.find((s) => s.stage === stage)?.count ?? 0;
}

// ─── Okres ───────────────────────────────────────────────────────────────────

/**
 * Dni sprzed 12.10.2026 to tygodniowe wpisy DynaReportera z datą raportu:
 * „1–5 października” niesie 211 weryfikacji z ponad tygodnia, więc odcinek okresu,
 * który trwa, przegrywałby z nim zawsze. Okresy zamknięte porównują się uczciwie.
 */
export function isFairComparison(running: boolean, previousStart: string | undefined): boolean {
  return !(running && previousStart !== undefined && previousStart.slice(0, 10) < "2026-10-12");
}

function dayMonth(iso: string): string {
  return `${Number(iso.slice(8, 10))}.${iso.slice(5, 7)}`;
}

function dayBefore(iso: string): string {
  const day = new Date(`${iso.slice(0, 10)}T12:00:00Z`);
  day.setUTCDate(day.getUTCDate() - 1);
  return day.toISOString().slice(0, 10);
}

function dayMonthYear(iso: string): string {
  return `${dayMonth(iso)}.${iso.slice(0, 4)}`;
}

const QUARTER_NAMES = ["I", "II", "III", "IV"];

/** Zdanie jest jedynym podpisem okresu, więc nazwa niesie rok. */
export function periodName(window: RecruitmentFunnelResponse["period"]): string {
  const year = window.start.slice(0, 4);
  const month = Number(window.start.slice(5, 7));
  if (window.kind === "month") {
    const name = new Date(window.start).toLocaleDateString("pl-PL", {
      month: "long",
      year: "numeric",
      timeZone: "Europe/Warsaw",
    });
    return name.charAt(0).toUpperCase() + name.slice(1);
  }
  if (window.kind === "quarter") return `${QUARTER_NAMES[Math.floor((month - 1) / 3)]} kwartał ${year}`;
  if (window.kind === "year") return `Rok ${year}`;
  return `${dayMonthYear(window.start)} – ${dayMonthYear(dayBefore(window.end))}`;
}

/** Cele mają sens tylko w miesiącu albo tygodniu od 2026: wcześniej nikt tych etapów nie prowadził. */
function goalsApply(window: RecruitmentFunnelResponse["period"]): boolean {
  return (window.kind === "month" || window.kind === "week") && window.start.slice(0, 4) >= "2026";
}

export function stageCountedFrom(funnel: RecruitmentFunnelResponse | undefined, stage: string): string | null {
  return funnel?.stages.find((s) => s.stage === stage)?.counted_from ?? null;
}

/**
 * Okno kończy się przed dniem, od którego etap jest liczony: to „brak danych”,
 * nie 0. Akceptacje we wrześniu 2026 nie są zerem, tylko nikt ich nie prowadził.
 */
export function stageNotRecorded(funnel: RecruitmentFunnelResponse | undefined, stage: string): boolean {
  const from = stageCountedFrom(funnel, stage);
  return from !== null && funnel !== undefined && funnel.period.end.slice(0, 10) <= from;
}

// ─── Cel placementów zespołu ─────────────────────────────────────────────────

/** Osoby z celem w oknie miesiąca: suma celów i ich placementów, bez byłych członków zespołu. */
export function peopleWithGoal(rows: readonly TeamPeopleRow[]): { target: number; placements: number } | null {
  const withGoal = rows.filter((r) => r.is_active && (r.placements_target ?? 0) > 0);
  if (withGoal.length === 0) return null;
  return {
    target: withGoal.reduce((sum, r) => sum + (r.placements_target ?? 0), 0),
    placements: withGoal.reduce((sum, r) => sum + r.placements, 0),
  };
}

// ─── Zdanie z odpowiedzią ────────────────────────────────────────────────────

const placementsWord = (n: number) => countPl(n, "placement", "placementy", "placementów");

const STALL_PLACE: Record<InFlightColumn["column"], string> = {
  cv_qc: "przed wysyłką CV",
  cv_sent: "u klientów",
  client_interview: "na rozmowach",
  contract: "na akceptacjach",
};

export function worstColumn(inFlight: InFlightResponse | undefined): InFlightColumn | null {
  // Pary starsze niż `recent_days` to zwykle karty, których nikt nie zamknął, nie zator.
  const worst = [...(inFlight?.columns ?? [])].sort((a, b) => b.recent_stale_count - a.recent_stale_count)[0];
  return worst && worst.recent_stale_count > 0 ? worst : null;
}

export function teamVerdict(input: {
  window: RecruitmentFunnelResponse["period"];
  running: boolean;
  workdays: number | null;
  funnel: RecruitmentFunnelResponse;
  goals: TeamGoalsResponse | undefined;
  inFlight: InFlightResponse | undefined;
  rows: readonly TeamPeopleRow[];
}): { pace: string; stall: string | null } {
  const { window, running, workdays, funnel, goals, inFlight, rows } = input;
  const name = periodName(window);
  const hired = stageCount(funnel, "hired");
  const goal = goals?.goals.find((g) => g.goal_id === "team_monthly_placements");
  let pace = `${name}: ${placementsWord(hired)}.`;
  if (running && window.kind === "month" && goal?.target != null) {
    const day = workdays ? `, ${workdays}. dzień roboczy` : "";
    const forecast = inFlight ? forecastLabel(inFlight.forecast) : null;
    const total = inFlight ? monthForecast(hired, inFlight.forecast) : null;
    const plan = Math.round(goal.expected ?? 0);
    // Cel sumuje tylko osoby z celem, licznik całą firmę: obie liczby muszą stać obok siebie.
    pace =
      goal.current != null && goal.current !== hired
        ? `${name}${day}: ${placementsWord(hired)} w firmie, ${goal.current} u osób z celem przy planie ${plan} na dziś.`
        : `${name}${day}: ${placementsWord(hired)} przy planie ${plan} na dziś.`;
    if (forecast && total) pace += ` W akceptacjach ${forecast} kolejnych, razem ${total} z celu ${goal.target}.`;
    else pace += ` Cel miesiąca: ${goal.target}.`;
  } else if (window.kind === "month" && goalsApply(window)) {
    const people = peopleWithGoal(rows);
    if (people) {
      const reached = people.placements >= people.target;
      pace =
        people.placements === hired
          ? `${name}: ${placementsWord(hired)} przy celu ${people.target}.`
          : `${name}: ${placementsWord(hired)} w firmie, ${people.placements} u osób z celem ${people.target}.`;
      pace += reached ? " Cel osiągnięty." : ` Do celu zabrakło ${people.target - people.placements}.`;
    }
  }
  const worst = worstColumn(inFlight);
  const stall = worst
    ? `Dziś najwięcej stoi ${STALL_PLACE[worst.column]}: ${worst.recent_stale_count} z ${worst.recent_count} par z ostatnich ${inFlight?.recent_days} dni czeka dłużej niż ${inFlight?.stale_days}.`
    : null;
  return { pace, stall };
}

// ─── Tempo ───────────────────────────────────────────────────────────────────

export interface TempoRow {
  id: string;
  label: string;
  horizon: string;
  /** `null` = nie policzono, nie 0. */
  current: number | null;
  target: number | null;
  /** Plan na teraz (kreska na pasku); `null` = okres zamknięty. */
  expected: number | null;
  /** Jaśniejszy pasek: szacunek z otwartych akceptacji. */
  forecast?: number | null;
  unit?: string;
  /** Licznik firmy inny niż licznik osób z celem. */
  note?: string | null;
}

export function tempoRows(input: {
  window: RecruitmentFunnelResponse["period"];
  running: boolean;
  workdays: number | null;
  funnel: RecruitmentFunnelResponse;
  goals: TeamGoalsResponse | undefined;
  inFlight: InFlightResponse | undefined;
  rows: readonly TeamPeopleRow[];
}): TempoRow[] {
  const { window, running, workdays, funnel, goals, inFlight, rows } = input;
  const byId = (id: string) => goals?.goals.find((g) => g.goal_id === id);
  const verif = byId("team_daily_first_verifications");
  const recs = byId("team_weekly_cvs_sent");
  const place = byId("team_monthly_placements");
  const precision = byId("team_monthly_precision");
  const out: TempoRow[] = [];
  if (running && window.kind === "month") {
    const company = goals?.company_month_placements ?? stageCount(funnel, "hired");
    const current = place?.current ?? company;
    out.push(
      { id: "verified", label: "Weryfikacje", horizon: "dziś", current: verif?.current ?? 0, target: verif?.target ?? null, expected: verif?.expected ?? null },
      { id: "cv_sent", label: "Rekomendacje", horizon: "ten tydzień", current: recs?.current ?? 0, target: recs?.target ?? null, expected: recs?.expected ?? null },
      {
        id: "hired",
        label: "Placementy",
        horizon: "ten miesiąc",
        current,
        target: place?.target ?? null,
        expected: place?.expected ?? null,
        forecast: inFlight?.forecast.high != null ? current + inFlight.forecast.high : null,
        note: company !== current ? `w firmie ${company}` : null,
      },
    );
  } else {
    // Cel okresu = dzisiejszy cel dnia i tygodnia × dni robocze okresu; historii celów nie ma.
    const days = goalsApply(window) ? (workdays ?? 0) : 0;
    const horizon = workdays ? `${workdays} dni` : "w okresie";
    const people = window.kind === "month" && goalsApply(window) ? peopleWithGoal(rows) : null;
    const hired = stageCount(funnel, "hired");
    out.push(
      { id: "verified", label: "Weryfikacje", horizon, current: stageNotRecorded(funnel, "verified") ? null : stageCount(funnel, "verified"), target: verif?.target != null && days ? verif.target * days : null, expected: null },
      { id: "cv_sent", label: "Rekomendacje", horizon, current: stageNotRecorded(funnel, "cv_sent") ? null : stageCount(funnel, "cv_sent"), target: recs?.target != null && days ? Math.round((recs.target * days) / 5) : null, expected: null },
      {
        id: "hired",
        label: "Placementy",
        horizon,
        current: people ? people.placements : hired,
        target: people?.target ?? null,
        expected: null,
        note: people && people.placements !== hired ? `w firmie ${hired}` : null,
      },
    );
  }
  if (precision) {
    out.push({ id: "precision", label: "Precyzja", horizon: "30 dni", current: precision.current, target: precision.target ?? null, expected: null, unit: "%" });
  }
  return out;
}

// ─── Sygnały ─────────────────────────────────────────────────────────────────

/** Im bliżej placementu, tym wyżej: akceptacja, potem CV u nas, potem rekrutacje. */
const SIGNAL_ORDER = ["stale_acceptances", "dl_send_stale", "no_one_sent", "overdue", "stale_jobs", "weak_preps", "low_precision", "stale_postings"];

/** Akceptacja stojąca dłużej niż tyle dni trafia do sygnałów. */
export const ACCEPTANCE_ATTENTION_DAYS = 14;

export interface TeamSignal {
  kind: string;
  count: number;
  label: string;
  href: string | null;
  /** Sygnał o osobach: kto, bez szukania w tabeli. */
  names: string[];
}

export function rankedSignals(
  items: readonly TeamAttentionItem[],
  inFlight: InFlightResponse | undefined,
  rows: readonly TeamPeopleRow[],
  /** Bez sekcji Pipeline (Rada nadzorcza) gotowy adres listy rekrutacji prowadzi donikąd. */
  canOpenJobs: boolean,
): TeamSignal[] {
  const stale = (inFlight?.acceptances ?? []).filter((a) => a.days > ACCEPTANCE_ATTENTION_DAYS).length;
  const nameOf = (id: number) => rows.find((r) => r.user_id === id)?.name ?? null;
  const out: TeamSignal[] = items.map((item) => ({
    kind: item.kind,
    count: item.count,
    label: item.label,
    href: (canOpenJobs ? item.href : null) ?? (item.report ? reportHref(item.report as ReportId) : null),
    names: (item.user_ids ?? []).map(nameOf).filter((n): n is string => Boolean(n)),
  }));
  if (stale > 0) {
    out.push({
      kind: "stale_acceptances",
      count: stale,
      label: `akceptacji czeka dłużej niż ${ACCEPTANCE_ATTENTION_DAYS} dni`,
      href: reportHref("akceptacje-w-toku"),
      names: [],
    });
  }
  const rank = (kind: string) => {
    const index = SIGNAL_ORDER.indexOf(kind);
    return index === -1 ? SIGNAL_ORDER.length : index;
  };
  return out.sort((a, b) => rank(a.kind) - rank(b.kind));
}

// ─── Grupy osób ──────────────────────────────────────────────────────────────

export type PersonGroupId = "placed" | "near" | "sending" | "quiet" | "no_goal";

/** Grupy mówią, jak daleko osoba doszła w okresie, nie jak ją oceniamy. */
export const PERSON_GROUPS: readonly { id: PersonGroupId; label: string }[] = [
  { id: "placed", label: "Mają placement w tym okresie" },
  { id: "near", label: "Doszli do rozmów albo akceptacji" },
  { id: "sending", label: "Wysyłają CV, jeszcze bez rozmów" },
  { id: "quiet", label: "Bez wysłanego CV w tym okresie" },
  { id: "no_goal", label: "Bez celu placementów" },
];

export function personGroup(row: TeamPeopleRow): PersonGroupId {
  // Cel znamy tylko w oknie miesiąca; poza nim bez celu to role inne niż rekruter.
  const noGoal = row.placements_target != null ? row.placements_target === 0 : row.role !== "recruiter";
  if (noGoal) return "no_goal";
  if (row.placements > 0) return "placed";
  if (row.interviews + (row.acceptances ?? 0) > 0) return "near";
  if (row.recommendations > 0) return "sending";
  return "quiet";
}

export function groupedPeople<T extends TeamPeopleRow>(rows: readonly T[]): { id: PersonGroupId; label: string; rows: T[] }[] {
  return PERSON_GROUPS.map((group) => ({
    ...group,
    rows: rows
      .filter((row) => personGroup(row) === group.id)
      .sort(
        (a, b) =>
          b.placements - a.placements ||
          (b.acceptances ?? 0) - (a.acceptances ?? 0) ||
          b.interviews - a.interviews ||
          b.recommendations - a.recommendations ||
          b.verifications - a.verifications,
      ),
  })).filter((group) => group.rows.length > 0);
}

// ─── Serie w czasie ──────────────────────────────────────────────────────────

export type ConversionKey = "verified_cv" | "cv_interview" | "interview_acceptance" | "acceptance_hired";

export const CONVERSIONS: readonly { key: ConversionKey; from: TrendStageKey; to: TrendStageKey; label: string; short: string }[] = [
  { key: "verified_cv", from: "verified", to: "cv_sent", label: "Weryfikacja → rekomendacja", short: "Weryf. → rekom." },
  { key: "cv_interview", from: "cv_sent", to: "client_interview", label: "Rekomendacja → rozmowa u klienta", short: "Rekom. → rozmowa" },
  { key: "interview_acceptance", from: "client_interview", to: "acceptance", label: "Rozmowa → akceptacja", short: "Rozmowa → akcept." },
  { key: "acceptance_hired", from: "acceptance", to: "hired", label: "Akceptacja → placement", short: "Akcept. → placement" },
];

export interface ConversionPoint {
  value: number | null;
  num: number | null;
  den: number | null;
}

export interface TrendSeries {
  labels: string[];
  counts: Record<TrendStageKey, (number | null)[]>;
  conversions: Record<ConversionKey, ConversionPoint[]>;
  /** Indeks okresu, od którego liczy NEXUS (12.10.2026); `null` = poza zakresem. */
  cutoverIndex: number | null;
}

type Counts = Record<TrendStageKey, number | null>;
const STAGE_KEYS: readonly TrendStageKey[] = ["verified", "cv_sent", "client_interview", "acceptance", "hired"];
const MONTH_NAMES = ["sty", "lut", "mar", "kwi", "maj", "cze", "lip", "sie", "wrz", "paź", "lis", "gru"];

function point(num: number | null, den: number | null): ConversionPoint {
  // Zero mianownika to „nie da się policzyć”, nie 0%. Bez sufitu 100%.
  return { num, den, value: num === null || den === null || den === 0 ? null : Math.round((100 * num) / den) };
}

function buildSeries(periods: readonly { label: string; counts: Counts; narrow?: Counts | null; cutover: boolean }[]): TrendSeries {
  const counts = Object.fromEntries(STAGE_KEYS.map((key) => [key, periods.map((p) => p.counts[key])])) as TrendSeries["counts"];
  const conversions = Object.fromEntries(
    CONVERSIONS.map((c) => [
      c.key,
      periods.map((p) => {
        // Przejście z akceptacjami tylko na odcinku, na którym liczą się oba etapy.
        const source = p.narrow && (c.from === "acceptance" || c.to === "acceptance") ? p.narrow : p.counts;
        return point(source[c.to], source[c.from]);
      }),
    ]),
  ) as TrendSeries["conversions"];
  const cutoverIndex = periods.findIndex((p) => p.cutover);
  return { labels: periods.map((p) => p.label), counts, conversions, cutoverIndex: cutoverIndex === -1 ? null : cutoverIndex };
}

/** Trwający tydzień zostaje w tabeli: kilka dni na linii wygląda jak załamanie. */
export function weeklySeries(weeks: WeeklyTrendResponse["weeks"]): TrendSeries {
  let cutoverSeen = false;
  return buildSeries(
    weeks
      .filter((w) => !w.partial)
      .map((w) => {
        const cutover = !cutoverSeen && w.week_start >= "2026-10-12";
        cutoverSeen = cutoverSeen || cutover;
        return { label: dayMonth(w.week_start), counts: w.counts, cutover };
      }),
  );
}

/** Trwający miesiąc zostaje poza linią z tego samego powodu co tydzień. */
export function monthlySeries(months: MonthlyTrendResponse["months"]): TrendSeries {
  return buildSeries(
    months
      .filter((m) => !m.partial)
      .map((m) => ({
        label: MONTH_NAMES[Number(m.month_start.slice(5, 7)) - 1],
        counts: m.counts,
        narrow: m.cutover_counts,
        cutover: m.cutover_counts !== null,
      })),
  );
}

export function niceAxisMax(value: number): number {
  if (value <= 4) return 4;
  const power = 10 ** Math.floor(Math.log10(value));
  const step = [1, 2, 3, 4, 6, 8, 10].find((s) => s * power >= value) ?? 10;
  return step * power;
}
