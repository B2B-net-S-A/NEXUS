/**
 * Model widoku licznika celów w górnym pasku (13.10.2026).
 *
 * Czysta funkcja: z odpowiedzi `/api/kpis/me/today` i `/api/kpis/me/goals`
 * układa do trzech podpisanych segmentów paska i treść panelu. Przycisk, panel
 * i harness `/preview/kpi-topbar` tylko to rysują.
 *
 * Reguły (docs/claude/ui/licznik-celow-w-gornym-pasku.md):
 * - segmenty mają stałą kolejność (dzień, tydzień, miesiąc), nie alfabet po id —
 *   do 13.10.2026 placement, jedyny cel wynikowy, nie mieścił się w pasku;
 * - kolejność to też ważność: w ciasnym pasku segmenty znikają od końca;
 * - znaczek tylko przy wyjątku: poniżej tempa, zrobione, okres zamknięty;
 * - „niepoliczony” i „celu jeszcze nie ma” nigdy nie są zerem ani „2/0”.
 */

import type { KpiGoal, KpiPeriod, KpiResult, KpiState, MyKpiGoals } from "@/lib/api";
import { KPI_ID_TO_WHO_COUNTS, whoCountsHref } from "@/lib/kpi-who-counts";
import { countPl } from "@/lib/plural-pl";

export type KpiMark = "behind" | "hit" | "missed" | null;

type Period = KpiPeriod | "quarter";

export interface KpiSegment {
  id: string;
  label: string;
  /** Krótszy podpis dla formy zwartej (okno 1280–1535 px). */
  labelCompact: string;
  /** Pogrubiony wynik. */
  value: string;
  /** Reszta po wyniku: cel i okres („/ 4 dziś”). */
  rest: string;
  /** To samo ze skrótem okresu („/ 15 tydz.”). */
  restCompact: string;
  mark: KpiMark;
}

export interface KpiPanelRow {
  id: string;
  title: string;
  value: string;
  rest: string;
  mark: KpiMark;
  state: KpiState | null;
  /** 0–100; null = bez paska (niepoliczony albo celu jeszcze nie ma). */
  progressPct: number | null;
  /** Kreska tempa albo progu na pasku, 0–100; null = bez kreski. */
  expectedPct: number | null;
  status: string | null;
  description: string | null;
  /**
   * Lista „Kto się liczy” za liczbą (17.10.2026) — tylko własne cele osoby
   * z wynikiem większym od zera; cele zespołu i portfela jej nie mają.
   */
  link: { href: string; label: string } | null;
}

export interface KpiPanelGroup {
  id: string;
  heading: string;
  aside: string | null;
  rows: KpiPanelRow[];
}

export interface KpiTopbarModel {
  /**
   * Czyje cele („Zespół”) — przedrostek podpisu pierwszego segmentu w formie
   * pełnej; null u rekrutera i DL. Nie jest osobnym segmentem: w ciasnym pasku
   * zajmowałby miejsce jedynego celu, który się mieści.
   */
  lead: string | null;
  /** W kolejności ważności: gdy w pasku brakuje miejsca, znikają od końca. */
  segments: KpiSegment[];
  /** Nazwa przycisku dla czytnika ekranu — to samo, co mówią segmenty. */
  spoken: string;
  panelTitle: string;
  panelAside: string | null;
  groups: KpiPanelGroup[];
  facts: { label: string; value: string }[];
  footnote: string | null;
  link: { href: string; label: string } | null;
}

