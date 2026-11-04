"use client";

import { useEffect, useMemo, useRef, type ReactNode, type RefObject } from "react";
import { useSearchParams } from "next/navigation";
import { useQueries } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { WhoCountsList, type WhoCountsQuery } from "@/components/v2/kpi/WhoCountsList";
import { Panel } from "@/components/insights/views/ViewKit";
import {
  PERSONAL_WHO_COUNTS,
  TEAM_WHO_COUNTS,
  WHO_COUNTS_ANCHOR,
  WHO_COUNTS_METRICS,
  currentPeriodHint,
  isIsoDay,
  isLatestPeriod,
  metricFromSlug,
  periodRange,
  periodKindFromSlug,
  periodKindSlug,
  periodLabel,
  rangeLabel,
  shiftPeriod,
  warsawToday,
  type DayRange,
  type WhoCountsMetric,
  type WhoCountsPeriodKind,
  teamListReconcile,
} from "@/lib/kpi-who-counts";
import { getRecruitmentActivityDetails } from "@/lib/recruitment-activity-api";
import { useUrlWriter } from "@/lib/url-selection";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/store/auth";

const KIND_LABELS: Record<WhoCountsPeriodKind, string> = {
  day: "Dzień",
  week: "Tydzień",
  month: "Miesiąc",
};

function useViewer() {
  const user = useAuthStore((state) => state.user);
  return {
    viewerId: user?.id ?? null,
    cacheKey: `${user?.id ?? "anonymous"}:${user?.authorization_version ?? "none"}`,
  };
}

/** Wejście z linku „#kto-sie-liczy” — lista stoi niżej niż górna krawędź ekranu. */
function useScrollIntoViewOnAnchor(ref: RefObject<HTMLElement | null>) {
  useEffect(() => {
    if (window.location.hash === `#${WHO_COUNTS_ANCHOR}`) {
      ref.current?.scrollIntoView({ block: "start" });
    }
  }, [ref]);
}

function MetricTabs({
  metrics,
  active,
  onChange,
}: {
  metrics: readonly WhoCountsMetric[];
  active: WhoCountsMetric;
  onChange: (metric: WhoCountsMetric) => void;
}) {
  return (
    <div
      role="group"
      aria-label="Cel"
      className="inline-flex w-fit overflow-hidden rounded-lg border border-border"
    >
      {metrics.map((metric) => (
        <button
          key={metric}
          type="button"
          aria-pressed={metric === active}
          onClick={() => onChange(metric)}
          className={cn(
            "whitespace-nowrap border-r border-border px-3 py-1.5 text-sm last:border-r-0 focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring",
            metric === active
              ? "bg-primary/10 font-semibold text-primary"
              : "text-muted-foreground hover:bg-muted hover:text-foreground",
          )}
        >
          {WHO_COUNTS_METRICS[metric].label}
        </button>
      ))}
    </div>
  );
}

/**
 * „Kto się liczy do celów” w Insights → Mój miesiąc: osoby za liczbami
 * z panelu celów w górnym pasku, w okresie celu i wcześniejszych.
 * Stan (cel, okres, dzień) jest w adresie, więc link z panelu otwiera
 * właściwą zakładkę, a „Wstecz” nie gubi wyboru.
 */
