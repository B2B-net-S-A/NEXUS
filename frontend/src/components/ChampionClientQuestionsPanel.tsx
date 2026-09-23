"use client";

import { Plus } from "lucide-react";

import { useClientQuestionPool } from "@/lib/api/interviewCycle";

/** Porównanie „to samo pytanie”: bez wielkości liter, białych znaków i punktorów. */
export function normalizeQuestion(text: string): string {
  return text
    .replace(/^[\s•\-*–·]+/, "")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}

/** Linie pola „Historyczne pytania klienta” jako znormalizowany zbiór. */
function historicalSet(historical: string): Set<string> {
  return new Set(
    historical
      .split("\n")
      .map(normalizeQuestion)
      .filter(Boolean),
  );
}

/**
 * „Pytania klienta z rozmów” — pula pytań, które klient tej rekrutacji zadawał
 * kandydatom (debriefy po rozmowach u klienta, bramka przed „Umową”). Delivery
 * Lead dopisuje je do pytań screeningowych albo do historycznych pytań
 * klienta w profilu Championa.
 *
 * Panel edytuje WYŁĄCZNIE szkic edytora (`onAddScreening`/`onAddHistorical`) —
 * zapis zostaje zwykłym „Zapisz” profilu. Awaria odczytu jest komunikatem,
 * nie pustą listą: pustka czytałaby się jak „klient nigdy o nic nie pytał”.
 */
export function ChampionClientQuestionsPanel({
  jobId,
  screeningQuestions,
  historicalQuestions,
  canEdit,
  onAddScreening,
  onAddHistorical,
}: {
  jobId: number;
  screeningQuestions: string[];
  historicalQuestions: string;
  canEdit: boolean;
  onAddScreening: (text: string) => void;
  onAddHistorical: (text: string) => void;
}) {
  const query = useClientQuestionPool("job", jobId);
  const questions = Array.isArray(query.data) ? query.data : [];
  const inScreening = new Set(screeningQuestions.map(normalizeQuestion).filter(Boolean));
  const inHistorical = historicalSet(historicalQuestions);

  return (
    <section
      className="rounded-lg border border-border bg-muted/40 p-3"
      data-testid="champion-client-questions"
      aria-labelledby="champion-client-questions-heading"
    >
      <h4
        id="champion-client-questions-heading"
        className="text-xs font-semibold text-foreground"
      >
        Pytania klienta z rozmów
        {query.isSuccess ? ` (${questions.length})` : ""}
      </h4>
      <p className="mt-0.5 mb-2 text-[11px] text-muted-foreground">
        Zebrane w telefonach do kandydatów po rozmowach u tego klienta.
      </p>
      {query.isPending ? (
        <p className="text-xs text-muted-foreground">Wczytuję pytania klienta…</p>
      ) : query.isError ? (
        <div role="alert" className="flex flex-wrap items-center gap-2 text-xs text-destructive">
          Nie udało się wczytać pytań klienta — lista może istnieć.
          <button
            type="button"
            onClick={() => query.refetch()}
            className="font-medium underline"
          >
            Ponów
          </button>
        </div>
      ) : questions.length === 0 ? (
        <p className="text-xs text-muted-foreground">
          Jeszcze nic — pytania pojawią się po pierwszym telefonie do kandydata
          po rozmowie u tego klienta.
        </p>
      ) : (
        <ul className="space-y-2">
          {questions.map((q) => {
            const key = normalizeQuestion(q.text);
            const hasScreening = inScreening.has(key);
            const hasHistorical = inHistorical.has(key);
            return (
              <li
                key={q.id}
                className="rounded-md border border-border bg-card px-2.5 py-2"
                data-testid={`champion-client-question-${q.id}`}
              >
                <p className="text-xs text-foreground">{q.text}</p>
                <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1">
                  {hasScreening || hasHistorical ? (
                    <span className="text-[11px] text-muted-foreground">już w profilu</span>
                  ) : null}
                  {canEdit && !hasScreening ? (
                    <button
                      type="button"
                      onClick={() => onAddScreening(q.text)}
                      className="inline-flex items-center gap-1 text-[11px] font-medium text-primary hover:underline"
                    >
                      <Plus className="h-3 w-3" aria-hidden />
                      Dodaj do pytań screeningowych
                    </button>
                  ) : null}
                  {canEdit && !hasHistorical ? (
                    <button
                      type="button"
                      onClick={() => onAddHistorical(q.text)}
                      className="inline-flex items-center gap-1 text-[11px] font-medium text-primary hover:underline"
                    >
                      <Plus className="h-3 w-3" aria-hidden />
                      Dodaj do historycznych pytań
                    </button>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
