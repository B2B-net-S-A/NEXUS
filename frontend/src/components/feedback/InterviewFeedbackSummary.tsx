"use client";

import { useQuery } from "@tanstack/react-query";
import { MessageSquare, Pencil, Plus } from "lucide-react";

import {
  interviewFeedbackApi,
  type InterviewFeedbackRow,
  type InterviewFeedbackSource,
} from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { cn } from "@/lib/utils";

/**
 * Zapisany feedback po rozmowie — dwie karty: od kandydata i od klienta.
 *
 * Do 09.2026 jedynym konsumentem `interviewFeedbackApi` był sam formularz:
 * feedback zapisywał się i nigdzie nie był widoczny, a karta rekrutacji dalej
 * mówiła „do uzupełnienia".
 */

export const interviewFeedbackByCandidateKey = (candidateId: number) =>
  ["interview-feedback", "by-candidate", candidateId] as const;

/** Wszystkie wpisy feedbacku kandydata (backend zawęża do rekrutacji wołającego). */
export function useInterviewFeedbackByCandidate(candidateId: number | null | undefined) {
  return useQuery<InterviewFeedbackRow[]>({
    queryKey: interviewFeedbackByCandidateKey(candidateId ?? 0),
    enabled: candidateId != null && candidateId > 0,
    queryFn: () =>
      interviewFeedbackApi
        .list({ candidate_id: candidateId as number })
        .then((r) => r.data as InterviewFeedbackRow[]),
    staleTime: 30_000,
  });
}

export interface InterviewFeedbackEditRequest {
  source: InterviewFeedbackSource;
  /** Wydarzenie wpisu (albo z `calendarEventId` przy „Uzupełnij"); `null` = werdykt z karty rekrutacji. */
  calendarEventId: number | null;
  /** Istniejący wpis — `null` przy „Uzupełnij". */
  feedbackId: number | null;
}

export interface InterviewFeedbackSummaryProps {
  /** Kandydat, którego feedback pokazujemy. */
  candidateId: number;
  /** Zawęża do jednej rekrutacji. */
  jobId?: number | null;
  /** Zawęża do jednego wydarzenia; włącza „Uzupełnij" dla brakującej strony. */
  calendarEventId?: number | null;
  /** Gotowe wiersze (np. z listy wyżej) — bez nich komponent pobiera sam. */
  rows?: InterviewFeedbackRow[];
  /** Bez przycisków „Uzupełnij/Edytuj" (np. profil kandydata). */
  readOnly?: boolean;
  /** Otwórz formularz feedbacku; bez tej funkcji przyciski się nie renderują. */
  onEdit?: (request: InterviewFeedbackEditRequest) => void;
  className?: string;
}

const INTEREST_LABELS: Record<string, string> = {
  hot: "Hot — gotowy iść dalej",
  warm: "Warm — rozważa",
  cold: "Cold — niska pilność",
  dead: "Dead — rezygnuje",
};

const NEXT_STEP_LABELS: Record<string, string> = {
  ready_for_next: "Gotowy na kolejny krok",
  need_info: "Potrzebuje więcej informacji",
  pass: "Rezygnuje",
};

const DECISION_LABELS: Record<string, { label: string; tone: string }> = {
  advance: { label: "Idziemy dalej", tone: "bg-success-muted text-success-muted-foreground" },
  reject: { label: "Odrzucony", tone: "bg-destructive/15 text-destructive" },
  on_hold: { label: "Wstrzymane", tone: "bg-warning-muted text-warning-muted-foreground" },
};

/** Najnowszy wpis każdej strony po zawężeniu (lista przychodzi malejąco po dacie). */
export function latestFeedbackBySource(
  rows: InterviewFeedbackRow[],
  { jobId, calendarEventId }: { jobId?: number | null; calendarEventId?: number | null },
): Partial<Record<InterviewFeedbackSource, InterviewFeedbackRow>> {
  const out: Partial<Record<InterviewFeedbackSource, InterviewFeedbackRow>> = {};
  for (const row of rows) {
    if (jobId != null && row.job_id !== jobId) continue;
    if (calendarEventId != null && row.calendar_event_id !== calendarEventId) continue;
    if (!out[row.feedback_source]) out[row.feedback_source] = row;
  }
  return out;
}

