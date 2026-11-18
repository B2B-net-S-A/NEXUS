"use client";

import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronLeft, ChevronRight } from "lucide-react";

import { QueryStateNotice } from "@/components/ds";
import { Button } from "@/components/ui/button";
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import { TeamFunnelPanel } from "@/components/insights/views/team/TeamFunnelPanel";
import { useBoardPeople, type BoardPeople, type PeoplePeriod } from "@/lib/api/supervisory-board";
import { insightsApi } from "@/lib/insights-api";
import { comparableSteps, teamFunnelSteps } from "@/lib/insights-team-funnel";
import { weakestStepSentence } from "@/lib/insights-views";
import { cn, formatDate } from "@/lib/utils";
import { isBlockingViewState, resolveViewState } from "@/lib/view-state";
import { firmaConclusions } from "./firma-conclusions";

const PERIODS: { value: PeoplePeriod["period"]; label: string }[] = [
  { value: "month", label: "Miesiąc" },
  { value: "quarter", label: "Kwartał" },
  { value: "year", label: "Rok" },
];

function windowLabel(data: BoardPeople | undefined): string {
  if (!data) return "";
  return `${formatDate(data.window.from)} – ${formatDate(data.window.to)}`;
}

/**
 * „Firma” dla Rady (R7). Uwagi Rady z 18.11.2026: widok z Insights był za
 * rozbudowany — zostają placementy, kontraktorzy na projektach, zejścia
 * z opisem powodów i wnioski; lejek zwinięty pod wnioskami. Insights → Firma
 * zostaje bez zmian dla Finansów i admina.
 */
export function RadaFirmaTab() {
  const [period, setPeriod] = React.useState<PeoplePeriod>({ period: "quarter", offset: 0 });
  const people = useBoardPeople(period);
  const funnel = useQuery({
    queryKey: ["insights", "recruitment", "funnel", period],
    queryFn: () => insightsApi.recruitmentFunnel(period),
  });
  const state = resolveViewState({
    isLoading: people.isLoading,
    isError: people.isError,
    error: people.error,
    isSuccess: people.isSuccess,
  });
  const funnelSentence = funnel.data
    ? weakestStepSentence(comparableSteps(teamFunnelSteps(funnel.data, undefined, undefined, undefined)))
    : null;
  const data = people.data;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-lg font-semibold text-foreground">Jak idzie firma?</h2>
          <p className="text-[12px] text-muted-foreground">{windowLabel(data)}</p>
        </div>
        <div className="flex items-center gap-2">
          <SegmentedRadio<PeoplePeriod["period"]>
            label="Okres"
            size="sm"
            value={period.period}
            onChange={(p) => setPeriod({ period: p, offset: 0 })}
            options={PERIODS}
          />
          <Button
            size="sm"
            variant="outline"
            className="h-8 w-8 p-0"
            aria-label="Poprzedni okres"
            onClick={() => setPeriod((p) => ({ ...p, offset: p.offset - 1 }))}
          >
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <Button
            size="sm"
            variant="outline"
            className="h-8 w-8 p-0"
            aria-label="Następny okres"
            disabled={period.offset >= 0}
            onClick={() => setPeriod((p) => ({ ...p, offset: Math.min(0, p.offset + 1) }))}
          >
            <ChevronRight className="h-4 w-4" />
          </Button>
        </div>
      </div>

      {isBlockingViewState(state) ? (
        <QueryStateNotice state={state as "forbidden" | "not_found" | "error"} onRetry={() => people.refetch()} />
      ) : !data ? (
        <div className="h-40 animate-pulse rounded-lg border border-border bg-card" aria-hidden />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Tile
              label="Placementy"
              value={data.placements.count}
              sub={`poprzedni okres ${data.placements.previous}`}
            />
            <Tile
              label="Kontraktorzy na projektach"
              value={data.contractors.active}
              sub={`u ${data.contractors.clients} klientów · wcześniej ${data.contractors.previous}`}
            />
            <Tile
              label="Zejścia"
              value={data.exits.count}
              tone={data.exits.count > data.placements.count ? "bad" : "neutral"}
              sub={`w tym rezygnacje ${data.flows.resignations} · poprzednio ${data.flows.previous_ends}`}
            />
            <Tile
              label="Netto (start − zejście)"
              value={data.flows.starts - data.flows.ends}
              signed
              tone={data.flows.starts - data.flows.ends < 0 ? "bad" : "good"}
              sub={`zaczęło ${data.flows.starts}, odeszło ${data.flows.ends}`}
            />
          </div>

          <section className="rounded-lg border border-border bg-card p-4">
            <h3 className="mb-2 text-sm font-semibold text-foreground">Wnioski</h3>
            <ul className="space-y-1.5 text-[13px] leading-relaxed text-foreground">
              {firmaConclusions(data, funnelSentence).map((line) => (
                <li key={line} className="flex gap-2">
                  <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-primary" aria-hidden />
                  <span>{line}</span>
                </li>
              ))}
            </ul>
            <details className="group mt-3 border-t border-border pt-2">
              <summary className="flex min-h-9 cursor-pointer list-none items-center gap-1 text-[13px] font-semibold text-primary">
                <ChevronDown className="h-4 w-4 transition-transform group-open:rotate-180" />
                Lejek rekrutacji w okresie
              </summary>
              <div className="pt-2">
                {funnel.data ? (
                  <TeamFunnelPanel
                    funnel={funnel.data}
                    previous={undefined}
                    previousLabel={undefined}
                    inFlight={undefined}
                    period={period}
                    canOpenList={false}
                  />
                ) : funnel.isError ? (
                  <p className="text-[12px] text-destructive">Nie udało się wczytać lejka.</p>
                ) : (
                  <div className="h-24 animate-pulse rounded-md bg-muted" aria-hidden />
                )}
              </div>
            </details>
          </section>

          <div className="grid gap-3 xl:grid-cols-2">
            <ContractorsPanel data={data} />
            <PlacementsPanel data={data} />
          </div>
          <ExitsPanel data={data} />
        </>
      )}
    </div>
  );
}

