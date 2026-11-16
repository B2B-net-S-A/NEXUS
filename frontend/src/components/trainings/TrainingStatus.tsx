"use client";

import { Check } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import type { TrainingStatus } from "@/lib/api/trainings";
import { cn } from "@/lib/utils";

import { STATUS_LABELS, STATUS_TONES, type StatusTone, type StepState } from "./training-model";

export function ToneBadge({ tone, children }: { tone: StatusTone; children: React.ReactNode }) {
  return <Badge variant={tone}>{children}</Badge>;
}

export function TrainingStatusBadge({
  status,
  label,
}: {
  status: TrainingStatus;
  label?: string;
}) {
  return <ToneBadge tone={STATUS_TONES[status]}>{label || STATUS_LABELS[status]}</ToneBadge>;
}

/** Pasek kroków karty: zrobione z ptaszkiem, bieżący wyróżniony, reszta szara. */
export function TrainingSteps({ steps }: { steps: StepState }) {
  return (
    <ol aria-label="Etapy szkolenia" className="flex flex-wrap items-center gap-1.5 text-xs">
      {steps.labels.map((label, index) => {
        const done = steps.complete || (!steps.cancelled && index < steps.current);
        const current = !steps.complete && !steps.cancelled && index === steps.current;
        return (
          <li
            key={label}
            aria-current={current ? "step" : undefined}
            data-state={done ? "done" : current ? "current" : "todo"}
            className={cn(
              "inline-flex items-center gap-1 rounded-full border px-2.5 py-1",
              done && "border-success/30 bg-success-muted text-success-muted-foreground",
              current && "border-primary bg-primary/10 font-semibold text-primary",
              !done && !current && "border-border text-muted-foreground",
            )}
          >
            {done ? <Check className="h-3 w-3" aria-hidden /> : null}
            {label}
          </li>
        );
      })}
    </ol>
  );
}
