"use client";

import { useQuery } from "@tanstack/react-query";

import { cn } from "@/lib/utils";
import { insightsApi, insightsQueryKeys, type WeeklyTrendResponse } from "@/lib/insights-api";
import { SectionError } from "@/components/insights/sections/_shared";

import { Panel, PanelLoading } from "../ViewKit";

const WEEKS = 8;

const SERIES = [
  { key: "verified", label: "Weryfikacje" },
  { key: "cv_sent", label: "Rekomendacje" },
  { key: "acceptance", label: "Akceptacje" },
  { key: "hired", label: "Placementy" },
] as const;

type SeriesKey = (typeof SERIES)[number]["key"];

function weekLabel(iso: string): string {
  return `${Number(iso.slice(8, 10))}.${iso.slice(5, 7)}`;
}

/** Słupki tygodni jednej serii; `null` (etap nieodnotowywany) = pusty słupek. */
function Bars({ weeks, series }: { weeks: WeeklyTrendResponse["weeks"]; series: SeriesKey }) {
  const values = weeks.map((w) => w.counts[series]);
  const max = Math.max(1, ...values.map((v) => v ?? 0));
  const label = SERIES.find((s) => s.key === series)?.label ?? series;
  const spoken = weeks
    .map((w) => `${weekLabel(w.week_start)}: ${w.counts[series] ?? "brak danych"}`)
    .join(", ");
  return (
    <div className="space-y-1.5">
      <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{label}</p>
      <div role="img" aria-label={`${label} tydzień po tygodniu — ${spoken}`} className="flex h-16 items-end gap-1">
        {weeks.map((w, i) => {
          const v = values[i];
          return (
            <span
              key={w.week_start}
              title={`Tydzień od ${weekLabel(w.week_start)}: ${v ?? "brak danych"}${w.partial ? " (trwa)" : ""}`}
              className={cn(
                "flex-1 rounded-t",
                v === null ? "h-1 bg-muted" : w.partial ? "bg-primary/40" : "bg-primary",
              )}
              style={v === null ? undefined : { height: `${Math.max(4, (100 * v) / max)}%` }}
            />
          );
        })}
      </div>
      <p className="text-xs tabular-nums text-muted-foreground">
        ten tydzień: {values[values.length - 1] ?? "—"} · poprzedni: {values[values.length - 2] ?? "—"}
      </p>
    </div>
  );
}

/** „Ostatnie 8 tygodni” — kierunek, którego jeden miesiąc nie pokazuje. */
export function WeeklyTrendPanel() {
  const query = useQuery({
    queryKey: insightsQueryKeys.weeklyTrend(WEEKS),
    queryFn: () => insightsApi.weeklyTrend(WEEKS),
    staleTime: 5 * 60 * 1000,
  });
  if (query.isPending) return <PanelLoading />;
  if (query.isError) {
    return (
      <SectionError label="Ostatnie tygodnie" error={query.error} onRetry={() => void query.refetch()} />
    );
  }
  const weeks = query.data.weeks;
  return (
    <Panel title={`Ostatnie ${WEEKS} tygodni`} hint="jaśniejszy słupek = tydzień trwa">
      <div className="grid grid-cols-2 gap-x-6 gap-y-4 lg:grid-cols-4">
        {SERIES.map((s) => (
          <Bars key={s.key} weeks={weeks} series={s.key} />
        ))}
      </div>
      <p className="text-xs text-muted-foreground">
        Akceptacje liczą się od 12.10.2026 — wcześniejsze tygodnie są puste, nie zerowe.
      </p>
    </Panel>
  );
}
