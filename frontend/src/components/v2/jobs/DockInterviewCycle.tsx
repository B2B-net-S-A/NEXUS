"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowUpRight } from "lucide-react";

import { InterviewCycleProgress } from "@/components/calendar/cycle/InterviewCycleProgress";
import { PlanPrepDialog } from "@/components/calendar/cycle/PlanPrepDialog";
import type { KanbanItem } from "@/components/v2/pages/kanban-shared";
import type { PairInfo, StepState } from "@/lib/interview-cycle";
import { cn } from "@/lib/utils";

const OPEN_STEP: ReadonlySet<StepState> = new Set(["todo", "current", "overdue"]);

const TONE: Record<NonNullable<KanbanItem["interview_badge"]>["tone"], string> = {
  urgent: "bg-destructive/10 text-destructive",
  wait: "bg-warning-muted text-warning-muted-foreground",
  ok: "bg-success-muted text-success-muted-foreground",
  info: "bg-info-muted text-info-muted-foreground",
};

/**
 * Sekcja „Rozmowa u klienta” w doku osoby: te same 7 kroków co na ekranie
 * „Rozmowy u klienta”, jedna rzecz do zrobienia i przejście do kalendarza.
 * Do 24.09.2026 dok nie wiedział o rozmowie nic — termin, prepy, telefon
 * i debrief były wyłącznie w kalendarzu.
 */
export function DockInterviewCycle({
  badge,
  pair,
  readOnly,
  onDebrief,
  onAddClientSlots,
}: {
  badge: NonNullable<KanbanItem["interview_badge"]>;
  pair: PairInfo;
  readOnly: boolean;
  onDebrief: (eventId: number) => void;
  onAddClientSlots?: () => void;
}) {
  const [prepNo, setPrepNo] = useState<1 | 2 | null>(null);
  const steps = badge.steps ?? [];
  const state = (key: string) => steps.find((s) => s.key === key)?.state;
  const interviewDone = state("interview") === "done";
  const nextPrep: 1 | 2 | null = interviewDone
    ? null
    : OPEN_STEP.has(state("prep") ?? "done")
      ? 1
      : OPEN_STEP.has(state("prep2") ?? "done")
        ? 2
        : null;
  const debriefOpen =
    badge.interview_event_id != null &&
    (badge.kind === "call_due" || OPEN_STEP.has(state("debrief") ?? "done")) &&
    interviewDone;
  const slotsOpen = OPEN_STEP.has(state("slots") ?? "done");
  const calendarHref = `/calendar?cycle=${pair.candidate_id}-${pair.job_id}`;

  return (
    <div
      className={cn(
        "space-y-2.5 rounded-lg border p-3 text-xs",
        badge.tone === "urgent" ? "border-destructive/40" : "border-border",
      )}
      data-testid="dock-interview-cycle"
    >
      <div className="flex items-center gap-2">
        <span className="text-sm font-semibold text-foreground">Rozmowa u klienta</span>
        <Link
          href={calendarHref}
          className="ml-auto inline-flex items-center gap-0.5 font-medium text-primary hover:underline"
        >
          W kalendarzu <ArrowUpRight className="h-3 w-3" aria-hidden />
        </Link>
      </div>
      <div className={cn("rounded-md px-2 py-1 font-semibold", TONE[badge.tone])}>{badge.label}</div>
      {steps.length ? <InterviewCycleProgress steps={steps} labels /> : null}
      {!readOnly && (debriefOpen || nextPrep || (slotsOpen && onAddClientSlots)) ? (
        <div className="flex flex-wrap gap-2 pt-0.5">
          {debriefOpen ? (
            <button
              type="button"
              onClick={() => onDebrief(badge.interview_event_id as number)}
              className="h-8 rounded-md bg-primary px-3 text-xs font-semibold text-primary-foreground hover:bg-primary/90"
            >
              Zapisz debrief
            </button>
          ) : null}
          {nextPrep ? (
            <button
              type="button"
              onClick={() => setPrepNo(nextPrep)}
              className="h-8 rounded-md border border-border bg-card px-3 text-xs font-semibold hover:bg-muted"
            >
              Zaplanuj Prep {nextPrep}
            </button>
          ) : null}
          {slotsOpen && onAddClientSlots ? (
            <button
              type="button"
              onClick={onAddClientSlots}
              className="h-8 rounded-md border border-border bg-card px-3 text-xs font-semibold hover:bg-muted"
            >
              Terminy od klienta
            </button>
          ) : null}
        </div>
      ) : null}
      {prepNo ? (
        <PlanPrepDialog open onOpenChange={(o) => !o && setPrepNo(null)} pair={pair} prepNo={prepNo} />
      ) : null}
    </div>
  );
}
