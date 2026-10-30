"use client";

import { DebriefModal } from "@/components/calendar/cycle/DebriefModal";
import { PlanPrepDialog } from "@/components/calendar/cycle/PlanPrepDialog";
import { PrecallDoneDialog } from "@/components/calendar/cycle/Prep2Skip";
import { PrepReviewDialog } from "@/components/calendar/cycle/PrepReviewDialog";
import { ReschedulePrepDialog } from "@/components/calendar/cycle/ReschedulePrepDialog";
import { SlotDecisionDialog, SlotRequestDialog } from "@/components/calendar/cycle/SlotDialogs";
import {
  interviewStartFor,
  type CycleAction,
  type CycleOverview,
} from "@/lib/interview-cycle";
import { prepInterviewForPair } from "@/lib/prep-timing";

/**
 * Okna akcji cyklu rozmowy otwierane z okienka „Rozmowy” w górnym pasku — te
 * same co na ekranie „Rozmowy u klienta” (`CalendarCycleScreen`). Osobny
 * moduł ładowany leniwie: pasek stoi na każdej stronie, a okna są potrzebne
 * dopiero po kliknięciu akcji.
 */
export default function InterviewActionDialogs({
  action,
  overview,
  onClose,
}: {
  action: CycleAction;
  overview: CycleOverview | undefined;
  onClose: () => void;
}) {
  const onOpenChange = (open: boolean) => {
    if (!open) onClose();
  };
  switch (action.type) {
    case "debrief":
      return (
        <DebriefModal
          open
          onOpenChange={onOpenChange}
          eventId={action.eventId}
          pair={action.pair}
          interviewStart={interviewStartFor(overview, action.eventId)}
        />
      );
    case "pick":
    case "confirm":
    case "reply":
      return (
        <SlotDecisionDialog
          open
          onOpenChange={onOpenChange}
          mode={action.type}
          pair={action.pair}
          request={action.request}
        />
      );
    case "plan_prep":
      return (
        <PlanPrepDialog
          open
          onOpenChange={onOpenChange}
          pair={action.pair}
          prepNo={action.second ? 2 : 1}
          interview={prepInterviewForPair(overview, action.pair)}
        />
      );
    case "reschedule_prep":
      return (
        <ReschedulePrepDialog
          open
          onOpenChange={onOpenChange}
          eventId={action.eventId}
          pair={action.pair}
          prepNo={action.prepNo}
          mode={action.mode}
          interview={prepInterviewForPair(overview, action.pair)}
        />
      );
    case "prep_review":
      return (
        <PrepReviewDialog
          open
          onOpenChange={onOpenChange}
          eventId={action.eventId}
          pair={action.pair}
        />
      );
    case "add_slots":
      return <SlotRequestDialog open onOpenChange={onOpenChange} pair={action.pair} request={action.request} />;
    case "precall_done":
      return (
        <PrecallDoneDialog
          open
          onOpenChange={onOpenChange}
          pair={action.pair}
          skip={action.skip}
        />
      );
    default:
      return null;
  }
}