const PERIOD_ORDER: Record<Period, number> = { day: 0, week: 1, month: 2, quarter: 3 };
const PERIOD_WORD: Record<Period, string> = { day: "dziś", week: "tydzień", month: "miesiąc", quarter: "kwartał" };
const PERIOD_SHORT: Record<Period, string> = { day: "dziś", week: "tydz.", month: "mies.", quarter: "kw." };
const PERIOD_HEADING: Record<Period, string> = {
  day: "Dziś",
  week: "Ten tydzień",
  month: "Ten miesiąc",
  quarter: "Ten kwartał",
};
const PERIOD_WHOLE: Record<Period, string> = {
  day: "cały dzień",
  week: "cały tydzień",
  month: "cały miesiąc",
  quarter: "cały kwartał",
};
const PERIOD_CLOSED: Record<Period, string> = {
  day: "Dzień zamknięty.",
  week: "Tydzień zamknięty.",
  month: "Miesiąc zamknięty.",
  quarter: "Kwartał zamknięty.",
};

/** Kolejność segmentów w pasku: po jednym celu na dzień, tydzień i miesiąc. */
const TOPBAR_ORDER = ["daily_first_verifications", "weekly_cvs_sent", "monthly_placements"];

const DL_PLACEMENTS_ID = "dl_placements_quarter";
const DL_HIT_RATIO_ID = "dl_hit_ratio_quarter";

/** Cel z tempem: osobisty KPI albo cel zespołu — ten sam kształt. */
interface PacedItem {
  id: string;
  /** Id celu bez przedrostka `team_` — do wspólnej kolejności. */
  rankId: string;
  title: string;
  period: Period;
  unit: "count" | "pct";
  current: number | null;
  target: number;
  state: KpiState | null;
  /** Ile powinno być „na teraz”; null = brak danych o tempie. */
  expected: number | null;
  description: string | null;
  /** Lista osób za liczbą; null = cel bez listy albo zero. */
  peopleHref: string | null;
}

/** Liczba po polsku: całkowita bez zmian, ułamek z przecinkiem („24,5”). */
export function formatKpiNumber(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(1).replace(".", ",");
}

function clampPct(value: number): number {
  return Math.min(100, Math.max(0, value));
}

function markOf(state: KpiState | null): KpiMark {
  if (state === "behind" || state === "hit" || state === "missed") return state;
  return null;
}

function hasTarget(item: Pick<PacedItem, "target" | "state">): boolean {
  return item.target > 0 && item.state !== null;
}

function fromKpi(kpi: KpiResult): PacedItem {
  return {
    id: kpi.kpi_id,
    rankId: kpi.kpi_id,
    title: kpi.short_title_pl || kpi.title_pl,
    period: kpi.period,
    unit: "count",
    current: kpi.current,
    target: kpi.target,
    state: kpi.state,
    expected: kpi.expected_count ?? null,
    description: kpi.description_pl || null,
    peopleHref: peopleHrefOf(kpi),
  };
}

function peopleHrefOf(kpi: KpiResult): string | null {
  const metric = KPI_ID_TO_WHO_COUNTS[kpi.kpi_id];
  return metric && kpi.current !== null && kpi.current > 0 ? whoCountsHref(metric) : null;
}

function fromGoal(goal: KpiGoal): PacedItem {
  return {
    id: goal.goal_id,
    rankId: goal.goal_id.replace(/^team_/, ""),
    title: goal.short_title_pl || goal.title_pl,
    period: goal.period,
    unit: goal.unit,
    current: goal.current,
    target: goal.target,
    state: goal.state,
    expected: goal.expected ?? null,
    description: goal.note,
    peopleHref: null,
  };
}

function rank(item: PacedItem): number {
  const index = TOPBAR_ORDER.indexOf(item.rankId);
  return index === -1 ? TOPBAR_ORDER.length : index;
}

function byTopbarOrder(a: PacedItem, b: PacedItem): number {
  return (
    rank(a) - rank(b) ||
    PERIOD_ORDER[a.period] - PERIOD_ORDER[b.period] ||
    a.id.localeCompare(b.id)
  );
}

function valueOf(item: PacedItem): string {
  if (item.current === null) return "niepoliczony";
  return `${formatKpiNumber(item.current)}${item.unit === "pct" ? "%" : ""}`;
}