function Tile({
  label,
  value,
  sub,
  tone = "neutral",
  signed,
}: {
  label: string;
  value: number;
  sub: string;
  tone?: "neutral" | "bad" | "good";
  signed?: boolean;
}) {
  return (
    <div className="min-w-0 rounded-lg border border-border bg-card px-3.5 py-3">
      <div className="text-[12px] font-medium text-muted-foreground">{label}</div>
      <div
        className={cn(
          "mt-1 text-[24px] font-semibold leading-tight tabular-nums",
          tone === "bad" && "text-destructive",
          tone === "good" && "text-success-muted-foreground",
          tone === "neutral" && "text-foreground",
        )}
      >
        {signed && value > 0 ? `+${value}` : value}
      </div>
      <div className="mt-1 text-[11px] leading-snug text-muted-foreground">{sub}</div>
    </div>
  );
}

const cellClass = "border-b border-border px-2 py-1.5";

function ContractorsPanel({ data }: { data: BoardPeople }) {
  return (
    <section className="min-w-0 rounded-lg border border-border bg-card p-4">
      <h3 className="mb-2 text-sm font-semibold text-foreground">Kontraktorzy na projektach</h3>
      {data.contractors.by_client.length === 0 ? (
        <p className="text-[12px] text-muted-foreground">Na koniec okresu nikt nie pracuje na kontrakcie.</p>
      ) : (
        <table className="w-full text-[12px] tabular-nums">
          <thead>
            <tr className="text-[11px] text-muted-foreground">
              <th className={cn(cellClass, "text-left font-medium")}>Klient</th>
              <th className={cn(cellClass, "text-right font-medium")}>Kontraktorzy</th>
              <th className={cn(cellClass, "text-right font-medium")}>Udział</th>
            </tr>
          </thead>
          <tbody>
            {data.contractors.by_client.map((row) => (
              <tr key={row.client} className={cn(row.rest && "text-muted-foreground")}>
                <td className={cellClass}>{row.client}</td>
                <td className={cn(cellClass, "text-right font-medium")}>{row.count}</td>
                <td className={cn(cellClass, "text-right text-muted-foreground")}>
                  {data.contractors.active ? `${Math.round((100 * row.count) / data.contractors.active)}%` : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function PlacementsPanel({ data }: { data: BoardPeople }) {
  return (
    <section className="min-w-0 rounded-lg border border-border bg-card p-4">
      <h3 className="mb-2 text-sm font-semibold text-foreground">Placementy według klienta</h3>
      {data.placements.by_client.length === 0 ? (
        <p className="text-[12px] text-muted-foreground">W okresie nie było placementów.</p>
      ) : (
        <table className="w-full text-[12px]">
          <thead>
            <tr className="text-[11px] text-muted-foreground">
              <th className={cn(cellClass, "text-left font-medium")}>Klient</th>
              <th className={cn(cellClass, "text-right font-medium")}>Liczba</th>
            </tr>
          </thead>
          <tbody>
            {data.placements.by_client.map((row) => (
              <tr key={row.client}>
                <td className={cellClass}>{row.client}</td>
                <td className={cn(cellClass, "text-right font-medium tabular-nums")}>{row.count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function ExitsPanel({ data }: { data: BoardPeople }) {
  const max = Math.max(1, ...data.exits.by_reason.map((r) => r.count));
  return (
    <section className="min-w-0 rounded-lg border border-border bg-card p-4">
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold text-foreground">Zejścia i ich powody</h3>
        <span className="text-[11px] text-muted-foreground">bez nazwisk · powód i opis z okna zakończenia kontraktu</span>
      </div>
      {data.exits.count === 0 ? (
        <p className="text-[12px] text-muted-foreground">W okresie nikt nie zakończył kontraktu.</p>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,260px)_minmax(0,1fr)]">
          <ul className="space-y-1.5 text-[12px]">
            {data.exits.by_reason.map((r) => (
              <li key={r.reason}>
                <div className="flex justify-between gap-2">
                  <span>{r.label}</span>
                  <span className="font-medium tabular-nums">{r.count}</span>
                </div>
                <div className="mt-0.5 h-1.5 rounded-full bg-muted">
                  <div className="h-1.5 rounded-full bg-primary" style={{ width: `${(100 * r.count) / max}%` }} />
                </div>
              </li>
            ))}
          </ul>
          <ul className="divide-y divide-border text-[12px]">
            {data.exits.items.map((item, i) => (
              <li key={`${item.ended_on}-${i}`} className="py-2">
                <div className="flex flex-wrap items-baseline gap-x-2">
                  <span className="font-medium text-foreground">{item.client}</span>
                  {item.project ? <span className="text-muted-foreground">{item.project}</span> : null}
                  <span className="ml-auto tabular-nums text-muted-foreground">{formatDate(item.ended_on)}</span>
                </div>
                <div className="mt-0.5 text-foreground">
                  {item.reason_label}
                  {item.party ? ` · zakończył: ${item.party}` : ""}
                  {item.mode ? ` (${item.mode})` : ""}
                  {item.tenure_months != null ? ` · ${item.tenure_months.toLocaleString("pl-PL")} mies. na projekcie` : ""}
                </div>
                {item.lessons ? <p className="mt-1 text-muted-foreground">„{item.lessons}”</p> : null}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
