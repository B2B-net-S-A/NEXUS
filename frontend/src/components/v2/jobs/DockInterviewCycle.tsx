"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowUpRight } from "lucide-react";

import { InterviewCycleProgress } from "@/components/calendar/cycle/InterviewCycleProgress";
import { PlanPrepDialog } from "@/components/calendar/cycle/PlanPrepDialog";
import { PrepReviewDialog } from "@/components/calendar/cycle/PrepReviewDialog";
import { SlotDecisionDialog } from "@/components/calendar/cycle/SlotDialogs";
import { ReschedulePrepDialog } from "@/components/calendar/cycle/ReschedulePrepDialog";
import type { KanbanItem } from "@/components/v2/pages/kanban-shared";
import type { PairInfo, StepState } from "@/lib/interview-cycle";
import { scheduledInterviewFromSteps } from "@/lib/prep-timing";
import { cn } from "@/lib/utils";

const OPEN_STEP: ReadonlySet<StepState> = new Set(["todo", "current", "overdue"]);
// Prep „po terminie” to prep zaplanowany po rozmowie u klienta — spotkanie już
// istnieje, więc nie jest krokiem do zaplanowania (od tego jest „Przełóż”).
const PREP_TO_PLAN: ReadonlySet<StepState> = new Set(["todo", "current"]);

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
  // PR 6 (04.10.2026): wybór i potwierdzenie terminu oraz ocena prepu w panelu
  // osoby — do tej pory wyłącznie w kalendarzu „Rozmowy u klienta”.
  const [slotMode, setSlotMode] = useState<"pick" | "confirm" | null>(null);
  const [reviewPrepId, setReviewPrepId] = useState<number | null>(null);
  const slotRequest = badge.slot_request ?? null;
  const canPickSlot = slotRequest?.status === "awaiting_recruiter";
  // Termin potwierdza osoba z prawem do terminów od klienta (ta sama, która je
  // dodaje) — przycisk „Terminy od klienta” jest tym samym sygnałem.
  const canConfirmSlot = slotRequest?.status === "awaiting_dl" && Boolean(onAddClientSlots);
  // Prep z oceną (także „niedostępna”) — okno mówi, co z niej wynika.
  const reviewedPreps = (badge.preps ?? []).filter((p) => p.review_status != null);
  const [rescheduling, setRescheduling] = useState(false);
  const steps = badge.steps ?? [];
  const state = (key: string) => steps.find((s) => s.key === key)?.state;
  const interviewDone = state("interview") === "done";
  const nextPrep: 1 | 2 | null = interviewDone
    ? null
    : PREP_TO_PLAN.has(state("prep") ?? "done")
      ? 1
      : PREP_TO_PLAN.has(state("prep2") ?? "done")
        ? 2
        : null;
  const debriefOpen =
    badge.interview_event_id != null &&
    (badge.kind === "call_due" || OPEN_STEP.has(state("debrief") ?? "done")) &&
    interviewDone;
  const slotsOpen = OPEN_STEP.has(state("slots") ?? "done");
  const calendarHref = `/calendar?cycle=${pair.candidate_id}-${pair.job_id}`;
  // Prep po rozmowie u klienta: krok jest „po terminie”, ale spotkanie już
  // istnieje — przekładamy TO spotkanie (nowy termin), zamiast zakładać drugie.
  const latePrepId = badge.late_prep_event_id ?? null;
  const latePrepNo: 1 | 2 = state("prep") !== "overdue" && state("prep2") === "overdue" ? 2 : 1;
  // Termin rozmowy bywa dopiero proponowany — okno prepu liczy względem niego.
  const prepInterview =
    scheduledInterviewFromSteps(steps) ??
    (badge.tentative_interview_at
      ? { start: badge.tentative_interview_at, tentative: true }
      : null);

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
      {!readOnly &&
      (debriefOpen ||
        nextPrep ||
        latePrepId ||
        canPickSlot ||
        canConfirmSlot ||
        (slotsOpen && onAddClientSlots && !slotRequest)) ? (
        <div className="flex flex-wrap gap-2 pt-0.5">
          {canPickSlot ? (
            <button
              type="button"
              onClick={() => setSlotMode("pick")}
              className="h-8 rounded-md bg-primary px-3 text-xs font-semibold text-primary-foreground hover:bg-primary/90"
            >
              Wybierz termin z kandydatem
            </button>
          ) : null}
          {canConfirmSlot ? (
            <button
              type="button"
              onClick={() => setSlotMode("confirm")}
              className="h-8 rounded-md bg-primary px-3 text-xs font-semibold text-primary-foreground hover:bg-primary/90"
            >
              Potwierdź termin
            </button>
          ) : null}
          {debriefOpen ? (
            <button
              type="button"
              onClick={() => onDebrief(badge.interview_event_id as number)}
              className="h-8 rounded-md bg-primary px-3 text-xs font-semibold text-primary-foreground hover:bg-primary/90"
            >
              Zapisz debrief
            </button>
          ) : null}
          {latePrepId ? (
            <button
              type="button"
              onClick={() => setRescheduling(true)}
              className="inline-flex h-8 items-center rounded-md border border-destructive/40 bg-card px-3 text-xs font-semibold text-destructive hover:bg-destructive/10"
            >
              Przełóż prep (wypada po rozmowie)
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
          {slotsOpen && onAddClientSlots && !slotRequest ? (
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
      {reviewedPreps.length > 0 ? (
        <div className="flex flex-wrap gap-x-3 gap-y-1">
          {reviewedPreps.map((p) => (
            <button
              key={p.id}
              type="button"
              onClick={() => setReviewPrepId(p.id)}
              className="font-medium text-primary hover:underline"
            >
              Ocena prepu{p.prep_no ? ` ${p.prep_no}` : ""}
            </button>
          ))}
        </div>
      ) : null}
      {slotMode && slotRequest ? (
        <SlotDecisionDialog
          open
          onOpenChange={(o) => !o && setSlotMode(null)}
          mode={slotMode}
          pair={pair}
          request={slotRequest}
        />
      ) : null}
      {reviewPrepId != null ? (
        <PrepReviewDialog
          open
          onOpenChange={(o) => !o && setReviewPrepId(null)}
          eventId={reviewPrepId}
          pair={pair}
        />
      ) : null}
      {rescheduling && latePrepId ? (
        <ReschedulePrepDialog
          open
          onOpenChange={(o) => !o && setRescheduling(false)}
          eventId={latePrepId}
          pair={pair}
          prepNo={latePrepNo}
          interview={prepInterview}
        />
      ) : null}
      {prepNo ? (
        <PlanPrepDialog
          open
          onOpenChange={(o) => !o && setPrepNo(null)}
          pair={pair}
          prepNo={prepNo}
          interview={prepInterview}
        />
      ) : null}
    </div>
  );
}
