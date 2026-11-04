"use client";

import { useState } from "react";
import { ChevronDown, ChevronUp, Copy, MessageSquare } from "lucide-react";

import {
  IMPRESSION_TO_OUTCOME,
  clientQuestionLines,
  formatWhen,
  isDebriefRow,
  useInterviewFeedbackByCandidate,
} from "@/components/feedback/InterviewFeedbackSummary";
import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { candidateBoardHref, isRecruitmentEnded } from "@/components/v2/candidate-profile/profile-helpers";
import { JobNameLabel } from "@/components/v2/jobs/JobNameLabel";
import type { InterviewFeedbackRow } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { useClientQuestions } from "@/lib/api/interviewCycle";
import type { NoteRecruitmentFilter } from "@/lib/candidate-notes-view";
import { OFFER_LABELS, OUTCOME_LABELS } from "@/lib/interview-cycle";
import { candidateJobNames } from "@/lib/job-name-text";
import { recruitmentOutcome } from "@/lib/recruitment-stage-label";
import { formatDate } from "@/lib/utils";

/**
 * Debrief i pytania klienta na górze „Notatki → Rozmowy” (wariant B, zgłoszenie
 * 04.11.2026): po odrzuceniu para wypada z kalendarza, a pytania są potrzebne
 * przed prepem następnej osoby. Dotąd były tylko w rozwiniętym wierszu
 * „Rekrutacji”, pod kartą procesu; ta sekcja zostaje tam bez zmian.
 */

/* eslint-disable @typescript-eslint/no-explicit-any -- odpowiedź /history jest luźno typowana */

const OUTCOME_BADGE = { success: "success", danger: "danger", warning: "warning", neutral: "neutral" } as const;

/** Wpis strony klienta bez pytań (ocena, decyzja) zostaje w „Rekrutacjach”. */
function isInterviewNote(row: InterviewFeedbackRow): boolean {
  return isDebriefRow(row) || clientQuestionLines(row).length > 0;
}

function matchesJobFilter(row: InterviewFeedbackRow, filter: NoteRecruitmentFilter): boolean {
  if (filter === "all") return true;
  return filter === "none" ? row.job_id == null : row.job_id === filter;
}

const sameQuestionKey = (text: string): string => text.trim().replace(/\s+/g, " ").toLowerCase();

export function ClientInterviewNotes({
  candidateId,
  recruitments,
  jobFilter,
}: {
  candidateId: number;
  recruitments: any[];
  jobFilter: NoteRecruitmentFilter;
}) {
  const query = useInterviewFeedbackByCandidate(candidateId);
  if (query.isError) {
    return (
      <p role="alert" className="text-xs text-destructive">
        {apiErrorMessage(query.error, "Nie udało się wczytać notatek po rozmowach u klienta.")} Zapisane
        pytania nie zniknęły — to nieudane pobranie.
      </p>
    );
  }
  const rows = (query.data ?? []).filter(
    (row) => isInterviewNote(row) && matchesJobFilter(row, jobFilter),
  );
  if (rows.length === 0) return null;
  return (
    <section aria-label="Po rozmowach u klienta" className="space-y-2">
      {rows.map((row) => (
        <InterviewNoteCard
          key={row.id}
          row={row}
          candidateId={candidateId}
          job={recruitments.find((item) => (item?.job_id ?? item?.id) === row.job_id) ?? null}
        />
      ))}
    </section>
  );
}

function InterviewNoteCard({
  row,
  candidateId,
  job,
}: {
  row: InterviewFeedbackRow;
  candidateId: number;
  job: any | null;
}) {
  const questions = clientQuestionLines(row);
  const titleId = `client-interview-note-${row.id}`;
  const interviewAt = formatWhen(row.calendar_event_start);
  const meta = [
    interviewAt ? `rozmowa ${interviewAt}` : null,
    row.author_name ? `zapisał(a) ${row.author_name}` : null,
  ].filter(Boolean);
  const outcome = job && isRecruitmentEnded(job) ? recruitmentOutcome(job) : null;
  return (
    <article aria-labelledby={titleId} className="space-y-2 rounded-lg border border-primary/30 bg-card px-3 py-2.5">
      <header className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
        <MessageSquare aria-hidden="true" className="h-3.5 w-3.5 text-primary" />
        <h3 id={titleId} className="font-semibold text-foreground">
          Po rozmowie u klienta
        </h3>
        {job && row.job_id != null ? (
          <JobNameLabel
            job={candidateJobNames({ ...job, job_id: row.job_id })}
            href={candidateBoardHref(row.job_id, candidateId)}
            wrap
            titleClassName="text-xs font-medium text-primary hover:underline"
          />
        ) : null}
        {outcome ? (
          <Badge size="sm" variant={OUTCOME_BADGE[outcome.tone]}>
            {outcome.label}
            {job.last_seen ? ` ${formatDate(job.last_seen)}` : ""}
          </Badge>
        ) : null}
        {meta.length > 0 ? (
          <span className="text-muted-foreground tabular-nums">{meta.join(" · ")}</span>
        ) : null}
      </header>
      <NoteBody row={row} questions={questions} />
      {row.job_id != null ? <OtherJobQuestions jobId={row.job_id} own={questions} /> : null}
    </article>
  );
}