function targetOf(item: PacedItem): string {
  if (item.current === null || !hasTarget(item)) return "";
  return `/ ${formatKpiNumber(item.target)}${item.unit === "pct" ? "%" : ""}`;
}

function segmentOf(item: PacedItem): KpiSegment {
  const target = targetOf(item);
  return {
    id: item.id,
    label: item.title,
    labelCompact: item.title,
    value: valueOf(item),
    rest: `${target} ${PERIOD_WORD[item.period]}`.trim(),
    restCompact: `${target} ${PERIOD_SHORT[item.period]}`.trim(),
    mark: markOf(item.state),
  };
}

function statusOf(item: PacedItem): string | null {
  switch (item.state) {
    case null:
      return null;
    case "hit":
      return "Cel zrobiony.";
    case "missed":
      return PERIOD_CLOSED[item.period];
    case "behind": {
      if (item.unit === "pct") return "Poniżej celu.";
      if (item.expected === null) return "Poniżej tempa.";
      const when = item.period === "day" ? "na tę godzinę" : "na dziś";
      return `Poniżej tempa (${when}: ${Math.floor(item.expected)}).`;
    }
    default:
      // Cel 1 (placement miesiąca) nie ma tempa — backend nigdy nie daje mu „behind”.
      return item.target === 1 ? `Cel na ${PERIOD_WHOLE[item.period]}, bez tempa.` : "W tempie.";
  }
}

function paceTick(item: PacedItem): number | null {
  if (item.unit !== "count" || item.expected === null || item.target <= 1) return null;
  if (item.state === "hit" || item.state === "missed" || item.state === null) return null;
  const pct = clampPct((item.expected / item.target) * 100);
  return pct > 0 ? pct : null;
}

function rowOf(item: PacedItem): KpiPanelRow {
  const counted = item.current !== null && hasTarget(item);
  return {
    id: item.id,
    title: item.title,
    value: valueOf(item),
    rest: targetOf(item),
    mark: markOf(item.state),
    state: item.state,
    progressPct: counted ? clampPct(((item.current as number) / item.target) * 100) : null,
    expectedPct: paceTick(item),
    status: statusOf(item),
    description: item.description,
    link: item.peopleHref ? { href: item.peopleHref, label: "Zobacz, kto się liczy" } : null,
  };
}

function hoursLeftLabel(hours: number): string {
  if (hours <= 0) return "dzień pracy zamknięty";
  const minutes = Math.round(hours * 60);
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  const text = [h > 0 ? `${h} h` : "", m > 0 ? `${m} min` : ""].filter(Boolean).join(" ");
  return `do końca dnia pracy: ${text}`;
}

function groupsOf(items: readonly PacedItem[], dayHoursLeft: number | null): KpiPanelGroup[] {
  const sorted = [...items].sort(byTopbarOrder);
  const periods = [...new Set(sorted.map((item) => item.period))].sort(
    (a, b) => PERIOD_ORDER[a] - PERIOD_ORDER[b],
  );
  return periods.map((period) => ({
    id: period,
    heading: PERIOD_HEADING[period],
    aside: period === "day" && dayHoursLeft !== null ? hoursLeftLabel(dayHoursLeft) : null,
    rows: sorted.filter((item) => item.period === period).map(rowOf),
  }));
}

function spokenOf(title: string, segments: readonly KpiSegment[]): string {
  const marks: Record<Exclude<KpiMark, null>, string> = {
    behind: ", poniżej tempa",
    hit: ", cel zrobiony",
    missed: ", okres zamknięty",
  };
  const parts = segments.map((segment) =>
    [segment.label, segment.value, segment.rest.replace("/", "z")].filter(Boolean).join(" ") +
    (segment.mark ? marks[segment.mark] : ""),
  );
  return `${title}: ${parts.join("; ")}`;
}

function peopleLabel(people: number | null): string | null {
  return people ? countPl(people, "osoba", "osoby", "osób") : null;
}

