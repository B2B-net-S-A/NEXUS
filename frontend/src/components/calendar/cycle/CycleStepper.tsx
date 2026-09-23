"use client";

import { Check } from "lucide-react";

import {
  STEP_TITLES,
  formatDayLabel,
  formatTime,
  prepQualityTone,
  stepTone,
  type CycleStep,
} from "@/lib/interview-cycle";
import { cn } from "@/lib/utils";

const STATE_TEXT: Record<CycleStep["state"], string> = {
  done: "zrobione",
  current: "teraz",
  scheduled: "zaplanowane",
  waiting: "czeka",
  todo: "do zrobienia",
  overdue: "po terminie",
  skipped: "pominięte",
};

const DOT: Record<ReturnType<typeof stepTone>, string> = {
  done: "bg-success text-success-foreground",
  current: "bg-primary text-primary-foreground",
  warn: "bg-warning text-warning-foreground",
  danger: "bg-destructive text-destructive-foreground",
  muted: "bg-card border-2 border-border text-muted-foreground",
};

const TITLE: Record<ReturnType<typeof stepTone>, string> = {
  done: "text-foreground",
  current: "text-primary font-semibold",
  warn: "text-warning-muted-foreground font-semibold",
  danger: "text-destructive font-semibold",
  muted: "text-muted-foreground",
};

const QUALITY_TEXT: Record<ReturnType<typeof prepQualityTone>, string> = {
  done: "text-success-muted-foreground font-semibold",
  warn: "text-warning-muted-foreground font-semibold",
  danger: "text-destructive font-semibold",
  muted: "",
};

/** Siedem kroków cyklu pary w pionie. Przycisk akcji dostaje tylko krok bieżący. */
export function CycleStepper({
  steps,
  action,
  onPrepReview,
}: {
  steps: CycleStep[];
  /** Akcja dla kroku bieżącego (np. „Zapisz debrief”). */
  action?: { stepKey: CycleStep["key"]; label: string; onClick: () => void } | null;
  /** 0362: odbyty prep z NEXUSA (Teams) — otwiera ocenę prepu. */
  onPrepReview?: (eventId: number) => void;
}) {
  return (
    <ol className="flex flex-col" aria-label="Kroki rozmowy u klienta">
      {steps.map((step, i) => {
        const tone = stepTone(step.state);
        const last = i === steps.length - 1;
        const when = step.at
          ? `${formatDayLabel(step.at)} ${formatTime(step.at)}`
          : null;
        return (
          <li key={step.key} className="flex gap-3 min-h-[44px]" data-step={step.key} data-state={step.state}>
            <div className="flex flex-col items-center w-6 shrink-0">
              <span
                className={cn(
                  "flex h-6 w-6 items-center justify-center rounded-full text-[11px] font-bold",
                  DOT[tone],
                  step.state === "skipped" && "opacity-50",
                )}
                aria-hidden
              >
                {step.state === "done" ? <Check className="h-3.5 w-3.5" /> : i + 1}
              </span>
              {!last ? <span className="w-0.5 flex-1 bg-border my-0.5" aria-hidden /> : null}
            </div>
            <div className="flex flex-1 items-start justify-between gap-2 pb-2.5">
              <div className="min-w-0">
                <div className={cn("text-sm", TITLE[tone], step.state === "skipped" && "line-through")}>
                  {STEP_TITLES[step.key]}
                </div>
                <div className="text-xs text-muted-foreground">
                  {[
                    STATE_TEXT[step.state],
                    // Telefon: `at` to KONIEC okna, więc „do 13:30”, nie sama godzina.
                    when && step.key === "call" && step.state !== "done" ? `do ${when}` : when,
                    !step.quality && step.meta && step.meta !== STATE_TEXT[step.state]
                      ? step.meta
                      : null,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                  {step.quality && step.meta ? (
                    <span className={cn("block", QUALITY_TEXT[prepQualityTone(step.quality)])}>
                      {step.meta}
                    </span>
                  ) : null}
                </div>
                {step.quality && step.event_id != null && onPrepReview ? (
                  <button
                    type="button"
                    onClick={() => onPrepReview(step.event_id as number)}
                    className="mt-0.5 text-xs font-semibold text-primary hover:underline"
                  >
                    Zobacz ocenę i transkrypt
                  </button>
                ) : null}
              </div>
              {action && action.stepKey === step.key ? (
                <button
                  type="button"
                  onClick={action.onClick}
                  className="shrink-0 h-8 px-3 rounded-md bg-primary/10 text-primary text-xs font-semibold hover:bg-primary/15"
                >
                  {action.label}
                </button>
              ) : null}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