export function MyWhoCountsPanel() {
  const ref = useRef<HTMLDivElement>(null);
  useScrollIntoViewOnAnchor(ref);
  const searchParams = useSearchParams();
  const { replaceUrl } = useUrlWriter();
  const { viewerId, cacheKey } = useViewer();
  const today = useMemo(() => warsawToday(), []);

  const metric = metricFromSlug(searchParams.get("kto")) ?? "recommendation";
  const kinds: WhoCountsPeriodKind[] =
    metric === "placement" ? ["week", "month"] : ["day", "week", "month"];
  const requestedKind = periodKindFromSlug(searchParams.get("okres"));
  const kind =
    requestedKind && kinds.includes(requestedKind)
      ? requestedKind
      : WHO_COUNTS_METRICS[metric].defaultKind;
  const rawDay = searchParams.get("dzien");
  const anchor = isIsoDay(rawDay) && rawDay <= today ? rawDay : today;

  const write = (next: {
    metric?: WhoCountsMetric;
    kind?: WhoCountsPeriodKind;
    anchor?: string | null;
  }) => {
    const params = new URLSearchParams(searchParams.toString());
    const nextMetric = next.metric ?? metric;
    params.set("kto", WHO_COUNTS_METRICS[nextMetric].slug);
    // Inny cel = jego własny okres (weryfikacje dziś, rekomendacje w tygodniu).
    const nextKind = next.metric && next.metric !== metric ? null : (next.kind ?? kind);
    if (nextKind) params.set("okres", periodKindSlug(nextKind));
    else params.delete("okres");
    const nextAnchor = next.anchor === undefined ? anchor : next.anchor;
    // Okres z dzisiejszym dniem nie ma `dzien` w adresie — jak wejście z panelu celów.
    const current =
      nextAnchor !== null &&
      nextKind !== null &&
      periodRange(nextKind, nextAnchor).start <= today &&
      today <= periodRange(nextKind, nextAnchor).end;
    if (nextAnchor && nextKind && !current) params.set("dzien", nextAnchor);
    else params.delete("dzien");
    // Bieżąca ścieżka, nie `/insights` na sztywno: ten sam panel stoi
    // w harnessie `/preview/insights`, a inna ścieżka idzie przez router.
    replaceUrl(`${window.location.pathname}?${params.toString()}`);
  };

  const hint = currentPeriodHint(kind, anchor, today);
  const latest = isLatestPeriod(kind, anchor, today);

  return (
    <div ref={ref} id={WHO_COUNTS_ANCHOR} className="scroll-mt-20">
      <Panel
        title="Kto się liczy do celów"
        hint="osoby za liczbami z panelu celów w górnym pasku"
      >
        <div className="flex flex-wrap items-center justify-between gap-3">
          <MetricTabs
            metrics={PERSONAL_WHO_COUNTS}
            active={metric}
            onChange={(next) => write({ metric: next, anchor: null })}
          />
          <div className="flex flex-wrap items-center gap-2">
            <div
              role="group"
              aria-label="Okres"
              className="inline-flex overflow-hidden rounded-lg border border-border"
            >
              {kinds.map((option) => (
                <button
                  key={option}
                  type="button"
                  aria-pressed={option === kind}
                  onClick={() => write({ kind: option, anchor: null })}
                  className={cn(
                    "border-r border-border px-2.5 py-1 text-xs last:border-r-0 focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring",
                    option === kind
                      ? "bg-muted font-semibold text-foreground"
                      : "text-muted-foreground hover:bg-muted",
                  )}
                >
                  {KIND_LABELS[option]}
                </button>
              ))}
            </div>
            <Button
              type="button"
              size="icon"
              variant="outline"
              className="h-8 w-8"
              aria-label="Poprzedni okres"
              onClick={() => write({ anchor: shiftPeriod(kind, anchor, -1) })}
            >
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <span className="min-w-[9rem] text-center text-sm">
              <span className="inline-block font-semibold first-letter:uppercase">
                {periodLabel(kind, anchor, today)}
              </span>
              {hint ? <span className="ml-1.5 text-muted-foreground">{hint}</span> : null}
            </span>
            <Button
              type="button"
              size="icon"
              variant="outline"
              className="h-8 w-8"
              aria-label="Następny okres"
              disabled={latest}
              onClick={() => write({ anchor: shiftPeriod(kind, anchor, 1) })}
            >
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>
        </div>
        {viewerId === null ? null : (
          <WhoCountsList
            metric={metric}
            viewerId={viewerId}
            cacheKey={cacheKey}
            query={myWhoCountsQuery(kind, anchor, viewerId)}
          />
        )}
      </Panel>
    </div>
  );
}

/**
 * Zapytanie listy osoby: zawsze od początku okresu, żeby ten sam tydzień
 * z dowolnego dnia miał jeden klucz w pamięci zapytań.
 */
export function myWhoCountsQuery(
  kind: WhoCountsPeriodKind,
  anchor: string,
  viewerId: number,
): WhoCountsQuery {
  const start = periodRange(kind, anchor).start;
  return { window: kind, day: start, month: start.slice(0, 7), subjectUserId: viewerId };
}

/** Kogo lider otworzył z tabeli Insights → Zespół → Ludzie. */
export type TeamWhoCountsSubject =
  | { kind: "person"; id: number; name: string }
  | { kind: "unattributed" }
  // Liczba z lejka zespołu (23.10.2026) — wszyscy z zasługą razem.
  | { kind: "team" };

