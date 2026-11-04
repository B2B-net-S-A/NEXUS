"use client";

import Link from "next/link";
import { useState } from "react";
import { useSearchParams } from "next/navigation";

import { cn } from "@/lib/utils";
import type {
  InFlightResponse,
  InsightsPeriodParams,
  RecruitmentFunnelResponse,
} from "@/lib/insights-api";
import { reportHref } from "@/lib/insights-reports";
import { addDays, metricFromSlug, WHO_COUNTS_METRICS, type WhoCountsMetric } from "@/lib/kpi-who-counts";
import { useUrlWriter } from "@/lib/url-selection";
import {
  TeamListReconcileLine,
  TeamWhoCountsPanel,
} from "@/components/insights/sections/WhoCountsPanel";
import { comparableSteps, teamFunnelSteps } from "@/lib/insights-team-funnel";
import { weakestStepSentence } from "@/lib/insights-views";

import { Panel, Takeaway } from "../ViewKit";

const DELTA_CLASS = {
  good: "text-success-muted-foreground",
  bad: "text-warning-muted-foreground",
  neutral: "text-muted-foreground",
} as const;

/** Etap lejka → lista „Kto się liczy” (ta sama trasa co komórki tabeli Ludzie). */
const STAGE_METRIC: Record<string, WhoCountsMetric> = {
  verified: "verification",
  cv_sent: "recommendation",
  client_interview: "interview",
  acceptance: "acceptance",
  hired: "placement",
};
const FUNNEL_METRICS = Object.values(STAGE_METRIC);
export const TEAM_LIST_SLUG = "zespol";

function dayMonth(iso: string): string {
  return `${Number(iso.slice(8, 10))}.${iso.slice(5, 7)}`;
}

/**
 * Jeden lejek zamiast czterech kafli i słupków z tymi samymi liczbami
 * (22.10.2026): pięć etapów w okresie, a pod nimi „stoi dziś”.
 */
