"use client";

import { MessageSquare } from "lucide-react";

import {
  InterviewFeedbackSummary,
  useInterviewFeedbackByCandidate,
} from "@/components/feedback/InterviewFeedbackSummary";
import type { InterviewFeedbackRow } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";

/**
 * „Feedback po rozmowach" na profilu kandydata (zakładka Rekrutacje), tylko
 * do odczytu — decyzja Artura 17.09.2026.
 *
 * Grupujemy po rekrutacji, bo `InterviewFeedbackSummary` pokazuje NAJNOWSZY
 * wpis każdej strony: bez podziału rozmowa z jednej rekrutacji przykrywałaby
 * feedback z drugiej. Edycja zostaje w kalendarzu i zakładce „Rozmowy"
 * rekrutacji — profil to widok zbiorczy.
 */
export interface CandidateInterviewFeedbackPanelProps {
  candidateId: number;
  /** `job_id → tytuł` z historii rekrutacji kandydata (bez drugiego zapytania). */
  jobTitles: ReadonlyMap<number, string>;
}

export function groupFeedbackByJob(
  rows: InterviewFeedbackRow[],
): { jobId: number | null; rows: InterviewFeedbackRow[] }[] {
  const groups = new Map<number | null, InterviewFeedbackRow[]>();
  for (const row of rows) {
    const key = row.job_id ?? null;
    const bucket = groups.get(key);
    if (bucket) bucket.push(row);
    else groups.set(key, [row]);
  }
  return Array.from(groups, ([jobId, groupRows]) => ({ jobId, rows: groupRows }));
}

export function CandidateInterviewFeedbackPanel({
  candidateId,
  jobTitles,
}: CandidateInterviewFeedbackPanelProps) {
  const query = useInterviewFeedbackByCandidate(candidateId);

  return (
    <section
      aria-label="Feedback po rozmowach"
      className="rounded-xl border border-border bg-card p-4 space-y-3"
    >
      <h3 className="flex items-center gap-1.5 text-sm font-semibold text-foreground">
        <MessageSquare className="h-4 w-4 text-muted-foreground" />
        Feedback po rozmowach
      </h3>
      {query.isPending ? (
        <p className="text-xs text-muted-foreground">Ładowanie feedbacku…</p>
      ) : query.isError ? (
        <p role="alert" className="text-xs text-destructive">
          {apiErrorMessage(query.error, "Nie udało się wczytać feedbacku po rozmowach.")}
        </p>
      ) : query.data.length === 0 ? (
        <p className="text-xs text-muted-foreground">
          Brak zapisanego feedbacku po rozmowach. Uzupełnia się go z okna
          rozmowy w kalendarzu albo z zakładki „Rozmowy” rekrutacji.
        </p>
      ) : (
        groupFeedbackByJob(query.data).map((group) => (
          <div key={group.jobId ?? "bez-rekrutacji"} className="space-y-1.5">
            <p className="text-xs font-medium text-muted-foreground">
              {group.jobId == null
                ? "Rozmowa bez przypisanej rekrutacji"
                : jobTitles.get(group.jobId) ?? `Rekrutacja #${group.jobId}`}
            </p>
            <InterviewFeedbackSummary
              candidateId={candidateId}
              jobId={group.jobId}
              rows={group.rows}
              readOnly
              className="sm:grid-cols-1"
            />
          </div>
        ))
      )}
    </section>
  );
}
