"use client";

import Link from "next/link";

import { cn } from "@/lib/utils";
import type {
  InFlightResponse,
  InsightsPeriodParams,
  RecruitmentFunnelResponse,
} from "@/lib/insights-api";
import { reportHref } from "@/lib/insights-reports";
import { comparableSteps, teamFunnelSteps } from "@/lib/insights-team-funnel";
import { weakestStepSentence } from "@/lib/insights-views";

import { Panel, Takeaway } from "../ViewKit";

const DELTA_CLASS = {
  good: "text-success-muted-foreground",
  bad: "text-warning-muted-foreground",
  neutral: "text-muted-foreground",
} as const;

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
}: {
  funnel: RecruitmentFunnelResponse;
  previous: RecruitmentFunnelResponse | undefined;
  previousLabel: string | undefined;
  inFlight: InFlightResponse | undefined;
  period: InsightsPeriodParams;
}) {
  const steps = teamFunnelSteps(funnel, previous, previousLabel, inFlight);
  const sentence = weakestStepSentence(comparableSteps(steps));
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
            <div key={s.stage} className="flex flex-col items-center gap-1 rounded-lg bg-muted/50 p-3 text-center">
              <span className="text-2xl font-bold tabular-nums text-foreground">
                {s.count.toLocaleString("pl-PL")}
              </span>
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
