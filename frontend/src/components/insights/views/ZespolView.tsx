"use client";

import Link from "next/link";
import { useState, type ReactNode } from "react";
import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  insightsBoardApi,
  insightsQueryKeys,
  type InsightsPeriodParams,
} from "@/lib/insights-api";
import {
  insightsFlagsApi,
  performanceFlagsQueryKey,
} from "@/lib/insights-flags-api";
import { buildFunnelCsvExport } from "@/lib/insights-csv";
import {
  dlLeadSortValue,
  isNameColumn,
  nextColumnSort,
  sortRowsByColumn,
  splitFormerEmployees,
  summarizeFormerEmployees,
  teamPeopleSortValue,
  type ColumnSort,
  type DlLeadSortKey,
  type TeamPeopleSortKey,
} from "@/lib/insights-people-table";
import { reportHref } from "@/lib/insights-reports";
import {
  insightsTeamSignalsApi,
  insightsTeamSignalsQueryKeys,
  type TeamPeopleResponse,
  type TeamPeopleRow,
} from "@/lib/insights-team-api";
import {
  groupedPeople,
  personGroup,
  TEAM_STAGES,
  worstColumn,
} from "@/lib/insights-team-view";
import {
  countDelta,
  DL_HIT_RATIO_PORTFOLIO_NOTE,
  isPeopleRowWorthShowing,
} from "@/lib/insights-views";
import { hasAnalyticsCapability, hasRole, useAuthStore } from "@/store/auth";
import { PeriodPicker } from "@/components/insights/PeriodPicker";
import { useInsightsPeriod } from "@/components/insights/useInsightsPeriod";
import { InsightsFlagAdmin } from "@/components/insights/sections/InsightsFlagAdmin";
import {
  InsightsPerformanceFlags,
  PerformanceFlagsLoadNotice,
} from "@/components/insights/sections/InsightsPerformanceFlag";
import {
  SectionError,
  SortableHeader,
} from "@/components/insights/sections/_shared";
import { Switch } from "@/components/ui/switch";
import {
  TeamWhoCountsPanel,
  type TeamWhoCountsSubject,
} from "@/components/insights/sections/WhoCountsPanel";
import {
  WHO_COUNTS_METRICS,
  addDays,
  metricFromSlug,
  type WhoCountsMetric,
} from "@/lib/kpi-who-counts";
import { useUrlWriter } from "@/lib/url-selection";
import { TeamAnswer } from "./team/TeamAnswer";
import { TeamStageLens } from "./team/TeamStageLens";
import { useTeamViewData } from "./team/useTeamViewData";
import { PanelLoading } from "./ViewKit";

export const ZESPOL_DEFAULT_PERIOD: InsightsPeriodParams = {
  period: "month",
  offset: 0,
};

/**
 * Tabela „Delivery Leadzi” liczy hit ratio z ROKU — jak raport „Portfele
 * Delivery Leadów”. Z miesiąca (okno Zespołu) wychodziło kilka zamkniętych
 * rekrutacji na DL i procent skakał o dziesiątki punktów, czytając się jak
 * awaria (audyt 24.09.2026, M27).
 */
export const ZESPOL_DL_PERIOD: InsightsPeriodParams = {
  period: "year",
  offset: 0,
};

/**
 * Zespół — „Jak idzie zespołowi?” (v4, 05.11.2026): odpowiedź, tempo i sprawy na
 * dziś, potem soczewka etapu z wykresami, na końcu mapa osób.
 *
 * Każdy widzi odpowiedź, tempo i soczewkę bez nazwisk. Osoby i sygnały — role
 * z `view_team_kpi` (HoR, Delivery Lead, TCM, Finanse, admin, Rada): to imienne
 * wyniki cudzej pracy. Bez kwot.
 */