function NoteBody({ row, questions }: { row: InterviewFeedbackRow; questions: string[] }) {
  const outcome = row.overall_impression != null ? IMPRESSION_TO_OUTCOME[row.overall_impression] : undefined;
  const facts = [
    { label: "Jak poszło", value: outcome ? OUTCOME_LABELS[outcome] : null },
    { label: "Czy przyjmie ofertę", value: row.offer_acceptance ? OFFER_LABELS[row.offer_acceptance] : null },
    { label: "Warunek / zastrzeżenie", value: row.acceptance_condition },
    { label: "Komentarz kandydata", value: row.concerns },
  ].filter((fact) => fact.value);
  return (
    <div className={facts.length > 0 ? "grid gap-3 md:grid-cols-[3fr_2fr]" : undefined}>
      <div className="min-w-0 space-y-1.5">
        <div className="flex min-h-8 flex-wrap items-center justify-between gap-2">
          <h4 className="text-xs font-semibold text-foreground">
            Pytania klienta{questions.length > 0 ? ` (${questions.length})` : ""}
          </h4>
          {questions.length > 0 ? <CopyQuestions questions={questions} /> : null}
        </div>
        {questions.length > 0 ? (
          <ol className="list-decimal space-y-0.5 pl-5 text-sm text-foreground">
            {questions.map((question, index) => (
              <li key={index} className="break-words">
                {question}
              </li>
            ))}
          </ol>
        ) : (
          <p className="text-xs text-muted-foreground">
            {row.no_client_questions ? "Klient nie zadawał pytań." : "Nie zapisano pytań."}
          </p>
        )}
      </div>
      {facts.length > 0 ? (
        <dl className="min-w-0 space-y-1.5 rounded-md bg-muted/50 p-2.5">
          {facts.map((fact) => (
            <div key={fact.label}>
              <dt className="text-xs text-muted-foreground">{fact.label}</dt>
              <dd className="whitespace-pre-line break-words text-xs text-foreground">{fact.value}</dd>
            </div>
          ))}
        </dl>
      ) : null}
    </div>
  );
}

function CopyQuestions({ questions }: { questions: string[] }) {
  const { showError, showSuccess } = useToast();
  const failed = () => showError("Nie udało się skopiować — zaznacz pytania i skopiuj ręcznie.");
  const copy = () => {
    if (!navigator.clipboard?.writeText) {
      failed();
      return;
    }
    navigator.clipboard.writeText(questions.join("\n")).then(() => showSuccess("Skopiowano pytania"), failed);
  };
  return (
    <button
      type="button"
      data-tour="candidate.notes.client-questions"
      onClick={copy}
      className="inline-flex min-h-8 items-center gap-1 rounded-md border border-border bg-card px-2 text-xs font-medium text-foreground hover:bg-accent focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
    >
      <Copy aria-hidden="true" className="h-3 w-3" />
      Kopiuj pytania
    </button>
  );
}

/** Pytania z tej rekrutacji spoza tego debriefu: pod prep następnej osoby. */
function OtherJobQuestions({ jobId, own }: { jobId: number; own: string[] }) {
  const query = useClientQuestions(jobId);
  const [open, setOpen] = useState(false);
  if (query.isError) {
    return (
      <p role="alert" className="border-t border-border pt-2 text-xs text-destructive">
        {apiErrorMessage(query.error, "Nie udało się wczytać innych pytań z tej rekrutacji.")}
      </p>
    );
  }
  const ownKeys = new Set(own.map(sameQuestionKey));
  const others = (query.data ?? []).filter((question) => !ownKeys.has(sameQuestionKey(question.text)));
  if (others.length === 0) return null;
  const Icon = open ? ChevronUp : ChevronDown;
  return (
    <div className="border-t border-border pt-1.5">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="inline-flex min-h-8 items-center gap-1 text-xs font-medium text-primary hover:underline"
      >
        <Icon aria-hidden="true" className="h-3.5 w-3.5" />
        Inne pytania z rozmów w tej rekrutacji ({others.length})
      </button>
      {open ? (
        <ul className="mt-1 list-disc space-y-0.5 pl-5 text-xs text-foreground">
          {others.map((question) => (
            <li key={question.id} className="break-words">
              {question.text}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
