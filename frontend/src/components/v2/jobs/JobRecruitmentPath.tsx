"use client";

/**
 * „Ścieżka rekrutacji" + „Najbliższy krok" w nagłówku rekrutacji
 * (24.09.2026). Czysto prezentacyjny — kroki i zdanie liczy
 * `lib/job-recruitment-path.ts`, strona podaje, co zrobić po kliknięciu.
 */

import { ArrowRight, Check, ChevronRight } from "lucide-react";

import { Button } from "@/components/ui/button";
import type {
  NearestStep,
  PathStep,
  PathStepKey,
  PathStepState,
} from "@/lib/job-recruitment-path";
import { cn } from "@/lib/utils";

const DOT_CLASS: Record<PathStepState, string> = {
  done: "bg-success text-success-foreground",
  active: "bg-primary text-primary-foreground",
  missing: "bg-warning text-warning-foreground",
  todo: "border border-border bg-background text-muted-foreground",
};

const STATE_LABEL: Record<PathStepState, string> = {
  done: "gotowe",
  active: "trwa",
  missing: "brak",
  todo: "przed nami",
};

function StepDot({ state }: { state: PathStepState }) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-[10px] font-bold leading-none",
        DOT_CLASS[state],
      )}
    >
      {state === "done" ? (
        <Check className="h-2.5 w-2.5" strokeWidth={3} />
      ) : state === "missing" ? (
        "!"
      ) : state === "active" ? (
        <span className="h-1.5 w-1.5 rounded-full bg-current" />
      ) : null}
    </span>
  );
}

export interface JobRecruitmentPathProps {
  steps: PathStep[];
  nearest: NearestStep | null;
  onStepClick: (key: PathStepKey) => void;
  onNearestClick: (step: NearestStep) => void;
}

export function JobRecruitmentPath({
  steps,
  nearest,
  onStepClick,
  onNearestClick,
}: JobRecruitmentPathProps) {
  return (
    <div
      className="flex min-w-0 flex-wrap items-stretch gap-x-3 gap-y-2 border-t border-border px-3 py-2"
      data-testid="job-recruitment-path"
    >
      <ol
        aria-label="Ścieżka rekrutacji"
        className="flex min-w-0 flex-1 flex-wrap items-stretch gap-y-1"
      >
        {steps.map((step, index) => (
          <li key={step.key} className="flex min-w-0 items-center">
            {index > 0 ? (
              <ChevronRight
                className="mx-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground/60"
                aria-hidden="true"
              />
            ) : null}
            <button
              type="button"
              onClick={() => onStepClick(step.key)}
              data-testid={`path-step-${step.key}`}
              data-state={step.state}
              aria-label={`${step.label}: ${STATE_LABEL[step.state]} — ${step.detail}`}
              className={cn(
                "flex min-w-0 items-start gap-1.5 rounded-md px-2 py-1 text-left transition-colors hover:bg-muted",
                "focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring",
              )}
            >
              <span className="mt-0.5">
                <StepDot state={step.state} />
              </span>
              <span className="min-w-0 leading-tight">
                <span className="block text-xs font-semibold text-foreground">
                  {step.label}
                </span>
                <span
                  className={cn(
                    "block max-w-[16rem] truncate text-[11px]",
                    step.state === "missing"
                      ? "font-medium text-warning"
                      : "text-muted-foreground",
                  )}
                >
                  {step.detail}
                </span>
              </span>
            </button>
          </li>
        ))}
      </ol>

      {nearest ? (
        <div
          className="flex min-w-0 items-center gap-2 rounded-md border border-primary/30 bg-primary/5 px-2.5 py-1"
          data-testid="job-nearest-step"
          data-rule={nearest.rule}
        >
          <span className="min-w-0 leading-tight">
            <span className="block text-[10px] font-semibold uppercase tracking-eyebrow text-primary">
              Najbliższy krok
            </span>
            <span className="block truncate text-xs font-medium text-foreground">
              {nearest.sentence}
            </span>
          </span>
          <Button
            type="button"
            size="sm"
            onClick={() => onNearestClick(nearest)}
            className="shrink-0"
          >
            {nearest.cta}
            <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
          </Button>
        </div>
      ) : null}
    </div>
  );
}