export function ZespolView() {
  const user = useAuthStore((state) => state.user);
  const seesTeam =
    hasRole(user, "admin") || hasAnalyticsCapability(user, "view_team_kpi");
  const { period, setPeriod } = useInsightsPeriod(ZESPOL_DEFAULT_PERIOD);
  const data = useTeamViewData(period, seesTeam);
  const searchParams = useSearchParams();
  const worst = worstColumn(data.inFlight);
  const worstStage = TEAM_STAGES.find((stage) => stage.column === worst?.column);
  const stallParams = new URLSearchParams(searchParams.toString());
  if (worstStage) stallParams.set("etap", worstStage.stage);

  return (
    <div className="space-y-5">
      <TeamAnswer
        data={data}
        seesTeam={seesTeam}
        stallHref={worstStage ? `/insights?${stallParams.toString()}` : null}
        picker={
          <PeriodPicker
            value={period}
            onChange={setPeriod}
            defaultValue={ZESPOL_DEFAULT_PERIOD}
            resolved={data.funnel.data?.period ?? null}
            csv={buildFunnelCsvExport(data.funnel.data)}
            hideCaption
          />
        }
      />
      <TeamStageLens data={data} seesTeam={seesTeam} period={period} />
      {seesTeam ? (
        <PeoplePanel period={period} previousLabel={data.previousLabel ?? null} />
      ) : (
        <p className="rounded-xl border border-border bg-card p-4 text-sm text-muted-foreground">
          Wyniki poszczególnych osób widzą liderzy zespołu (Head of Recruitment,
          Delivery Lead). Swoje liczby znajdziesz w zakładce „Mój miesiąc”.
        </p>
      )}
    </div>
  );
}

type PeopleScope = "recruiters" | "delivery";