function subjectQuery(subject: TeamWhoCountsSubject): Partial<WhoCountsQuery> {
  if (subject.kind === "person") return { subjectUserId: subject.id };
  if (subject.kind === "team") return { teamScope: true };
  return { unattributed: true };
}

const SUBJECT_LABEL = {
  unattributed: "Bez osoby z zasługą",
  team: "Cały zespół",
} as const;

/**
 * Lista osoby z tabeli „Ludzie” w okresie z paska Insights. Wiersze liczy ta
 * sama atrybucja co tabela, więc ich liczba to liczba z klikniętej komórki.
 */
export function TeamWhoCountsPanel({
  subject,
  metric,
  range,
  metrics = TEAM_WHO_COUNTS,
  notice,
  onMetricChange,
  onClose,
}: {
  /** Linijka nad listą (lejek: pary bez osoby z zasługą, różnica z liczbą). */
  notice?: ReactNode;
  subject: TeamWhoCountsSubject;
  metric: WhoCountsMetric;
  range: DayRange;
  metrics?: readonly WhoCountsMetric[];
  onMetricChange: (metric: WhoCountsMetric) => void;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const { viewerId, cacheKey } = useViewer();
  const today = useMemo(() => warsawToday(), []);
  const subjectKey = subject.kind === "person" ? subject.id : subject.kind;

  useEffect(() => {
    ref.current?.scrollIntoView({ block: "nearest" });
  }, [subjectKey]);

  const who = subject.kind === "person" ? subject.name : SUBJECT_LABEL[subject.kind];
  return (
    <div ref={ref} id={WHO_COUNTS_ANCHOR} className="scroll-mt-20">
      <Panel
        title={`Kto się liczy · ${who}`}
        hint={rangeLabel(range, today)}
        actions={
          <Button
            type="button"
            size="sm"
            variant="ghost"
            onClick={onClose}
            aria-label="Zamknij listę"
            className="ml-auto"
          >
            <X className="mr-1 h-4 w-4" />
            Zamknij
          </Button>
        }
      >
        <MetricTabs metrics={metrics} active={metric} onChange={onMetricChange} />
        {notice}
        <WhoCountsList
          metric={metric}
          viewerId={viewerId}
          cacheKey={cacheKey}
          query={{
            window: "range",
            day: range.start,
            month: range.start.slice(0, 7),
            dateFrom: range.start,
            dateTo: range.end,
            ...subjectQuery(subject),
          }}
        />
      </Panel>
    </div>
  );
}

/**
 * Pod listą całego zespołu z lejka: ile par nie ma osoby z zasługą i czy suma
 * zgadza się z klikniętą liczbą. Dwa lekkie zapytania (strona po 1 wierszu).
 */
export function TeamListReconcileLine({
  metric,
  range,
  clicked,
  onShowUnattributed,
}: {
  metric: WhoCountsMetric;
  range: DayRange;
  clicked: number | null;
  onShowUnattributed: () => void;
}) {
  const { cacheKey } = useViewer();
  const base = {
    metric,
    window: "range" as const,
    day: range.start,
    month: range.start.slice(0, 7),
    dateFrom: range.start,
    dateTo: range.end,
    page: 1,
    pageSize: 1,
  };
  const [team, without] = useQueries({
    queries: [
      { teamScope: true },
      { unattributed: true },
    ].map((scope) => ({
      queryKey: ["who-counts-reconcile", cacheKey, metric, range.start, range.end, scope],
      queryFn: () => getRecruitmentActivityDetails({ ...base, ...scope }),
      staleTime: 30_000,
    })),
  });
  if (!team.data || !without.data) return null;
  const sentence = teamListReconcile(
    metric,
    clicked,
    team.data.period_total ?? team.data.total,
    without.data.period_total ?? without.data.total,
  );
  if (!sentence.unattributed && !sentence.mismatch) return null;
  return (
    <p className="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-xs text-muted-foreground">
      {sentence.unattributed ? (
        <span>
          {sentence.unattributed}{" "}
          <button
            type="button"
            onClick={onShowUnattributed}
            className="font-semibold text-primary hover:underline"
          >
            Pokaż
          </button>
        </span>
      ) : null}
      {sentence.mismatch ? <span>{sentence.mismatch}</span> : null}
    </p>
  );
}
