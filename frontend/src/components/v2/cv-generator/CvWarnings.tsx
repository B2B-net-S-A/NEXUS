"use client";

import { useId, useState } from "react";
import { ChevronRight } from "lucide-react";

import { classifyCvWarnings } from "@/lib/cv-generator";
import { cn } from "@/lib/utils";

import { StatusChip } from "./GeneratorParts";

export interface CvWarningsProps {
  warnings: readonly string[] | null | undefined;
  /** Klik „Pokaż w CV” — otwiera podgląd dokumentu. */
  onShowInCv?: () => void;
}

/**
 * Uwagi do CV w dwóch grupach: „Do sprawdzenia” (to, co może być w CV
 * nieprawdą albo czego brakuje) i zwinięte „Informacje” (co generator zrobił).
 */
export function CvWarnings({ warnings, onShowInCv }: CvWarningsProps) {
  const infoId = useId();
  const [infoOpen, setInfoOpen] = useState(false);
  const { review, info, infoKinds } = classifyCvWarnings(warnings);
  if (review.length === 0 && info.length === 0) {
    return <p className="text-sm text-muted-foreground">Bez uwag — generator nie zgłosił niczego do sprawdzenia.</p>;
  }
  return (
    <div className="space-y-3">
      {review.length > 0 ? (
        <section aria-label="Do sprawdzenia" className="rounded-xl border border-warning/30 bg-card">
          <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
            <h3 className="text-sm font-semibold text-foreground">Do sprawdzenia</h3>
            <StatusChip tone="warn">{review.length}</StatusChip>
            <span className="text-xs text-muted-foreground">Tylko to, co może być w CV nieprawdą</span>
          </div>
          <ul className="divide-y divide-border">
            {review.map((item) => (
              <li key={item.text} className="flex flex-wrap items-start gap-x-3 gap-y-1 px-4 py-3">
                <span className="w-full text-xs font-semibold uppercase tracking-wide text-warning-muted-foreground sm:w-36 sm:flex-none">
                  {item.kind}
                </span>
                <span className="min-w-0 flex-1 text-sm text-foreground">{item.text}</span>
                {onShowInCv ? (
                  <button type="button" onClick={onShowInCv} className="text-sm font-medium text-primary hover:underline">
                    Pokaż w CV
                  </button>
                ) : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {info.length > 0 ? (
        <div className="rounded-xl border border-border bg-card">
          <button
            type="button"
            aria-expanded={infoOpen}
            aria-controls={infoId}
            onClick={() => setInfoOpen((open) => !open)}
            className="flex w-full items-center gap-2 px-4 py-3 text-left text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <ChevronRight aria-hidden className={cn("h-4 w-4 flex-none text-muted-foreground transition-transform", infoOpen && "rotate-90")} />
            <span className="font-semibold text-foreground">{`Informacje (${info.length})`}</span>
            <span className="min-w-0 truncate text-muted-foreground">
              — {infoKinds.map((k) => `${k.kind} (${k.count})`).join(", ")}
            </span>
          </button>
          {infoOpen ? (
            <ul id={infoId} className="space-y-1.5 border-t border-border px-4 py-3 text-sm text-muted-foreground">
              {info.map((item) => (
                <li key={item.text}>{item.text}</li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
