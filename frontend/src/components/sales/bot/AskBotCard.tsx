"use client";

import { Send } from "lucide-react";
import { useState } from "react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { apiErrorMessage } from "@/lib/api-error";
import { useAskBot, useCompanyQuestions, type BotQuestion } from "@/lib/api/sales-bot";
import { formatDateTimePl } from "@/lib/date-pl";

import { BotTag, SourceLink } from "./kit";

const MIN_QUESTION = 5;
const MAX_QUESTION = 300;

function QuestionItem({
  item,
  onRetry,
  retrying,
}: {
  item: BotQuestion;
  onRetry?: (question: string) => void;
  retrying: boolean;
}) {
  const header = [
    item.asked_by?.name ?? "Ktoś z zespołu",
    formatDateTimePl(item.asked_at),
    item.status === "received" && item.minutes !== null ? `odpowiedź po ${item.minutes} min` : null,
  ]
    .filter(Boolean)
    .join(" · ");
  const failed = item.status === "failed" || item.status === "expired";
  return (
    <li className="space-y-1 rounded-md border border-border bg-muted/30 px-3 py-2">
      <p className="text-xs text-muted-foreground">{header}</p>
      {item.question && <p className="text-sm font-medium text-foreground">„{item.question}”</p>}
      {item.status === "started" && (
        <p className="text-sm text-muted-foreground" role="status">
          Bot szuka odpowiedzi, zwykle kilka minut.
        </p>
      )}
      {failed && (
        <div className="flex flex-wrap items-center gap-2 text-sm text-destructive" role="alert">
          <span>
            {item.status === "expired"
              ? "Bot nie odpowiedział w ciągu 2 godzin."
              : "Nie udało się przekazać pytania botowi."}
          </span>
          {onRetry && item.question && (
            <Button size="sm" variant="outline" className="h-7" disabled={retrying} onClick={() => onRetry(item.question!)}>
              Zapytaj ponownie
            </Button>
          )}
        </div>
      )}
      {item.status === "received" &&
        (item.answer && item.answer.length > 0 ? (
          <ul className="space-y-1">
            {item.answer.map((line, index) => (
              <li key={index} className="text-sm text-foreground">
                {line.text}{" "}
                {line.url ? (
                  <SourceLink url={line.url} className="ml-1" />
                ) : (
                  <span className="ml-1 text-xs text-muted-foreground">wniosek bota</span>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted-foreground">Bot nie znalazł odpowiedzi w otwartych źródłach.</p>
        ))}
    </li>
  );
}

interface AskBotCardProps {
  companyId: number;
  companyName: string;
  canEdit: boolean;
}

/** G-B: pytanie do bota o tę firmę; odpowiedź ze źródłami wraca na kartę po kilku minutach. */
export function AskBotCard({ companyId, companyName, canEdit }: AskBotCardProps) {
  const questions = useCompanyQuestions(companyId);
  const ask = useAskBot(companyId);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);

  if (questions.isSuccess && !questions.data.enabled) return null;
  if (questions.isLoading) return null;

  const submit = (text: string, clear: boolean) => {
    const question = text.trim();
    if (question.length < MIN_QUESTION) {
      setError(`Pytanie musi mieć co najmniej ${MIN_QUESTION} znaków.`);
      return;
    }
    setError(null);
    ask.mutate(question, {
      onSuccess: () => {
        if (clear) setDraft("");
      },
      onError: (failure) => setError(apiErrorMessage(failure, "Nie udało się wysłać pytania do bota.")),
    });
  };

  return (
    <Card className="space-y-3 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold text-foreground">Zapytaj bota o {companyName}</h2>
          <BotTag />
        </div>
        <span className="text-xs text-muted-foreground">
          odpowiedź w kilka minut · do bota idzie nazwa, domena i pytanie
        </span>
      </div>
      {canEdit && (
        <form
          className="space-y-1"
          onSubmit={(event) => {
            event.preventDefault();
            submit(draft, true);
          }}
        >
          <div className="flex gap-2">
            <Input
              value={draft}
              maxLength={MAX_QUESTION}
              onChange={(event) => setDraft(event.target.value)}
              placeholder="np. Czy mają centrum IT w Polsce i kogo teraz rekrutują?"
              aria-label="Pytanie do bota"
              data-tour="sales.company.ask"
              className="h-8"
            />
            <Button size="sm" type="submit" className="h-8 shrink-0" disabled={ask.isPending}>
              <Send className="mr-1 size-3.5" aria-hidden />
              Zapytaj
            </Button>
          </div>
          {error ? (
            <p className="text-xs text-destructive" role="alert">
              {error}
            </p>
          ) : (
            <p className="text-xs text-muted-foreground">Bez adresów e-mail, telefonów i innych danych osobowych.</p>
          )}
        </form>
      )}
      {questions.isError ? (
        <QueryStateNotice
          state="error"
          description="Nie udało się wczytać pytań do bota."
          onRetry={() => void questions.refetch()}
        />
      ) : questions.isSuccess && questions.data.items.length === 0 ? (
        <p className="text-sm text-muted-foreground">Nikt jeszcze nie pytał bota o tę firmę.</p>
      ) : questions.isSuccess ? (
        <ul className="space-y-2" aria-label="Pytania do bota">
          {questions.data.items.map((item) => (
            <QuestionItem
              key={item.run_id}
              item={item}
              retrying={ask.isPending}
              onRetry={canEdit ? (question) => submit(question, false) : undefined}
            />
          ))}
        </ul>
      ) : null}
    </Card>
  );
}
