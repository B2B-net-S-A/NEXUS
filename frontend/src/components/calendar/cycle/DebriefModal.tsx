"use client";

import { DebriefDialog } from "@/components/calendar/cycle/DebriefDialog";
import { candidateLabel, pairContext, type PairInfo } from "@/lib/interview-cycle";

/**
 * Debrief po telefonie do kandydata (≤30 min po rozmowie u klienta) — wejście
 * z kalendarza „Rozmowy u klienta”. Formularz żyje w `DebriefDialog`, wspólnym
 * z bramką na tablicy rekrutacji (`DebriefRequiredDialog`).
 */
export function DebriefModal({
  open,
  onOpenChange,
  eventId,
  pair,
  interviewStart,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  eventId: number | null;
  pair: PairInfo | null;
  /** Początek rozmowy — debrief jest dostępny dopiero od niego. */
  interviewStart?: string;
}) {
  return (
    <DebriefDialog
      open={open}
      onOpenChange={onOpenChange}
      eventId={eventId}
      title="Debrief po rozmowie u klienta"
      description={pair ? `${candidateLabel(pair)} · ${pairContext(pair)}` : undefined}
      interviewStart={interviewStart}
    />
  );
}
