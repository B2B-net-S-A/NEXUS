"use client";

/**
 * „Dopytaj pod CV” w „Ściądze do rozmowy” (decyzja Artura 05.11.2026, wariant 3).
 *
 * Opcjonalne pytania z Profilu Championa i oryginalnego CV. Nic nie blokuje:
 * rekruter wpisuje odpowiedź w notatce z rozmowy i podaje firmę, bo generator
 * przenosi fakt do opisu roli tylko wtedy, gdy zna firmę. Awaria nie wygląda jak
 * pusta lista, a osoba spoza „Nowych” i „Screeningu” sekcji nie widzi.
 */

import { Loader2, RefreshCw } from "lucide-react";

import { apiErrorMessage } from "@/lib/api-error";
import {
  useAutoRefreshCvCallQuestions,
  useCvCallQuestions,
  useRefreshCvCallQuestions,
} from "@/lib/api/cvCallQuestions";
import { cn } from "@/lib/utils";

const TYPE = {
  dock: { body: "text-xs", label: "text-[11px]", pad: "p-2.5" },
  roomy: { body: "text-sm", label: "text-xs", pad: "p-4" },
} as const;

export type CvCallQuestionsSize = keyof typeof TYPE;

function countLabel(count: number): string {
  return count >= 5 ? `${count} opcjonalnych` : `${count} opcjonalne`;
}

function Retry({ onRetry }: { onRetry: () => void }) {
  return (
    <button
      type="button"
      onClick={onRetry}
      className="inline-flex items-center gap-1 font-medium text-primary hover:underline"
    >
      <RefreshCw className="h-3 w-3" aria-hidden="true" /> Ponów
    </button>
  );
}

export function CvCallQuestions({
  candidateId,
  jobId,
  size = "dock",
  framed = false,
}: {
  candidateId: number;
  jobId: number;
  size?: CvCallQuestionsSize;
  /** Sama sekcja, gdy reszta ściągi jest pusta: dostaje wtedy jej ramkę i nagłówek. */
  framed?: boolean;
}) {
  const query = useCvCallQuestions(candidateId, jobId);
  const refresh = useRefreshCvCallQuestions(candidateId, jobId);
  useAutoRefreshCvCallQuestions(candidateId, jobId, query.data, refresh);

  const type = TYPE[size];
  let body: React.ReactNode = null;

  if (query.isError) {
    body = (
      <p className={cn("flex flex-wrap items-center gap-2 text-muted-foreground", type.body)} role="alert">
        {apiErrorMessage(query.error, "Nie udało się wczytać pytań pod CV.")}
        <Retry onRetry={() => void query.refetch()} />
      </p>
    );
  } else if (query.isSuccess) {
    const { status, questions, can_refresh: canRefresh } = query.data;
    if (refresh.isPending && questions.length === 0) {
      body = (
        <p className={cn("flex items-center gap-1.5 text-muted-foreground", type.body)} role="status">
          <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" /> Przygotowuję pytania pod CV…
        </p>
      );
    } else if (refresh.isError || status === "failed") {
      body = (
        <p className={cn("flex flex-wrap items-center gap-2 text-muted-foreground", type.body)} role="alert">
          {refresh.isError
            ? apiErrorMessage(refresh.error, "Nie udało się przygotować pytań pod CV.")
            : "Nie udało się przygotować pytań pod CV."}
          {canRefresh ? <Retry onRetry={() => refresh.mutate()} /> : null}
        </p>
      );
    } else if (status === "ready" && questions.length === 0) {
      body = (
        <p className={cn("text-muted-foreground", type.body)}>
          Nie ma o co dopytać pod CV: wymagania są opisane w rolach albo padły już w rozmowie.
        </p>
      );
    } else if (status === "ready") {
      body = (
        <>
          <p className={cn("font-semibold text-muted-foreground", type.label)}>
            Dopytaj pod CV · {countLabel(questions.length)}
          </p>
          <ol className={cn("list-decimal space-y-1.5 pl-4 text-foreground", type.body)}>
            {questions.map((item) => (
              <li key={item.requirement} className="[overflow-wrap:anywhere]" data-testid="cv-call-question">
                {item.question}
                <span className={cn("block text-muted-foreground", type.label)}>
                  {item.company ? `${item.requirement} · ${item.company}` : item.requirement}
                </span>
              </li>
            ))}
          </ol>
          <p className={cn("text-muted-foreground", type.label)}>
            Odpowiedzi wpisz w notatce z rozmowy i podaj nazwę firmy.
          </p>
        </>
      );
    }
  }

  if (body === null) return null;

  const card = (
    <div
      className="space-y-1.5 rounded-md border border-border bg-card p-2.5"
      data-testid="cv-call-questions"
      data-tour="cheatsheet.cv-questions"
    >
      {body}
    </div>
  );
  if (!framed) return card;
  return (
    <section
      className={cn("space-y-3 rounded-lg border border-primary/30 bg-primary/5", type.pad)}
      aria-label="Ściąga do rozmowy"
    >
      <p className={cn("font-semibold uppercase tracking-wide text-muted-foreground", type.label)}>
        Ściąga do rozmowy
      </p>
      {card}
    </section>
  );
}
