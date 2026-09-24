"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { cn } from "@/lib/utils";
import {
  insightsApi,
  insightsBoardApi,
  insightsQueryKeys,
  type InsightsPeriodParams,
  type RecruitmentFunnelResponse,
} from "@/lib/insights-api";
import {
  insightsFlagsApi,
  performanceFlagsQueryKey,
} from "@/lib/insights-flags-api";
import { buildFunnelCsvExport } from "@/lib/insights-csv";
import { reportHref, type ReportId } from "@/lib/insights-reports";
import {
  insightsTeamSignalsApi,
  insightsTeamSignalsQueryKeys,
  type TeamPeopleRow,
} from "@/lib/insights-team-api";
import {
  buildSteps,
  countDelta,
  DL_HIT_RATIO_PORTFOLIO_NOTE,
  isPeopleRowWorthShowing,
  previousComparablePeriod,
  weakestStepIndex,
  weakestStepSentence,
} from "@/lib/insights-views";
import { isBlockingViewState, resolveViewState } from "@/lib/view-state";
import { hasAnalyticsCapability, hasRole, useAuthStore } from "@/store/auth";
import { PeriodPicker } from "@/components/insights/PeriodPicker";
import { useInsightsPeriod } from "@/components/insights/useInsightsPeriod";
import { InsightsFlagAdmin } from "@/components/insights/sections/InsightsFlagAdmin";
import {
  InsightsPerformanceFlags,
  PerformanceFlagsLoadNotice,
} from "@/components/insights/sections/InsightsPerformanceFlag";
import { SectionError } from "@/components/insights/sections/_shared";
import {
  FunnelBars,
  Panel,
  PanelLoading,
  Takeaway,
  Tile,
  TileRow,
  ViewHeader,
} from "./ViewKit";

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

const STEPS = [
  { stage: "verified", label: "Zweryfikowani" },
  { stage: "cv_sent", label: "CV wysłane" },
  { stage: "interview", label: "Rozmowy" },
  { stage: "hired", label: "Zatrudnieni" },
] as const;

function stageCount(funnel: RecruitmentFunnelResponse | undefined, stage: string) {
  return funnel?.stages.find((s) => s.stage === stage)?.count ?? null;
}

/**
 * Zespół — „Jak idzie zespołowi i gdzie tracimy ludzi?".
 *
 * Kafle i lejek widzi każdy (lejek firmy, jak dotąd w Insights). Tabelę
 * ludzi i „Do uwagi" — role z `view_team_kpi` (HoR, Delivery Lead, TCM,
 * Finanse, admin): to imienne wyniki cudzej pracy. Bez kwot.
 */
