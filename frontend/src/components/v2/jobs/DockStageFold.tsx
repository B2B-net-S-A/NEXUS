"use client";

/**
 * Zwinięta linia „Warunki i następny etap” pod paskiem zakładek rozwiniętego
 * panelu osoby (09.10.2026).
 *
 * Do tej daty fakty o osobie, „Nie odebrał” i ramka „Następny etap” stały
 * w głowie panelu i wracały do niej w każdej zakładce poza „Screeningiem”.
 * Głowa się nie przewija, więc pasek zakładek zjeżdżał na dół, a na treść
 * zakładki zostawały dwie linijki. Tu te same bloki stoją POD paskiem,
 * domyślnie zwinięte do jednej linii ze skrótem („Zweryfikowany · brakuje
 * 4 z 4”), a treść montuje się dopiero po rozwinięciu.
 */

import type { ReactNode } from "react";
import { ChevronDown } from "lucide-react";

import { nextStageHeading, useNextStageRequirements } from "@/components/v2/jobs/DockNextStage";
import type { KanbanColumn } from "@/components/v2/pages/kanban-shared";
import { summarizeRequirements } from "@/lib/api/moveRequirements";
import { cn } from "@/lib/utils";

export interface DockStageFoldProps {
  title: string;
  /** Skrót obok tytułu, widoczny tylko w stanie zwiniętym. */
  summary?: ReactNode;
  open: boolean;
  onToggle: () => void;
  children: ReactNode;
}

export function DockStageFold({ title, summary = null, open, onToggle, children }: DockStageFoldProps) {
  return (
    <section className="rounded-lg border border-border" data-testid="dock-stage-fold">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <span className="shrink-0 text-xs font-semibold text-foreground">{title}</span>
        <span className="min-w-0 flex-1 truncate text-[11px] text-muted-foreground">
          {open ? null : summary}
        </span>
        <ChevronDown
          className={cn("h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform", open && "rotate-180")}
          aria-hidden="true"
        />
      </button>
      {open ? <div className="space-y-2.5 px-3 pb-3">{children}</div> : null}
    </section>
  );
}

/** Skrót zwiniętej linii: nazwa następnego etapu i liczba braków z serwera. */
export function NextStageSummary({
  candidateId,
  jobId,
  target,
  refreshToken,
}: {
  candidateId: number;
  jobId: number;
  target: KanbanColumn;
  refreshToken?: unknown;
}) {
  const query = useNextStageRequirements({ candidateId, jobId, target, refreshToken });
  const data = query.data ?? null;
  const heading = nextStageHeading(data, target.name ?? target.stage);
  const summary = data ? summarizeRequirements(data.items ?? []) : null;
  return (
    <span data-testid="dock-stage-fold-summary">
      {heading.label}
      {summary && summary.total > 0
        ? summary.missing > 0
          ? ` · brakuje ${summary.missing} z ${summary.total}`
          : ` · gotowe ${summary.total} z ${summary.total}`
        : ""}
    </span>
  );
}