export function InterviewFeedbackSummary({
  candidateId,
  jobId = null,
  calendarEventId = null,
  rows,
  readOnly = false,
  onEdit,
  className,
}: InterviewFeedbackSummaryProps) {
  const query = useInterviewFeedbackByCandidate(rows ? null : candidateId);
  const source = rows ?? query.data;

  if (!rows && query.isError) {
    return (
      <div role="alert" className={cn("rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-xs text-destructive", className)}>
        {apiErrorMessage(query.error, "Nie udało się wczytać feedbacku po rozmowach.")} Zapisany
        feedback nie zniknął — to nieudane pobranie.
      </div>
    );
  }
  if (!source) {
    return (
      <div className={cn("text-xs text-muted-foreground", className)}>Ładowanie feedbacku…</div>
    );
  }

  const latest = latestFeedbackBySource(source, { jobId, calendarEventId });
  const editable = !readOnly && !!onEdit;

  return (
    <div className={cn("grid gap-3 sm:grid-cols-2", className)} data-testid="interview-feedback-summary">
      <FeedbackCard
        title="Feedback od kandydata"
        row={latest.candidate_side}
        editable={editable}
        canCreate={editable && calendarEventId != null}
        onEdit={() =>
          onEdit?.({
            source: "candidate_side",
            calendarEventId: latest.candidate_side?.calendar_event_id ?? calendarEventId,
            feedbackId: latest.candidate_side?.id ?? null,
          })
        }
      >
        {latest.candidate_side ? <CandidateSideBody row={latest.candidate_side} /> : null}
      </FeedbackCard>
      <FeedbackCard
        title="Feedback od klienta"
        row={latest.client_side}
        editable={editable}
        canCreate={editable && calendarEventId != null}
        onEdit={() =>
          onEdit?.({
            source: "client_side",
            calendarEventId: latest.client_side?.calendar_event_id ?? calendarEventId,
            feedbackId: latest.client_side?.id ?? null,
          })
        }
      >
        {latest.client_side ? <ClientSideBody row={latest.client_side} /> : null}
      </FeedbackCard>
    </div>
  );
}

function FeedbackCard({
  title,
  row,
  editable,
  canCreate,
  onEdit,
  children,
}: {
  title: string;
  row: InterviewFeedbackRow | undefined;
  editable: boolean;
  canCreate: boolean;
  onEdit: () => void;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-lg border border-border bg-card p-3 space-y-2" aria-label={title}>
      <header className="flex items-center justify-between gap-2">
        <h4 className="flex items-center gap-1.5 text-xs font-semibold text-foreground">
          <MessageSquare className="h-3.5 w-3.5 text-muted-foreground" />
          {title}
        </h4>
        {row && editable ? (
          <button
            type="button"
            onClick={onEdit}
            className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-0.5 text-xs hover:bg-muted"
          >
            <Pencil className="h-3 w-3" />
            Edytuj
          </button>
        ) : !row && canCreate ? (
          <button
            type="button"
            onClick={onEdit}
            className="inline-flex items-center gap-1 rounded-md bg-primary px-2 py-0.5 text-xs text-primary-foreground hover:bg-primary/90"
          >
            <Plus className="h-3 w-3" />
            Uzupełnij
          </button>
        ) : null}
      </header>
      {row ? children : <p className="text-xs text-muted-foreground">Brak zapisanego feedbacku.</p>}
    </section>
  );
}

function Line({ label, value }: { label: string; value: React.ReactNode }) {
  if (value == null || value === "") return null;
  return (
    <div className="text-xs">
      <span className="text-muted-foreground">{label}: </span>
      <span className="text-foreground whitespace-pre-line break-words">{value}</span>
    </div>
  );
}

function CandidateSideBody({ row }: { row: InterviewFeedbackRow }) {
  return (
    <div className="space-y-1">
      <Line label="Ogólne wrażenie" value={row.overall_impression != null ? `${row.overall_impression}/5` : null} />
      <Line label="Zainteresowanie" value={row.interest_level ? INTEREST_LABELS[row.interest_level] ?? row.interest_level : null} />
      <Line label="Kolejny krok" value={row.next_step_preference ? NEXT_STEP_LABELS[row.next_step_preference] ?? row.next_step_preference : null} />
      <Line label="Pytania kandydata" value={row.candidate_questions} />
      <Line label="Wątpliwości" value={row.concerns} />
    </div>
  );
}

function ClientSideBody({ row }: { row: InterviewFeedbackRow }) {
  const decision = row.decision ? DECISION_LABELS[row.decision] : null;
  const scores = [
    row.technical_fit != null ? `technicznie ${row.technical_fit}/5` : null,
    row.soft_fit != null ? `miękkie ${row.soft_fit}/5` : null,
    row.overall_fit != null ? `ogólnie ${row.overall_fit}/5` : null,
  ].filter(Boolean);
  return (
    <div className="space-y-1">
      {decision ? (
        <span className={cn("inline-block rounded-full px-2 py-0.5 text-xs font-medium", decision.tone)}>
          {decision.label}
        </span>
      ) : null}
      <Line label="Oceny" value={scores.length ? scores.join(" · ") : null} />
      <Line label="Podsumowanie" value={row.feedback_summary} />
      <Line label="Pytania klienta" value={row.client_questions} />
    </div>
  );
}
