"use client";

import Link from "next/link";
import { useMemo, useState, type ReactNode } from "react";

import { useAllClientQuestions, type ClientQuestion } from "@/lib/api/interviewCycle";

export interface RecruitmentQuestionGroup {
  /** `null` = debrief poprawiony albo rekrutacja poza dostępem pytającego. */
  jobId: number | null;
  title: string;
  questions: ClientQuestion[];
}

const NO_RECRUITMENT_TITLE = "Bez wskazanej rekrutacji";

/** Pytanie z kilku rekrutacji stoi w każdej; kolejność grup idzie za najnowszym pytaniem. */
export function groupByRecruitment(questions: ClientQuestion[]): RecruitmentQuestionGroup[] {
  const groups = new Map<number | null, RecruitmentQuestionGroup>();
  const add = (jobId: number | null, title: string, question: ClientQuestion) => {
    const group = groups.get(jobId);
    if (group) group.questions.push(question);
    else groups.set(jobId, { jobId, title, questions: [question] });
  };
  for (const question of questions) {
    if (question.jobs?.length) {
      for (const job of question.jobs) add(job.id, job.title, question);
    } else {
      add(null, NO_RECRUITMENT_TITLE, question);
    }
  }
  return [...groups.values()];
}

function matchesFilter(group: RecruitmentQuestionGroup, needle: string): RecruitmentQuestionGroup | null {
  if (!needle || group.title.toLowerCase().includes(needle)) return group;
  const questions = group.questions.filter((q) => q.text.toLowerCase().includes(needle));
  return questions.length > 0 ? { ...group, questions } : null;
}

/**
 * Wszystkie pytania klienta z rozmów, pogrupowane po rekrutacji, w której padły
 * (zgłoszenie 02.11.2026). Pobierane dopiero po otwarciu: pod rekrutacją domyślnie
 * stoją tylko pytania z tej rekrutacji. Awaria jest komunikatem, nie pustą listą.
 */
export function AllClientQuestions({
  jobId,
  renderQuestion,
}: {
  jobId: number;
  renderQuestion: (question: ClientQuestion, group: RecruitmentQuestionGroup) => ReactNode;
}) {
  const query = useAllClientQuestions(jobId, true);
  const [filter, setFilter] = useState("");
  const groups = useMemo(
    () => groupByRecruitment(Array.isArray(query.data) ? query.data : []),
    [query.data],
  );
  const needle = filter.trim().toLowerCase();
  const visible = groups
    .map((group) => matchesFilter(group, needle))
    .filter((group): group is RecruitmentQuestionGroup => group !== null);

  if (query.isPending) {
    return <p className="text-xs text-muted-foreground">Wczytuję pytania klienta…</p>;
  }
  if (query.isError) {
    return (
      <div role="alert" className="flex flex-wrap items-center gap-2 text-xs text-destructive">
        Nie udało się wczytać pytań klienta — lista może istnieć.
        <button type="button" onClick={() => query.refetch()} className="font-medium underline">
          Ponów
        </button>
      </div>
    );
  }
  if (groups.length === 0) {
    return (
      <p className="text-xs text-muted-foreground">
        Jeszcze nic — ten klient nie ma zapisanych pytań z rozmów.
      </p>
    );
  }
  return (
    <div className="space-y-3" data-testid="all-client-questions">
      <input
        type="search"
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        placeholder="Szukaj w pytaniach i nazwach rekrutacji"
        aria-label="Szukaj w pytaniach i nazwach rekrutacji"
        className="w-full rounded-md border border-input bg-background px-2.5 py-1.5 text-xs text-foreground"
      />
      {visible.length === 0 ? (
        <p className="text-xs text-muted-foreground">Nic nie pasuje do tego wyszukiwania.</p>
      ) : (
        visible.map((group) => (
          <div key={group.jobId ?? "none"} data-testid={`all-client-questions-group-${group.jobId ?? "none"}`}>
            <h5 className="mb-1 text-xs font-semibold text-foreground">
              {group.jobId != null ? (
                <Link href={`/jobs/${group.jobId}`} className="hover:underline">
                  {group.title}
                </Link>
              ) : (
                group.title
              )}
              {group.jobId === jobId ? (
                <span className="font-normal text-muted-foreground"> · ta rekrutacja</span>
              ) : null}
              <span className="font-normal text-muted-foreground"> ({group.questions.length})</span>
            </h5>
            <ul className="space-y-2">
              {group.questions.map((question) => renderQuestion(question, group))}
            </ul>
          </div>
        ))
      )}
    </div>
  );
}
