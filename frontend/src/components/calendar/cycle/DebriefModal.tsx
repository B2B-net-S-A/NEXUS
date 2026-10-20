"use client";

import { DebriefDialog } from "@/components/calendar/cycle/DebriefDialog";
import { candidateLabel, pairContext, type PairInfo } from "@/lib/interview-cycle";
import { hasRole, useAuthStore } from "@/store/auth";

/** Lustro ``RecruitmentAssessmentWriteAccess`` (zapis debriefu). */
const DEBRIEF_WRITE_ROLES = [
  "admin",
  "head_of_recruitment",
  "delivery_lead",
  "talent_community_manager",
  "recruiter",
  "finance",
] as const;

/**
 * Debrief po telefonie do kandydata (≤30 min po rozmowie u klienta) — wejście
 * z kalendarza „Rozmowy u klienta”. Formularz żyje w `DebriefDialog`, wspólnym
 * z bramką na tablicy rekrutacji (`DebriefRequiredDialog`). Bez `eventId`
 * (zadanie „Uzupełnij pytania z rozmowy”, 20.10.2026) zapisuje pytania pary
 * i pyta, kiedy była rozmowa.
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
  const user = useAuthStore((s) => s.user);
  const readOnly = !hasRole(user, ...DEBRIEF_WRITE_ROLES);
  return (
    <DebriefDialog
      open={open}
      onOpenChange={onOpenChange}
      eventId={eventId}
      pair={pair ? { candidateId: pair.candidate_id, jobId: pair.job_id } : null}
      title={eventId == null ? "Pytania z rozmowy u klienta" : "Debrief po rozmowie u klienta"}
      description={pair ? `${candidateLabel(pair)} · ${pairContext(pair)}` : undefined}
      interviewStart={interviewStart}
      readOnly={readOnly}
    />
  );
}