export function TeamFunnelPanel({
  funnel,
  previous,
  previousLabel,
  inFlight,
  period,
  canOpenList,
}: {
  /** Lista osób za liczbą — role z wglądem w zespół (lustro `_TEAM_DETAIL_ROLES`). */
  canOpenList: boolean;
  funnel: RecruitmentFunnelResponse;
  previous: RecruitmentFunnelResponse | undefined;
  previousLabel: string | undefined;
  inFlight: InFlightResponse | undefined;
  period: InsightsPeriodParams;
}) {
  const steps = teamFunnelSteps(funnel, previous, previousLabel, inFlight);
  const sentence = weakestStepSentence(comparableSteps(steps));
  // `?kto=…&osoba=zespol` — w adresie, więc „Wstecz” zamyka listę.
  const searchParams = useSearchParams();
  const { pushUrl, replaceUrl } = useUrlWriter();
  const openMetric =
    searchParams.get("osoba") === TEAM_LIST_SLUG ? metricFromSlug(searchParams.get("kto")) : null;
  const writeList = (metric: WhoCountsMetric | null, mode: "push" | "replace" = "push") => {
    const params = new URLSearchParams(searchParams.toString());
    if (metric === null) {
      params.delete("kto");
      params.delete("osoba");
    } else {
      params.set("kto", WHO_COUNTS_METRICS[metric].slug);
      params.set("osoba", TEAM_LIST_SLUG);
    }
    const href = `${window.location.pathname}?${params.toString()}`;
    if (mode === "push") pushUrl(href);
    else replaceUrl(href);
  };
  // „Pokaż” przy parach bez osoby z zasługą — widok w tej samej liście, nie w adresie.
  const [withoutCredit, setWithoutCredit] = useState(false);
  const range = {
    start: funnel.period.start.slice(0, 10),
    end: addDays(funnel.period.end.slice(0, 10), -1),
  };
  const clicked = openMetric
    ? (steps.find((s) => STAGE_METRIC[s.stage] === openMetric)?.count ?? null)
    : null;
  return (
    <Panel title="Lejek: w okresie i stan na dziś" hint="pierwsze wejście pary (kandydat, rekrutacja) na etap">
      <div className="overflow-x-auto">
        <div className="grid min-w-[44rem] grid-cols-[7rem_repeat(5,minmax(0,1fr))] gap-2">
          <span />
          {steps.map((s) => (
            <span
              key={s.stage}
              className="text-center text-xs font-semibold uppercase tracking-wide text-muted-foreground"
            >
              {s.label}
            </span>
          ))}
          <span className="self-center text-sm font-semibold text-foreground">W okresie</span>
          {steps.map((s) => (
            <div
              key={s.stage}
              className={cn(
                "flex flex-col items-center gap-1 rounded-lg bg-muted/50 p-3 text-center",
                openMetric === STAGE_METRIC[s.stage] && "bg-primary/10 ring-2 ring-primary/40",
              )}
            >
              {canOpenList && s.count > 0 ? (
                <button
                  type="button"
                  onClick={() => {
                    setWithoutCredit(false);
                    writeList(STAGE_METRIC[s.stage]);
                  }}
                  aria-pressed={openMetric === STAGE_METRIC[s.stage]}
                  aria-label={`${s.label}: ${s.count}. Pokaż osoby`}
                  className="rounded-sm text-2xl font-bold tabular-nums text-foreground underline decoration-dotted decoration-2 underline-offset-[6px] hover:text-primary focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
                >
                  {s.count.toLocaleString("pl-PL")}
                </button>
              ) : (
                <span className="text-2xl font-bold tabular-nums text-foreground">
                  {s.count.toLocaleString("pl-PL")}
                </span>
              )}
              {s.conversion !== null ? (
                <span className="rounded-full bg-primary/10 px-2 py-0.5 text-xs font-semibold text-primary">
                  {s.conversion}%
                </span>
              ) : null}
              {s.countedFrom ? (
                <span className="text-xs text-muted-foreground">od {dayMonth(s.countedFrom)}</span>
              ) : s.delta ? (
                <span className={cn("text-xs", DELTA_CLASS[s.delta.tone])}>{s.delta.text}</span>
              ) : null}
            </div>
          ))}
          {inFlight ? (
            <>
              <span className="self-center text-sm font-semibold text-foreground">Stoi dziś</span>
              {steps.map((s) => (
                <div
                  key={s.stage}
                  className="flex flex-col items-center gap-0.5 rounded-lg border border-dashed border-border p-2.5 text-center"
                >
                  <span className="text-lg font-bold tabular-nums text-foreground">
                    {s.today?.value ?? "—"}
                  </span>
                  {s.today?.note ? (
                    <span
                      className={cn(
                        "text-xs",
                        /dłużej/.test(s.today.note)
                          ? "font-semibold text-warning-muted-foreground"
                          : "text-muted-foreground",
                      )}
                    >
                      {s.today.note}
                    </span>
                  ) : null}
                </div>
              ))}
            </>
          ) : null}
        </div>
      </div>
      {canOpenList && openMetric ? (
        <TeamWhoCountsPanel
          subject={withoutCredit ? { kind: "unattributed" } : { kind: "team" }}
          metric={openMetric}
          metrics={FUNNEL_METRICS}
          range={range}
          notice={
            withoutCredit ? (
              <button
                type="button"
                onClick={() => setWithoutCredit(false)}
                className="w-fit text-xs font-semibold text-primary hover:underline"
              >
                ← Cały zespół
              </button>
            ) : (
              <TeamListReconcileLine
                metric={openMetric}
                range={range}
                clicked={clicked}
                onShowUnattributed={() => setWithoutCredit(true)}
              />
            )
          }
          onMetricChange={(metric) => {
            setWithoutCredit(false);
            writeList(metric, "replace");
          }}
          onClose={() => {
            setWithoutCredit(false);
            writeList(null);
          }}
        />
      ) : canOpenList ? (
        <p className="text-xs text-muted-foreground">Kliknij liczbę, żeby zobaczyć osoby za nią.</p>
      ) : null}
      {sentence ? <Takeaway>{sentence}</Takeaway> : null}
      <Link
        href={reportHref("lejek-etapy", period)}
        className="w-fit text-sm font-semibold text-primary hover:underline"
      >
        Wszystkie etapy i odznaki Tablicy →
      </Link>
    </Panel>
  );
}