export function ZespolView() {
  const user = useAuthStore((state) => state.user);
  const seesTeam =
    hasRole(user, "admin") || hasAnalyticsCapability(user, "view_team_kpi");
  const { period, setPeriod } = useInsightsPeriod(ZESPOL_DEFAULT_PERIOD);
  const today = useMemo(() => new Date(), []);
  const previous = useMemo(
    () => previousComparablePeriod(period, today),
    [period, today],
  );

  const funnelQuery = useQuery({
    queryKey: ["insights", "recruitment", "funnel", period],
    queryFn: () => insightsApi.recruitmentFunnel(period),
  });
  const previousFunnelQuery = useQuery({
    queryKey: ["insights", "recruitment", "funnel", previous?.params ?? null],
    queryFn: () =>
      insightsApi.recruitmentFunnel(previous!.params as InsightsPeriodParams),
    enabled: previous !== null,
  });

  const funnel = funnelQuery.data;
  const prevFunnel = previousFunnelQuery.data;
  const viewState = resolveViewState({
    isLoading: funnelQuery.isPending,
    isSuccess: funnelQuery.isSuccess,
    isError: funnelQuery.isError,
    error: funnelQuery.error,
  });

  const steps = buildSteps(
    STEPS.map((s) => s.label),
    STEPS.map((s) => stageCount(funnel, s.stage) ?? 0),
  );
  const prevSteps = prevFunnel
    ? buildSteps(
        STEPS.map((s) => s.label),
        STEPS.map((s) => stageCount(prevFunnel, s.stage) ?? 0),
      )
    : undefined;
  const sentence = weakestStepSentence(steps, {
    previous: prevSteps,
    previousLabel: previous?.label,
  });

  const tile = (stage: string, label: string) => {
    const current = stageCount(funnel, stage);
    const before = prevFunnel ? stageCount(prevFunnel, stage) : null;
    return (
      <Tile
        key={stage}
        label={label}
        value={current === null ? "—" : current.toLocaleString("pl-PL")}
        delta={previous ? countDelta(current, before, previous.label) : null}
      />
    );
  };

  return (
    <div className="space-y-6">
      <ViewHeader
        question="Jak idzie zespołowi?"
        lede={
          previous
            ? `Porównanie: ${previous.label}. Liczone: pierwsze wejście pary (kandydat, rekrutacja) na etap w wybranym okresie.`
            : "Liczone: pierwsze wejście pary (kandydat, rekrutacja) na etap w wybranym okresie."
        }
        actions={
          <PeriodPicker
            value={period}
            onChange={setPeriod}
            defaultValue={ZESPOL_DEFAULT_PERIOD}
            resolved={funnel?.period ?? null}
            csv={buildFunnelCsvExport(funnel)}
          />
        }
      />

      {viewState === "loading" ? (
        <PanelLoading />
      ) : isBlockingViewState(viewState) ? (
        <SectionError
          label="Zespół"
          error={funnelQuery.error}
          onRetry={() => void funnelQuery.refetch()}
        />
      ) : (
        <>
          <TileRow>
            {tile("hired", "Placementy")}
            {tile("cv_sent", "CV wysłane do klienta")}
            {tile("interview", "Rozmowy")}
            {tile("verified", "Zweryfikowani")}
          </TileRow>

          <div
            className={cn(
              "grid grid-cols-1 gap-4",
              seesTeam && "xl:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]",
            )}
          >
            <Panel
              title="Gdzie tracimy ludzi"
              hint="% osób, które przeszły z poprzedniego etapu"
            >
              <FunnelBars steps={steps} highlight={weakestStepIndex(steps)} />
              {sentence ? <Takeaway>{sentence}</Takeaway> : null}
              <Link
                href={reportHref("lejek-etapy", period)}
                className="text-sm font-semibold text-primary hover:underline"
              >
                Wszystkie etapy i odznaki Tablicy →
              </Link>
            </Panel>
            {seesTeam ? <AttentionPanel /> : null}
          </div>
        </>
      )}

      {seesTeam ? (
        <PeoplePanel period={period} previousLabel={previous?.label ?? null} />
      ) : (
        <p className="rounded-xl border border-border bg-card p-4 text-sm text-muted-foreground">
          Wyniki poszczególnych osób widzą liderzy zespołu (Head of Recruitment,
          Delivery Lead). Swoje liczby znajdziesz w zakładce „Mój miesiąc”.
        </p>
      )}
    </div>
  );
}

