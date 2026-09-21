"use client";

/** „Co sprawdziłem” — kroki narzędzi w trwającej turze. */

import { AlertCircle, Check, Loader2 } from "lucide-react";
import type { JarvisStep } from "@/lib/jarvis/types";

export function JarvisStepTrace({ steps }: { steps: JarvisStep[] }) {
  if (steps.length === 0) return null;
  return (
    <ul className="space-y-1 text-xs text-muted-foreground" aria-label="Kroki Jarvisa">
      {steps.map((step, index) => (
        <li key={`${step.tool}-${index}`} className="flex items-center gap-1.5">
          {step.status === "running" ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
          ) : step.status === "done" ? (
            <Check className="h-3.5 w-3.5 text-success" aria-hidden />
          ) : (
            <AlertCircle className="h-3.5 w-3.5 text-destructive" aria-hidden />
          )}
          <span>{step.label}</span>
        </li>
      ))}
    </ul>
  );
}