function PeoplePanel({
  period,
  previousLabel,
}: {
  period: InsightsPeriodParams;
  previousLabel: string | null;
}) {
  const user = useAuthStore((state) => state.user);
  // Delivery Lead bez roli rekrutacyjnej zaczyna od swojej perspektywy.
  const [scope, setScope] = useState<PeopleScope>(
    hasRole(user, "delivery_lead") &&
      !hasRole(user, "admin", "head_of_recruitment", "recruiter")
      ? "delivery"
      : "recruiters",
  );
  // Konta wyłączone stoją jednym wierszem pod listą (prośba z zespołu,
  // 19.10.2026); przełącznik wspólny dla obu zakładek, domyślnie zwinięte.
  const [showFormer, setShowFormer] = useState(false);

  return (
    <section id="ludzie" className="scroll-mt-24 space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="text-base font-semibold text-foreground">Ludzie</h3>
        <div className="flex flex-wrap items-center gap-3">
          <label
            htmlFor="zespol-show-former"
            className="inline-flex min-h-9 cursor-pointer items-center gap-2 text-sm text-muted-foreground"
          >
            <Switch
              id="zespol-show-former"
              checked={showFormer}
              onCheckedChange={setShowFormer}
            />
            Pokaż byłych członków zespołu
          </label>
          <div
            role="group"
            aria-label="Kogo pokazać"
            className="inline-flex gap-0.5 rounded-lg bg-muted p-1"
          >
            {(
              [
                ["recruiters", "Rekruterzy"],
                ["delivery", "Delivery Leadzi"],
              ] as const
            ).map(([value, label]) => (
              <button
                key={value}
                type="button"
                aria-pressed={scope === value}
                onClick={() => setScope(value)}
                className={cn(
                  "min-h-9 rounded-md px-3 text-sm font-semibold transition-colors",
                  scope === value
                    ? "bg-card text-foreground shadow-xs"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
      </div>
      {scope === "recruiters" ? (
        <RecruiterTable
          period={period}
          previousLabel={previousLabel}
          showFormer={showFormer}
        />
      ) : (
        <DeliveryTable showFormer={showFormer} />
      )}
    </section>
  );
}

function RecruiterTable({
  period,
  previousLabel,
  showFormer,
}: {
  period: InsightsPeriodParams;
  previousLabel: string | null;
  showFormer: boolean;
}) {
  const peopleQuery = useQuery({
    queryKey: insightsTeamSignalsQueryKeys.people(period),
    queryFn: () => insightsTeamSignalsApi.people(period),
  });
  const flagsQuery = useQuery({
    queryKey: performanceFlagsQueryKey,
    queryFn: () => insightsFlagsApi.list(),
  });
  // Bez kliknięcia nagłówka — grupy osób; klik sortuje całą listę.
  const [sort, setSort] = useState<ColumnSort<TeamPeopleSortKey> | null>(null);
  const [showNoGoal, setShowNoGoal] = useState(false);
  const data = peopleQuery.data;
  const worthShowing = (data?.rows ?? []).filter(isPeopleRowWorthShowing);
  const quiet = (data?.rows.length ?? 0) - worthShowing.length;
  const { people, former } = splitFormerEmployees(worthShowing, showFormer);
  const rows = sort
    ? sortRowsByColumn(
        people,
        (row) => teamPeopleSortValue(row, sort.key),
        sort.dir,
        (row) => row.name,
      )
    : people;
  const formerSummary = summarizeFormerEmployees(former, (row) => row.name, {
    recommendations: (row) => row.recommendations,
    interviews: (row) => row.interviews,
    acceptances: (row) => row.acceptances ?? 0,
    placements: (row) => row.placements,
  });
  const onSort = (key: TeamPeopleSortKey) =>
    setSort((current) => nextColumnSort(current, key, isNameColumn));
  const outside = data?.outside_scope;
  const hasTargets = (data?.rows ?? []).some(
    (row) => row.placements_target != null && row.placements_target > 0,
  );
  // Lista „Kto się liczy” osoby z tabeli (17.10.2026): `?kto=…&osoba=<id>`
  // albo `osoba=bez-zaslugi`. W adresie, więc „Wstecz” ją zamyka.
  const searchParams = useSearchParams();
  const { pushUrl, replaceUrl } = useUrlWriter();
  const listMetric = metricFromSlug(searchParams.get("kto"));
  const listWho = searchParams.get("osoba");
  const writeList = (
    metric: WhoCountsMetric | null,
    who: string | null,
    mode: "push" | "replace" = "push",
  ) => {
    const params = new URLSearchParams(searchParams.toString());
    if (metric === null || who === null) {
      params.delete("kto");
      params.delete("osoba");
    } else {
      params.set("kto", WHO_COUNTS_METRICS[metric].slug);
      params.set("osoba", who);
    }
    const href = `${window.location.pathname}?${params.toString()}`;
    if (mode === "push") pushUrl(href);
    else replaceUrl(href);
  };

  if (peopleQuery.isPending) return <PanelLoading />;
  if (peopleQuery.isError || !data) {
    return (
      <SectionError
        label="Ludzie"
        error={peopleQuery.error}
        onRetry={() => void peopleQuery.refetch()}
      />
    );
  }

  const low = data.low_precision_pct;
  const listSubject = teamListSubject(listWho, data.rows);
  // Skala cieniowania: najwyższa wartość w kolumnie wśród osób z celem.
  const heatMax = (value: (row: TeamPeopleRow) => number | null | undefined) =>
    Math.max(0, ...rows.filter((row) => personGroup(row) !== "no_goal").map((row) => value(row) ?? 0));
  const heat: PersonHeat = {
    verifications_per_workday: heatMax((row) => row.verifications_per_workday),
    recommendations: heatMax((row) => row.recommendations),
    interviews: heatMax((row) => row.interviews),
    acceptances: heatMax((row) => row.acceptances),
    placements: heatMax((row) => row.placements),
  };
  const renderPerson = (row: TeamPeopleRow) => (
    <PersonRow
      key={row.user_id}
      row={row}
      heat={heat}
      openMetric={
        listSubject?.kind === "person" && listSubject.id === row.user_id
          ? listMetric
          : null
      }
      onOpen={(metric) => writeList(metric, String(row.user_id))}
      lowPrecision={low}
      flags={flagsQuery.data?.flags_by_user?.[String(row.user_id)] ?? []}
      flagTypes={flagsQuery.data?.types ?? []}
      previousLabel={previousLabel}
    />
  );
  const unattributed = data.unattributed;
  const unattributedShown =
    unattributed !== undefined &&
    unattributed.recommendations + unattributed.interviews + unattributed.placements > 0;
  return (
    <div className="space-y-2">
      {listMetric && listSubject ? (
        <TeamWhoCountsPanel
          subject={listSubject}
          metric={listMetric}
          range={{
            start: data.period.start.slice(0, 10),
            end: addDays(data.period.end.slice(0, 10), -1),
          }}
          onMetricChange={(metric) => writeList(metric, listWho, "replace")}
          onClose={() => writeList(null, null)}
        />
      ) : null}
      <PerformanceFlagsLoadNotice
        isPending={flagsQuery.isPending}
        isSuccess={flagsQuery.isSuccess}
        isError={flagsQuery.isError}
        error={flagsQuery.error}
        onRetry={() => void flagsQuery.refetch()}
      />
      <div className="overflow-x-auto rounded-xl border border-border bg-card shadow-xs">
        <table className="w-full min-w-[46rem] text-sm">
          <thead>
            <tr className="border-b border-border text-xs uppercase tracking-wide text-muted-foreground">
              {(
                [
                  ["name", "Osoba"],
                  ["verifications_per_workday", "Weryf./dz."],
                  ["recommendations", "CV"],
                  ["interviews", "Rozmowy"],
                  ["acceptances", "Akcept."],
                  ["placements", hasTargets ? "Plac. / cel" : "Plac."],
                  ["in_flight", "W drodze"],
                  ["precision_pct", "Precyzja"],
                  ["placements_delta", "Zmiana"],
                ] as const
              ).map(([key, label]) => (
                <SortableHeader
                  key={key}
                  label={label}
                  columnKey={key}
                  sortKey={sort?.key ?? null}
                  sortDir={sort?.dir ?? "desc"}
                  onSort={onSort}
                  align={key === "name" ? "left" : "right"}
                  className={cn(
                    "whitespace-nowrap py-2 font-semibold",
                    key === "name"
                      ? "sticky left-0 bg-card px-4"
                      : key === "placements_delta"
                        ? "px-4"
                        : "px-2",
                  )}
                />
              ))}
            </tr>
          </thead>
          <tbody>
            {worthShowing.length === 0 ? (
              <tr>
                <td colSpan={9} className="px-4 py-6 text-center text-muted-foreground">
                  Nikt nie ruszył jeszcze kandydata w tym okresie.
                </td>
              </tr>
            ) : sort ? (
              rows.map(renderPerson)
            ) : (
              groupedPeople(rows).flatMap((group) => {
                const collapsible = group.id === "no_goal";
                const expanded = !collapsible || showNoGoal;
                return [
                  <tr key={group.id} className="h-7 border-b border-border bg-muted/50">
                    <td colSpan={9} className="sticky left-0 px-4 py-1 text-xs font-semibold text-foreground">
                      {collapsible ? (
                        <button
                          type="button"
                          onClick={() => setShowNoGoal((value) => !value)}
                          aria-expanded={showNoGoal}
                          className="inline-flex items-center gap-1 hover:text-primary"
                        >
                          {showNoGoal ? <ChevronDown className="h-3.5 w-3.5" aria-hidden /> : <ChevronRight className="h-3.5 w-3.5" aria-hidden />}
                          {group.label} · {group.rows.length}
                          {showNoGoal ? null : (
                            <span className="font-normal text-muted-foreground">
                              {" "}· {group.rows.reduce((sum, row) => sum + row.recommendations, 0)} CV,{" "}
                              {group.rows.reduce((sum, row) => sum + row.placements, 0)} plac.
                            </span>
                          )}
                        </button>
                      ) : (
                        <>{group.label} · {group.rows.length}</>
                      )}
                    </td>
                  </tr>,
                  ...(expanded ? group.rows.map(renderPerson) : []),
                ];
              })
            )}
            {formerSummary ? (
              <tr className="h-8 border-t border-border text-muted-foreground">
                <td className="sticky left-0 bg-card px-4 py-2.5 text-xs">
                  <FormerEmployeesLabel
                    count={formerSummary.count}
                    names={formerSummary.names}
                  />
                </td>
                <td className="px-3 py-2.5 text-right text-xs">—</td>
                <td className="px-3 py-2.5 text-right text-xs tabular-nums">
                  {formerSummary.sums.recommendations}
                </td>
                <td className="px-3 py-2.5 text-right text-xs tabular-nums">
                  {formerSummary.sums.interviews}
                </td>
                <td className="px-3 py-2.5 text-right text-xs tabular-nums">
                  {formerSummary.sums.acceptances}
                </td>
                <td className="px-3 py-2.5 text-right text-xs tabular-nums">
                  {formerSummary.sums.placements}
                </td>
                <td className="px-3 py-2.5 text-right text-xs">—</td>
                <td className="px-3 py-2.5 text-right text-xs">—</td>
                <td className="px-4 py-2.5 text-right text-xs">—</td>
              </tr>
            ) : null}
            {outside && outside.people > 0 ? (
              <tr className="h-8 border-t border-border text-muted-foreground">
                <td className="sticky left-0 bg-card px-4 py-2.5 text-xs">
                  {outside.label} ({outside.people})
                </td>
                <td className="px-3 py-2.5 text-right text-xs">—</td>
                <td className="px-3 py-2.5 text-right text-xs tabular-nums">
                  {outside.recommendations}
                </td>
                <td className="px-3 py-2.5 text-right text-xs tabular-nums">
                  {outside.interviews}
                </td>
                <td className="px-3 py-2.5 text-right text-xs tabular-nums">
                  {outside.acceptances ?? "—"}
                </td>
                <td className="px-3 py-2.5 text-right text-xs tabular-nums">
                  {outside.placements}
                </td>
                <td className="px-3 py-2.5 text-right text-xs">—</td>
                <td className="px-3 py-2.5 text-right text-xs">—</td>
                <td className="px-4 py-2.5 text-right text-xs">—</td>
              </tr>
            ) : null}
            {unattributed && unattributedShown ? (
              <tr className="h-8 border-t border-border text-muted-foreground">
                <td className="sticky left-0 bg-card px-4 py-2.5 text-xs">
                  Bez osoby z zasługą
                </td>
                <td className="px-3 py-2.5 text-right text-xs">—</td>
                {(
                  [
                    ["recommendation", unattributed.recommendations],
                    ["interview", unattributed.interviews],
                  ] as const
                ).map(([metric, value]) => (
                  <CountCell
                    key={metric}
                    value={value}
                    metric={metric}
                    who="Bez osoby z zasługą"
                    active={listSubject?.kind === "unattributed" && listMetric === metric}
                    onOpen={() => writeList(metric, UNATTRIBUTED_SLUG)}
                    className="text-xs"
                  />
                ))}
                <td className="px-3 py-2.5 text-right text-xs tabular-nums">
                  {unattributed.acceptances ?? "—"}
                </td>
                <CountCell
                  value={unattributed.placements}
                  metric="placement"
                  who="Bez osoby z zasługą"
                  active={listSubject?.kind === "unattributed" && listMetric === "placement"}
                  onOpen={() => writeList("placement", UNATTRIBUTED_SLUG)}
                  className="text-xs"
                />
                <td className="px-3 py-2.5 text-right text-xs">—</td>
                <td className="px-3 py-2.5 text-right text-xs">—</td>
                <td className="px-4 py-2.5 text-right text-xs">—</td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-muted-foreground">
        {quiet > 0 ? `Pominięto osoby bez ruchu w tym okresie: ${quiet}. ` : ""}
        {unattributedElsewhere(data) > 0
          ? `${unattributedElsewhere(data)} ruchów${unattributed ? " na innych etapach" : ""} nie da się przypisać nikomu — są w lejku, nie ma ich w tabeli. `
          : ""}
        Zasługę za parę dostaje osoba, która zweryfikowała kandydata. Liczba
        przy osobie otwiera listę osób za nią; klik w nagłówek sortuje.
      </p>
      <details className="text-xs text-muted-foreground">
        <summary className="min-h-9 cursor-pointer py-2 font-semibold text-primary">
          Jak liczymy tabelę?
        </summary>
        <p className="max-w-4xl leading-relaxed">
          Liczone jak w wyścigach i „Mój miesiąc”: CV wysłane, rozmowy,
          akceptacje i placementy pary dostaje osoba, która zweryfikowała
          kandydata — dlatego liczby różnią się od lejka wyżej i od raportu
          „Aktywność zespołu” (tam liczy się osoba, która przesunęła etap).
          Akceptacje liczą się od 12.10.2026. „Placementy / cel” — tylko
          w oknie miesiąca, cel osoby z celów KPI. „W drodze dziś” — pary osoby,
          które stoją dziś na wysyłce CV, u klienta, na rozmowie albo
          w akceptacji, niezależnie od okresu. Precyzja: z osób zweryfikowanych
          w ostatnich 30 dniach — ilu wysłano CV do klienta; „—” = mniej niż
          5 weryfikacji. Konta administracyjne i byli członkowie zespołu stoją
          jednym wierszem pod tabelą — ich liczby zostają w sumach.
        </p>
      </details>
    </div>
  );
}

const UNATTRIBUTED_SLUG = "bez-zaslugi";

/** Etykieta wiersza „Byli pracownicy (N)”: nazwiska w jednej linii. */
function FormerEmployeesLabel({
  count,
  names,
}: {
  count: number;
  names: readonly string[];
}) {
  return (
    <>
      Byli w zespole ({count}):{" "}
      <span className="text-foreground/80">{names.join(", ")}</span>
    </>
  );
}

/**
 * Kamienie bez osoby z zasługą, których nie ma w wierszu „Bez osoby z zasługą”
 * (weryfikacje, QC, akceptacje) — zostają w przypisie pod tabelą.
 */
function unattributedElsewhere(data: TeamPeopleResponse): number {
  const row = data.unattributed;
  if (!row) return data.totals.unattributed;
  return Math.max(
    data.totals.unattributed -
      row.recommendations -
      row.interviews -
      (row.acceptances ?? 0) -
      row.placements,
    0,
  );
}

/** Kogo otworzyć z `osoba=` w adresie; nieznany kształt = nic. */
function teamListSubject(
  who: string | null,
  rows: readonly TeamPeopleRow[],
): TeamWhoCountsSubject | null {
  if (!who) return null;
  if (who === UNATTRIBUTED_SLUG) return { kind: "unattributed" };
  const id = Number(who);
  if (!Number.isInteger(id) || id <= 0) return null;
  const row = rows.find((candidate) => candidate.user_id === id);
  return { kind: "person", id, name: row?.name ?? `Osoba #${id}` };
}

/** Liczba w tabeli, która otwiera listę osób za nią (0 zostaje zwykłą liczbą). */
function CountCell({
  value,
  metric,
  who,
  active,
  onOpen,
  className,
  suffix,
  shade,
}: {
  value: number;
  metric: WhoCountsMetric;
  who: string;
  active: boolean;
  onOpen: () => void;
  className?: string;
  /** Dopisek za liczbą (np. „/ 2” — cel). */
  suffix?: ReactNode;
  /** 0–1: im więcej w kolumnie, tym ciemniejsza komórka. */
  shade?: number | null;
}) {
  return (
    <td className="px-0.5 py-0.5 text-right tabular-nums">
      <span
        className={cn(
          "block rounded px-2 py-0.5",
          value === 0 && "text-muted-foreground",
          active && "ring-2 ring-primary/50",
          className,
        )}
        style={shadeStyle(shade)}
      >
        {value > 0 ? (
          <button
            type="button"
            onClick={onOpen}
            aria-pressed={active}
            aria-label={`${who} · ${WHO_COUNTS_METRICS[metric].label}: ${value}. Pokaż osoby`}
            className="rounded-sm hover:text-primary hover:underline focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
          >
            {value}
          </button>
        ) : (
          value
        )}
        {suffix}
      </span>
    </td>
  );
}

function shadeStyle(shade: number | null | undefined) {
  if (!shade || shade <= 0) return undefined;
  return { backgroundColor: `hsl(var(--primary) / ${(0.05 + 0.27 * shade).toFixed(3)})` };
}

type PersonHeat = Record<
  "verifications_per_workday" | "recommendations" | "interviews" | "acceptances" | "placements",
  number
>;

function PersonRow({
  row,
  heat,
  openMetric,
  onOpen,
  lowPrecision,
  flags,
  flagTypes,
  previousLabel,
}: {
  row: TeamPeopleRow;
  heat: PersonHeat;
  openMetric: WhoCountsMetric | null;
  onOpen: (metric: WhoCountsMetric) => void;
  lowPrecision: number;
  flags: Parameters<typeof InsightsPerformanceFlags>[0]["flags"];
  flagTypes: Parameters<typeof InsightsFlagAdmin>[0]["types"];
  previousLabel: string | null;
}) {
  const delta = countDelta(row.placements, row.previous_placements, "");
  const isLow = row.precision_pct !== null && row.precision_pct < lowPrecision;
  // Cel tylko w oknie miesiąca i tylko dodatni — „2 / 0” to nie cel.
  const target =
    row.placements_target != null && row.placements_target > 0
      ? row.placements_target
      : null;
  // Osoby bez celu bez cienia: ich liczby nie są tym samym porównaniem.
  const shaded = personGroup(row) !== "no_goal";
  const shade = (value: number | null | undefined, max: number) =>
    shaded && value && max > 0 ? value / max : null;
  return (
    <tr className="group/row h-8 border-b border-border/50 last:border-b-0 hover:bg-muted/40">
      <td className="sticky left-0 whitespace-nowrap bg-card px-4 py-0.5 group-hover/row:bg-muted">
        <span className="inline-flex items-center gap-1.5">
          <span className="font-medium text-foreground">{row.name}</span>
          {!row.is_active ? (
            <span className="rounded bg-muted px-1.5 py-0.5 text-[11px] text-muted-foreground">
              był(a) w zespole
            </span>
          ) : null}
          <InsightsPerformanceFlags flags={flags} />
          <span className="flex h-4 items-center opacity-0 transition-opacity focus-within:opacity-100 group-hover/row:opacity-100 pointer-coarse:opacity-100">
            <InsightsFlagAdmin
              userId={row.user_id}
              userName={row.name}
              flags={flags}
              types={flagTypes}
            />
          </span>
        </span>
      </td>
      <td className="px-0.5 py-0.5 text-right tabular-nums">
        <span
          className={cn("block rounded px-2 py-0.5", !row.verifications_per_workday && "text-muted-foreground")}
          style={shadeStyle(shade(row.verifications_per_workday, heat.verifications_per_workday))}
        >
          {row.verifications_per_workday === null
            ? "—"
            : row.verifications_per_workday.toLocaleString("pl-PL")}
        </span>
      </td>
      <CountCell
        value={row.recommendations}
        metric="recommendation"
        who={row.name}
        active={openMetric === "recommendation"}
        onOpen={() => onOpen("recommendation")}
        shade={shade(row.recommendations, heat.recommendations)}
      />
      <CountCell
        value={row.interviews}
        metric="interview"
        who={row.name}
        active={openMetric === "interview"}
        onOpen={() => onOpen("interview")}
        shade={shade(row.interviews, heat.interviews)}
      />
      <td className="px-0.5 py-0.5 text-right tabular-nums">
        <span
          className={cn("block rounded px-2 py-0.5", !row.acceptances && "text-muted-foreground")}
          style={shadeStyle(shade(row.acceptances, heat.acceptances))}
        >
          {row.acceptances ?? "—"}
        </span>
      </td>
      <CountCell
        value={row.placements}
        metric="placement"
        who={row.name}
        active={openMetric === "placement"}
        onOpen={() => onOpen("placement")}
        shade={shade(row.placements, heat.placements)}
        className={cn(
          row.placements > 0 && "font-semibold",
          target !== null && row.placements >= target && "text-success-muted-foreground",
        )}
        suffix={
          target !== null ? (
            <span className="font-normal text-muted-foreground"> / {target}</span>
          ) : null
        }
      />
      <td className={cn("px-2 py-0.5 text-right tabular-nums", !row.in_flight && "text-muted-foreground")}>{row.in_flight ?? "—"}</td>
      <td className="px-0.5 py-0.5 text-right tabular-nums">
        <span
          className={cn(
            "block rounded px-2 py-0.5",
            row.precision_pct === null && "text-muted-foreground",
            isLow && "bg-warning-muted font-semibold text-warning-muted-foreground",
          )}
        >
          {row.precision_pct === null ? "—" : `${Math.round(row.precision_pct)}%`}
        </span>
      </td>
      <td
        className={cn(
          "px-4 py-0.5 text-right text-xs tabular-nums",
          delta?.tone === "good" && "text-success-muted-foreground",
          delta?.tone === "bad" && "text-warning-muted-foreground",
          (!delta || delta.tone === "neutral") && "text-muted-foreground",
        )}
        title={previousLabel ? `Placementy wobec: ${previousLabel}` : "Placementy wobec poprzedniego okresu"}
      >
        {!delta || delta.tone === "neutral"
          ? <span className="sr-only">bez zmian</span>
          : `${row.placements > row.previous_placements ? "▲" : "▼"} ${Math.abs(row.placements - row.previous_placements)}`}
      </td>
    </tr>
  );
}

function DeliveryTable({ showFormer }: { showFormer: boolean }) {
  const period = ZESPOL_DL_PERIOD;
  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: insightsQueryKeys.dlPortfolio(period),
    queryFn: () => insightsBoardApi.dlPortfolio(period),
  });
  // Bez kliknięcia nagłówka — kolejność z API.
  const [sort, setSort] = useState<ColumnSort<DlLeadSortKey> | null>(null);
  if (isPending) return <PanelLoading />;
  if (isError || !data) {
    return (
      <SectionError
        label="Delivery Leadzi"
        error={error}
        onRetry={() => void refetch()}
      />
    );
  }
  const { people, former } = splitFormerEmployees(data.leads, showFormer);
  const leads = sort
    ? sortRowsByColumn(
        people,
        (lead) => dlLeadSortValue(lead, sort.key),
        sort.dir,
        (lead) => lead.dl_name,
      )
    : people;
  const formerSummary = summarizeFormerEmployees(former, (lead) => lead.dl_name, {
    requests: (lead) => lead.requests,
    open_requests: (lead) => lead.open_requests,
    placements: (lead) => lead.placements,
  });
  const onSort = (key: DlLeadSortKey) =>
    setSort((current) => nextColumnSort(current, key, isNameColumn));
  return (
    <div className="space-y-2">
      <div className="overflow-x-auto rounded-xl border border-border bg-card shadow-xs">
        <table className="w-full min-w-[40rem] text-sm">
          <thead>
            <tr className="border-b border-border text-xs uppercase tracking-wide text-muted-foreground">
              {(
                [
                  ["name", "Delivery Lead"],
                  ["requests", "Rekrutacje"],
                  ["open_requests", "Otwarte"],
                  ["placements", "Placementy"],
                  ["hit_ratio", "Hit ratio"],
                ] as const
              ).map(([key, label]) => (
                <SortableHeader
                  key={key}
                  label={label}
                  columnKey={key}
                  sortKey={sort?.key ?? null}
                  sortDir={sort?.dir ?? "desc"}
                  onSort={onSort}
                  align={key === "name" ? "left" : "right"}
                  className={cn(
                    "py-2.5 font-semibold",
                    key === "name"
                      ? "sticky left-0 bg-card px-4"
                      : key === "hit_ratio"
                        ? "px-4"
                        : "px-3",
                  )}
                />
              ))}
            </tr>
          </thead>
          <tbody>
            {data.leads.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-4 py-6 text-center text-muted-foreground">
                  Brak rekrutacji Delivery Leadów w tym okresie.
                </td>
              </tr>
            ) : (
              leads.map((lead) => (
                <tr key={lead.dl_id} className="border-b border-border/60 last:border-b-0">
                  <td className="sticky left-0 bg-card px-4 py-2.5">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium text-foreground">{lead.dl_name}</span>
                      {!lead.is_active ? (
                        <span className="rounded bg-muted px-1.5 py-0.5 text-[11px] text-muted-foreground">
                          był(a) w zespole
                        </span>
                      ) : null}
                    </div>
                  </td>
                  <td className="px-3 py-2.5 text-right tabular-nums">{lead.requests}</td>
                  <td className="px-3 py-2.5 text-right tabular-nums">
                    {lead.open_requests}
                  </td>
                  <td className="px-3 py-2.5 text-right font-semibold tabular-nums">
                    {lead.placements}
                  </td>
                  <td
                    className={cn(
                      "px-4 py-2.5 text-right tabular-nums",
                      lead.target_achieved === false && "text-warning-muted-foreground",
                    )}
                  >
                    {lead.hit_ratio === null ? "—" : `${Math.round(lead.hit_ratio)}%`}
                  </td>
                </tr>
              ))
            )}
            {formerSummary ? (
              <tr className="h-8 border-t border-border text-muted-foreground">
                <td className="sticky left-0 bg-card px-4 py-2.5 text-xs">
                  <FormerEmployeesLabel
                    count={formerSummary.count}
                    names={formerSummary.names}
                  />
                </td>
                <td className="px-3 py-2.5 text-right text-xs tabular-nums">
                  {formerSummary.sums.requests}
                </td>
                <td className="px-3 py-2.5 text-right text-xs tabular-nums">
                  {formerSummary.sums.open_requests}
                </td>
                <td className="px-3 py-2.5 text-right text-xs tabular-nums">
                  {formerSummary.sums.placements}
                </td>
                <td className="px-4 py-2.5 text-right text-xs">—</td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-muted-foreground">
        Okno: rok {data.period.start.slice(0, 4)}, niezależnie od okresu
        wybranego wyżej — hit ratio z miesiąca skacze o dziesiątki punktów.{" "}
        {DL_HIT_RATIO_PORTFOLIO_NOTE} Cel {data.hit_ratio_target_pct}%. Klienci
        każdego DL —{" "}
        <Link href={reportHref("portfele-dl", period)} className="font-semibold text-primary hover:underline">
          raport Portfele Delivery Leadów
        </Link>
        . Byli członkowie zespołu (konto wyłączone) stoją jednym wierszem pod listą —
        ich liczby zostają w sumach. Klik w nagłówek sortuje kolumnę.
      </p>
    </div>
  );
}