const CLOSED_FORMS = ["zamkniętej rekrutacji", "zamkniętych rekrutacji", "zamkniętych rekrutacji"] as const;

/** Wiersze panelu Delivery Leada: jeden cel (30% hit ratio) zapisany na dwa sposoby. */
function deliveryLeadRows(goals: MyKpiGoals): KpiPanelRow[] {
  const closed = goals.closed_requests ?? null;
  const placements = goals.goals.find((g) => g.goal_id === DL_PLACEMENTS_ID);
  const hitRatio = goals.goals.find((g) => g.goal_id === DL_HIT_RATIO_ID);
  const rows: KpiPanelRow[] = [];

  if (placements) {
    const item = fromGoal(placements);
    const counted = item.current !== null && hasTarget(item);
    const missing = counted ? item.target - (item.current as number) : 0;
    rows.push({
      ...rowOf(item),
      expectedPct: null,
      status:
        item.state === "hit"
          ? "Cel zrobiony."
          : item.state === "behind"
            ? `Brakuje ${countPl(missing, "placementu", "placementów", "placementów")}.`
            : null,
      description:
        counted && closed !== null && hitRatio
          ? `Cel to ${formatKpiNumber(hitRatio.target)}% z ${countPl(closed, ...CLOSED_FORMS)}.`
          : placements.note,
    });
  }

  if (hitRatio) {
    const item = fromGoal(hitRatio);
    const counted = item.current !== null;
    rows.push({
      ...rowOf(item),
      // Oba wiersze to ten sam warunek — znaczek świeci raz, przy placementach.
      mark: null,
      // Skala 0–100% z kreską na progu, nie „ile celu zrobione”.
      progressPct: counted ? clampPct(item.current as number) : null,
      expectedPct: counted ? clampPct(item.target) : null,
      status: null,
      description:
        counted && closed !== null && placements?.current != null
          ? `${countPl(placements.current, "placement", "placementy", "placementów")} z ${countPl(closed, ...CLOSED_FORMS)}. ` +
            `Kreska to próg ${formatKpiNumber(item.target)}%.`
          : hitRatio.note,
    });
  }
  return rows;
}

function deliveryLeadSegments(goals: MyKpiGoals): KpiSegment[] {
  const closed = goals.closed_requests ?? null;
  const quarter = goals.scope_label.split(" ")[0];
  const segments: KpiSegment[] = [];
  if (closed !== null) {
    const rest = quarter ? `w ${quarter}` : "";
    segments.push({
      id: "dl_closed_requests",
      label: "Zamknięte rekrutacje",
      labelCompact: "Zamknięte",
      value: String(closed),
      rest,
      restCompact: rest,
      mark: null,
    });
  }
  for (const goal of goals.goals) {
    if (goal.goal_id !== DL_PLACEMENTS_ID && goal.goal_id !== DL_HIT_RATIO_ID) continue;
    const item = fromGoal(goal);
    const isHitRatio = goal.goal_id === DL_HIT_RATIO_ID;
    const target = isHitRatio ? `/ ${formatKpiNumber(item.target)}%` : targetOf(item);
    segments.push({
      id: item.id,
      label: item.title,
      labelCompact: item.title,
      // W pasku „—”, w panelu słowo „niepoliczony”.
      value: item.current === null ? "—" : valueOf(item),
      rest: target,
      restCompact: target,
      mark: isHitRatio ? null : markOf(item.state),
    });
  }
  // Najpierw to, co do zrobienia (placementy), potem ten sam cel w procentach,
  // na końcu podstawa celu — w ciasnym pasku segmenty znikają od końca.
  const order = [DL_PLACEMENTS_ID, DL_HIT_RATIO_ID, "dl_closed_requests"];
  return segments.sort((a, b) => order.indexOf(a.id) - order.indexOf(b.id));
}

