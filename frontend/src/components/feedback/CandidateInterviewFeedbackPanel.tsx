"use client";

import { MessageSquare } from "lucide-react";

import {
  DebriefFeedbackCard,
  InterviewFeedbackSummary,
  isDebriefRow,
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
 *
 * Od 13.10.2026 (E3) feedback rekrutacji z listy siedzi w jej rozwiniętym
 * wierszu (`jobId`), a blok na dole zakładki pokazuje resztę (`excludeJobIds`:
 * rozmowy bez rekrutacji i z rekrutacji spoza listy) — nic nie znika. Każde
 * wystąpienie czyta tę samą kwerendę kandydata, więc to jedno pobranie.
 */
export interface CandidateInterviewFeedbackPanelProps {
  candidateId: number;
  /** `job_id → tytuł` z historii rekrutacji kandydata (bez drugiego zapytania). */
  jobTitles: ReadonlyMap<number, string>;
  /**
   * Profil kandydata (04.10.2026): pusta karta „Brak zapisanego feedbacku”
   * stała zawsze. Z tą flagą sekcja pojawia się dopiero, gdy jest co pokazać;
   * awaria nadal się pokazuje (awaria nie może udawać pustki).
   */
  hideWhenEmpty?: boolean;
  /** Tylko feedback tej rekrutacji (bez podpisu grupy — wiersz ją nazywa). */
  jobId?: number;
  /** Bez feedbacku tych rekrutacji (pokazanych gdzie indziej); `null` zostaje. */
  excludeJobIds?: ReadonlySet<number>;
}

export function filterFeedbackRows(
  rows: InterviewFeedbackRow[],
  { jobId, excludeJobIds }: { jobId?: number; excludeJobIds?: ReadonlySet<number> },
): InterviewFeedbackRow[] {
  if (jobId != null) return rows.filter((row) => row.job_id === jobId);
  if (excludeJobIds && excludeJobIds.size > 0) {
    return rows.filter((row) => row.job_id == null || !excludeJobIds.has(row.job_id));
  }
  return rows;
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
  hideWhenEmpty = false,
  jobId,
  excludeJobIds,
}: CandidateInterviewFeedbackPanelProps) {
  const query = useInterviewFeedbackByCandidate(candidateId);
  const rows = query.isSuccess ? filterFeedbackRows(query.data, { jobId, excludeJobIds }) : [];
  if (hideWhenEmpty && (query.isPending || (query.isSuccess && rows.length === 0))) {
    return null;
  }

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
      ) : rows.length === 0 ? (
        <p className="text-xs text-muted-foreground">
          Brak zapisanego feedbacku po rozmowach. Uzupełnia się go z okna
          rozmowy w kalendarzu albo z zakładki „Rozmowy” rekrutacji.
        </p>
      ) : (
        groupFeedbackByJob(rows).map((group) => (
          <div key={group.jobId ?? "bez-rekrutacji"} className="space-y-1.5">
            {jobId == null ? (
              <p className="text-xs font-medium text-muted-foreground">
                {group.jobId == null
                  ? "Rozmowa bez przypisanej rekrutacji"
                  : jobTitles.get(group.jobId) ?? `Rekrutacja #${group.jobId}`}
              </p>
            ) : null}
            {/* Każdy debrief osobno (04.10.2026): kolejna runda nie może
                przykryć warunku kandydata z poprzedniej. */}
            {group.rows.filter(isDebriefRow).map((row) => (
              <DebriefFeedbackCard key={row.id} row={row} />
            ))}
            {group.rows.some((row) => !isDebriefRow(row)) ? (
              <InterviewFeedbackSummary
                candidateId={candidateId}
                jobId={group.jobId}
                rows={group.rows.filter((row) => !isDebriefRow(row))}
                readOnly
                hideEmpty
                className="sm:grid-cols-1"
              />
            ) : null}
          </div>
        ))
      )}
    </section>
  );
}