function AttentionPanel() {
  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: insightsTeamSignalsQueryKeys.attention(),
    queryFn: () => insightsTeamSignalsApi.attention(),
  });
  return (
    <Panel title="Do uwagi">
      {isPending ? (
        <PanelLoading />
      ) : isError ? (
        <SectionError
          label="Do uwagi"
          error={error}
          onRetry={() => void refetch()}
        />
      ) : data.items.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          Nic nie wymaga uwagi — żaden sygnał nie przekracza progu.
        </p>
      ) : (
        <ul className="divide-y divide-border">
          {data.items.map((item) => (
            <li key={item.kind} className="flex items-start gap-3 py-3">
              <span className="min-w-8 text-xl font-semibold tabular-nums text-warning-muted-foreground">
                {item.count}
              </span>
              <div className="min-w-0 text-sm leading-snug">
                <p className="text-foreground">{item.label}</p>
                {item.report ? (
                  <Link
                    href={reportHref(item.report as ReportId)}
                    className="font-semibold text-primary hover:underline"
                  >
                    Pokaż listę
                  </Link>
                ) : (
                  <a
                    href="#ludzie"
                    className="font-semibold text-primary hover:underline"
                  >
                    Zobacz w tabeli
                  </a>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </Panel>
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

  return (
    <section id="ludzie" className="scroll-mt-24 space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="text-base font-semibold text-foreground">Ludzie</h3>
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
      {scope === "recruiters" ? (
        <RecruiterTable period={period} previousLabel={previousLabel} />
      ) : (
        <DeliveryTable />
      )}
    </section>
  );
}

function RecruiterTable({
  period,
  previousLabel,
}: {
  period: InsightsPeriodParams;
  previousLabel: string | null;
}) {
  const peopleQuery = useQuery({
    queryKey: insightsTeamSignalsQueryKeys.people(period),
    queryFn: () => insightsTeamSignalsApi.people(period),
  });
  const flagsQuery = useQuery({
    queryKey: performanceFlagsQueryKey,
    queryFn: () => insightsFlagsApi.list(),
  });
  const data = peopleQuery.data;
  const rows = (data?.rows ?? []).filter(isPeopleRowWorthShowing);
  const quiet = (data?.rows.length ?? 0) - rows.length;
  const outside = data?.outside_scope;

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
  return (
    <div className="space-y-2">
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
              <th className="sticky left-0 bg-card px-4 py-2.5 text-left font-semibold">
                Osoba
              </th>
              <th className="px-3 py-2.5 text-right font-semibold">Weryf. / dzień</th>
              <th className="px-3 py-2.5 text-right font-semibold">CV wysłane</th>
              <th className="px-3 py-2.5 text-right font-semibold">Rozmowy</th>
              <th className="px-3 py-2.5 text-right font-semibold">Placementy</th>
              <th className="px-3 py-2.5 text-right font-semibold">Precyzja 30 dni</th>
              <th className="px-4 py-2.5 text-right font-semibold">
                {previousLabel ? "Placementy vs poprzednio" : "Zmiana"}
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-4 py-6 text-center text-muted-foreground">
                  Nikt nie ruszył jeszcze kandydata w tym okresie.
                </td>
              </tr>
            ) : (
              rows.map((row) => (
                <PersonRow
                  key={row.user_id}
                  row={row}
                  lowPrecision={low}
                  flags={flagsQuery.data?.flags_by_user?.[String(row.user_id)] ?? []}
                  flagTypes={flagsQuery.data?.types ?? []}
                />
              ))
            )}
            {outside && outside.people > 0 ? (
              <tr className="border-t border-border text-muted-foreground">
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
                  {outside.placements}
                </td>
                <td className="px-3 py-2.5 text-right text-xs">—</td>
                <td className="px-4 py-2.5 text-right text-xs">—</td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-muted-foreground">
        {quiet > 0 ? `Pominięto osoby bez ruchu w tym okresie: ${quiet}. ` : ""}
        {data.totals.unattributed > 0
          ? `${data.totals.unattributed} ruchów nie da się przypisać nikomu — są w lejku, nie ma ich w tabeli. `
          : ""}
        Liczone jak w wyścigach i „Mój miesiąc”: CV wysłane, rozmowy
        i placementy pary dostaje osoba, która zweryfikowała kandydata — dlatego
        liczby różnią się od kafli wyżej i od raportu „Aktywność zespołu” (tam
        liczy się osoba, która przesunęła etap). Precyzja: z osób
        zweryfikowanych w ostatnich 30 dniach — ilu wysłano CV do klienta; „—” =
        mniej niż 5 weryfikacji. Konta administracyjne stoją jednym wierszem
        pod tabelą, jak w Hall of Fame.
      </p>
    </div>
  );
}

function PersonRow({
  row,
  lowPrecision,
  flags,
  flagTypes,
}: {
  row: TeamPeopleRow;
  lowPrecision: number;
  flags: Parameters<typeof InsightsPerformanceFlags>[0]["flags"];
  flagTypes: Parameters<typeof InsightsFlagAdmin>[0]["types"];
}) {
  const delta = countDelta(row.placements, row.previous_placements, "");
  const isLow = row.precision_pct !== null && row.precision_pct < lowPrecision;
  return (
    <tr className="border-b border-border/60 last:border-b-0">
      <td className="sticky left-0 bg-card px-4 py-2.5">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium text-foreground">{row.name}</span>
          {!row.is_active ? (
            <span className="rounded bg-muted px-1.5 py-0.5 text-[11px] text-muted-foreground">
              były pracownik
            </span>
          ) : null}
          <InsightsPerformanceFlags flags={flags} />
          <InsightsFlagAdmin
            userId={row.user_id}
            userName={row.name}
            flags={flags}
            types={flagTypes}
          />
        </div>
      </td>
      <td className="px-3 py-2.5 text-right tabular-nums">
        {row.verifications_per_workday === null
          ? "—"
          : row.verifications_per_workday.toLocaleString("pl-PL")}
      </td>
      <td className="px-3 py-2.5 text-right tabular-nums">{row.recommendations}</td>
      <td className="px-3 py-2.5 text-right tabular-nums">{row.interviews}</td>
      <td className="px-3 py-2.5 text-right font-semibold tabular-nums">
        {row.placements}
      </td>
      <td
        className={cn(
          "px-3 py-2.5 text-right tabular-nums",
          isLow && "font-semibold text-warning-muted-foreground",
        )}
      >
        {row.precision_pct === null ? "—" : `${Math.round(row.precision_pct)}%`}
      </td>
      <td
        className={cn(
          "px-4 py-2.5 text-right tabular-nums",
          delta?.tone === "good" && "text-success-muted-foreground",
          delta?.tone === "bad" && "text-warning-muted-foreground",
          (!delta || delta.tone === "neutral") && "text-muted-foreground",
        )}
      >
        {!delta || delta.tone === "neutral"
          ? "bez zmian"
          : `${row.placements > row.previous_placements ? "▲" : "▼"} ${Math.abs(row.placements - row.previous_placements)}`}
      </td>
    </tr>
  );
}

function DeliveryTable() {
  const period = ZESPOL_DL_PERIOD;
  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: insightsQueryKeys.dlPortfolio(period),
    queryFn: () => insightsBoardApi.dlPortfolio(period),
  });
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
  return (
    <div className="space-y-2">
      <div className="overflow-x-auto rounded-xl border border-border bg-card shadow-xs">
        <table className="w-full min-w-[40rem] text-sm">
          <thead>
            <tr className="border-b border-border text-xs uppercase tracking-wide text-muted-foreground">
              <th className="sticky left-0 bg-card px-4 py-2.5 text-left font-semibold">
                Delivery Lead
              </th>
              <th className="px-3 py-2.5 text-right font-semibold">Rekrutacje</th>
              <th className="px-3 py-2.5 text-right font-semibold">Otwarte</th>
              <th className="px-3 py-2.5 text-right font-semibold">Placementy</th>
              <th className="px-4 py-2.5 text-right font-semibold">Hit ratio</th>
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
              data.leads.map((lead) => (
                <tr key={lead.dl_id} className="border-b border-border/60 last:border-b-0">
                  <td className="sticky left-0 bg-card px-4 py-2.5 font-medium text-foreground">
                    {lead.dl_name}
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
        .
      </p>
    </div>
  );
}