function deliveryLeadGroup(goals: MyKpiGoals, heading: string): KpiPanelGroup {
  return { id: "quarter", heading, aside: null, rows: deliveryLeadRows(goals) };
}

function closedFacts(goals: MyKpiGoals): { label: string; value: string }[] {
  const closed = goals.closed_requests ?? null;
  if (closed === null) return [];
  const facts = [{ label: "Zamknięte rekrutacje w kwartale", value: String(closed) }];
  // 21.10.2026: duplikaty, anulowane przez klienta, obsadzone wewnętrznie…
  // nie wchodzą do hit ratio — osobny fakt, żeby było widać, że ich nie liczono.
  const neutral = goals.closed_neutral ?? 0;
  if (neutral > 0) {
    facts.push({ label: "Zamknięte, które nie liczą się do hit ratio", value: String(neutral) });
  }
  return facts;
}

export function buildKpiTopbarModel(
  kpis: readonly KpiResult[],
  goals: MyKpiGoals | null,
): KpiTopbarModel | null {
  const leader = goals && goals.kind !== "none" && goals.goals.length > 0 ? goals : null;

  if (kpis.length > 0) {
    const items = kpis.map(fromKpi).sort(byTopbarOrder);
    const inBar = items.slice(0, 3);
    const segments = inBar.map(segmentOf);
    const daily = kpis.find((kpi) => kpi.period === "day");
    const groups = groupsOf(items, daily ? daily.deadline_hours_left : null);
    // Osoba z własnymi celami i celami lidera: w pasku osobiste, reszta w panelu.
    if (leader?.kind === "delivery_lead") {
      groups.push(deliveryLeadGroup(leader, `Cel portfela · ${leader.scope_label}`));
    } else if (leader) {
      const people = peopleLabel(leader.people);
      groups.push({
        id: "team",
        heading: people ? `Cele zespołu · ${people}` : "Cele zespołu",
        aside: null,
        rows: leader.goals.map(fromGoal).sort(byTopbarOrder).map(rowOf),
      });
    }
    return {
      lead: null,
      segments,
      spoken: spokenOf("Twoje cele", segments),
      panelTitle: "Twoje cele",
      panelAside: null,
      groups,
      facts: leader?.kind === "delivery_lead" ? closedFacts(leader) : [],
      footnote: "Rekomendacja i placement liczą się osobie, która zweryfikowała kandydata.",
      link: { href: "/insights?tab=moj-miesiac", label: "Mój miesiąc" },
    };
  }

  if (!leader) return null;

  if (leader.kind === "delivery_lead") {
    const segments = deliveryLeadSegments(leader);
    return {
      lead: null,
      segments,
      spoken: spokenOf("Cel portfela", segments),
      panelTitle: "Cel portfela",
      panelAside: leader.scope_label || null,
      groups: [deliveryLeadGroup(leader, "Ten kwartał")],
      facts: closedFacts(leader),
      footnote:
        "Otwarte rekrutacje wejdą do celu po zamknięciu. Liczy się pierwsze zatrudnienie w rekrutacji z Twojego portfela.",
      link: { href: "/insights?tab=raporty&report=portfele-dl", label: "Portfele DL" },
    };
  }

  const items = leader.goals.map(fromGoal).sort(byTopbarOrder);
  // W pasku tylko liczniki; precyzja (procent z 30 dni) zostaje w panelu.
  const inBar = items.filter((item) => item.unit === "count").slice(0, 3);
  const segments = inBar.map(segmentOf);
  const people = peopleLabel(leader.people);
  return {
    lead: "Zespół",
    segments,
    spoken: spokenOf("Cele zespołu", segments),
    panelTitle: "Cele zespołu",
    panelAside: people,
    groups: groupsOf(items, null),
    facts: [],
    footnote: "Cel zespołu to suma celów osób, a wynik to suma ich pracy.",
    link: { href: "/insights?tab=zespol", label: "Zespół w Insights" },
  };
}
