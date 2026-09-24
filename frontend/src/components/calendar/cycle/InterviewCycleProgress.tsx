"use client";

import { STEP_ORDER, STEP_TITLES, type StepKey, type StepState } from "@/lib/interview-cycle";
import { cn } from "@/lib/utils";

/** Kolor fazy kroku: niebieski = umawianie, fiolet = prep, bursztyn = rozmowa, zielony = telefon/debrief. */
const PHASE: Record<StepKey, { solid: string; soft: string }> = {
  slots: { solid: "bg-info", soft: "bg-info/40" },
  choice: { solid: "bg-info", soft: "bg-info/40" },
  prep: { solid: "bg-primary", soft: "bg-primary/40" },
  prep2: { solid: "bg-primary", soft: "bg-primary/40" },
  interview: { solid: "bg-warning", soft: "bg-warning/40" },
  call: { solid: "bg-success", soft: "bg-success/40" },
  debrief: { solid: "bg-success", soft: "bg-success/40" },
};

const STATE_TEXT: Record<StepState, string> = {
  done: "zrobione",
  current: "teraz",
  scheduled: "zaplanowane",
  waiting: "czeka",
  todo: "przed nami",
  overdue: "po terminie",
  skipped: "pominięte",
};

function barClass(key: StepKey, state: StepState): string {
  switch (state) {
    case "done":
      return PHASE[key].solid;
    case "current":
    case "scheduled":
    case "waiting":
      return PHASE[key].soft;
    case "overdue":
      return "bg-destructive";
    case "skipped":
      return "bg-muted-foreground/25";
    default:
      return "bg-border";
  }
}

/**
 * Siedem kresek cyklu rozmowy u klienta (terminy → debrief) — na karcie
 * Tablicy rekrutacji i w doku osoby. Te same kroki co na ekranie
 * „Rozmowy u klienta”, liczone przez serwer.
 */
export function InterviewCycleProgress({
  steps,
  labels = false,
  className,
}: {
  steps: ReadonlyArray<{ key: StepKey; state: StepState }>;
  /** Podpisy pod kreskami (dok); na karcie same kreski. */
  labels?: boolean;
  className?: string;
}) {
  const byKey = new Map(steps.map((s) => [s.key, s.state]));
  const done = steps.filter((s) => s.state === "done").length;
  const summary = STEP_ORDER.map(
    (k) => `${STEP_TITLES[k]}: ${STATE_TEXT[byKey.get(k) ?? "todo"]}`,
  ).join(" · ");
  return (
    <div
      role="img"
      aria-label={`Rozmowa u klienta — ${done} z 7 kroków zrobione. ${summary}`}
      title={summary}
      className={cn("grid grid-cols-7 gap-0.5", className)}
      data-testid="interview-cycle-progress"
    >
      {STEP_ORDER.map((key) => {
        const state = byKey.get(key) ?? "todo";
        return (
          <div key={key} className="flex min-w-0 flex-col gap-1">
            <span className={cn("h-1.5 rounded-full", barClass(key, state))} data-state={state} />
            {labels ? (
              <span
                className={cn(
                  "truncate text-center text-[10px] leading-tight",
                  state === "overdue" ? "font-semibold text-destructive" : "text-muted-foreground",
                )}
              >
                {SHORT[key]}
              </span>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

const SHORT: Record<StepKey, string> = {
  slots: "Terminy",
  choice: "Wybór",
  prep: "Prep",
  prep2: "Prep 2",
  interview: "Rozmowa",
  call: "Telefon",
  debrief: "Debrief",
};
