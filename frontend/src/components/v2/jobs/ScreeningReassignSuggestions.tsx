"use client";

/**
 * Przepięcie → podpowiedzi Luny w arkuszu screeningu (Pipeline v4, 23.09.2026).
 *
 * Osoba przepięta z podobnej rekrutacji odpowiadała już na pytania
 * screeningowe tamtej rekrutacji. Baner pokazuje się WYŁĄCZNIE, gdy serwer
 * zna rekrutację źródłową (`GET …/screening/reassign-context` — bez modelu,
 * bez kosztu). Dopiero „Podpowiedz odpowiedzi" woła Lunę.
 *
 * Każda podpowiedź to propozycja: „Przyjmij" wpisuje ją w pole odpowiedzi
 * (`origin: reassign_suggested`), „Popraw" wpisuje i ustawia kursor w polu,
 * „Odrzuć podpowiedź" ją chowa. Nic nie zapisuje się samo — zapis to dalej
 * „Zapisz screening". Awaria Luny to komunikat, nie blokada: arkusz działa
 * ręcznie jak dotąd.
 *
 * „Pomiń brakujące — przepięcie" pozwala zapisać arkusz bez odpowiedzi na
 * pytania, których poprzedni screening nie objął; pominięte odpowiedzi
 * i notatka wewnętrzna NIGDY nie idą do klienta (share portal, generator CV).
 *
 * Komponent musi stać WEWNĄTRZ `<Form>` arkusza — pole notatki korzysta
 * z kontekstu formularza.
 */

import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import type { UseFormReturn } from "react-hook-form";
import { Loader2, Sparkles } from "lucide-react";

import {
  screeningApi,
  type ScreeningQuestion,
  type ScreeningReassignSuggestion,
  type ScreeningReassignSuggestionsResponse,
} from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { FormField, TextareaField } from "@/components/v2/forms";
import type { ScreeningFormValues } from "@/components/v2/screening/ScreeningForm";
import { countPl } from "@/lib/plural-pl";
import { formatDate } from "@/lib/utils";

export const reassignContextQueryKey = (stageId: number) =>
  ["screening-reassign-context", stageId] as const;

const CONFIDENCE: Record<
  ScreeningReassignSuggestion["confidence"],
  { label: string; variant: "success" | "warning" | "neutral" }
> = {
  high: { label: "pewne", variant: "success" },
  medium: { label: "prawdopodobne", variant: "warning" },
  low: { label: "niepewne", variant: "neutral" },
};

export interface ScreeningReassignSuggestionsProps {
  stageId: number;
  questions: ScreeningQuestion[];
  methods: UseFormReturn<ScreeningFormValues>;
  readOnly?: boolean;
}

export function ScreeningReassignSuggestions({
  stageId,
  questions,
  methods,
  readOnly = false,
}: ScreeningReassignSuggestionsProps) {
  // Podpowiedzi, które rekruter już przyjął albo odrzucił — znikają z listy.
  const [handled, setHandled] = useState<Set<string>>(() => new Set());

  const contextQuery = useQuery({
    queryKey: reassignContextQueryKey(stageId),
    queryFn: () => screeningApi.reassignContext(stageId).then((r) => r.data),
    staleTime: 60_000,
  });

  const suggestMut = useMutation<ScreeningReassignSuggestionsResponse>({
    mutationFn: () => screeningApi.reassignSuggestions(stageId).then((r) => r.data),
    onSuccess: () => setHandled(new Set()),
  });

  if (contextQuery.isError) {
    return (
      <p
        role="status"
        className="mb-4 rounded-md border border-border bg-muted/30 px-3 py-2 text-xs text-muted-foreground"
      >
        Nie udało się sprawdzić, czy ta osoba przyszła z przepięcia — arkusz
        działa normalnie.{" "}
        <button
          type="button"
          className="font-medium text-primary hover:underline"
          onClick={() => void contextQuery.refetch()}
        >
          Spróbuj ponownie
        </button>
      </p>
    );
  }
  const context = contextQuery.data;
  if (!contextQuery.isSuccess || !context?.available || !context.source) return null;

  const source = context.source;
  const result = suggestMut.data;
  const questionById = new Map(questions.map((q) => [q.id, q]));
  const pending = (result?.suggestions ?? []).filter(
    (s) => questionById.has(s.question_id) && !handled.has(s.question_id),
  );

  const skipMissing = Boolean(methods.watch("skip_missing"));
  const emptyCount = questions.filter(
    (q) => !(methods.watch(`answers.${q.id}.response`) ?? "").trim(),
  ).length;

  const markHandled = (questionId: string) =>
    setHandled((prev) => new Set(prev).add(questionId));

  const fill = (suggestion: ScreeningReassignSuggestion, focus: boolean) => {
    const field = `answers.${suggestion.question_id}.response` as const;
    methods.setValue(field, suggestion.text, {
      shouldDirty: true,
      shouldValidate: true,
    });
    methods.setValue(`answers.${suggestion.question_id}.origin`, "reassign_suggested", {
      shouldDirty: true,
    });
    markHandled(suggestion.question_id);
    if (focus) {
      // Po wyrenderowaniu wartości — inaczej kursor ląduje w pustym polu.
      setTimeout(() => methods.setFocus(field), 0);
    }
  };

  const toggleSkip = (checked: boolean) => {
    methods.setValue("skip_missing", checked, {
      shouldDirty: true,
      shouldValidate: methods.formState.isSubmitted,
    });
  };

  return (
    <section
      aria-label="Podpowiedzi z poprzedniej rekrutacji"
      className="mb-5 space-y-3 rounded-lg border border-primary/30 bg-primary/5 p-4"
    >
      <div className="flex flex-wrap items-start gap-3">
        <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-foreground">
            Luna przygotuje odpowiedzi z poprzedniej rekrutacji
          </p>
          <p className="text-xs text-muted-foreground">
            Przepięcie z: {source.job_title}
            {source.date ? ` · ${formatDate(source.date)}` : ""}
            {context.previous_answers_count > 0
              ? ` · ${context.previous_answers_count} odp. ze screeningu`
              : " · bez odpowiedzi ze screeningu, Luna sprawdzi notatki"}
          </p>
        </div>
        {!readOnly && (
          <Button
            type="button"
            size="sm"
            variant="outline"
            loading={suggestMut.isPending}
            onClick={() => suggestMut.mutate()}
          >
            <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
            {result ? "Podpowiedz ponownie" : "Podpowiedz odpowiedzi"}
          </Button>
        )}
      </div>

      {suggestMut.isPending && (
        <p className="flex items-center gap-1.5 text-xs text-muted-foreground" role="status">
          <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" /> Luna czyta
          poprzedni screening i notatki…
        </p>
      )}
      {suggestMut.isError && (
        <p role="alert" className="text-xs text-destructive">
          {apiErrorMessage(
            suggestMut.error,
            "Luna nie odpowiedziała — uzupełnij odpowiedzi ręcznie.",
          )}
        </p>
      )}
      {result && !suggestMut.isPending && result.message && (
        <p role="status" className="text-xs text-muted-foreground">
          {result.message}
        </p>
      )}

      {pending.length > 0 && (
        <ul className="space-y-2" aria-label="Podpowiedzi odpowiedzi">
          {pending.map((suggestion) => {
            const question = questionById.get(suggestion.question_id)!;
            const index = questions.indexOf(question);
            const confidence = CONFIDENCE[suggestion.confidence] ?? CONFIDENCE.low;
            const hasAnswer = Boolean(
              (methods.watch(`answers.${suggestion.question_id}.response`) ?? "").trim(),
            );
            return (
              <li
                key={suggestion.question_id}
                className="space-y-2 rounded-md border border-border bg-card p-3"
              >
                <div className="flex items-start gap-2">
                  <Badge variant="soft" size="sm" className="shrink-0 font-mono">
                    Q{index + 1}
                  </Badge>
                  <p className="min-w-0 flex-1 text-xs font-medium text-foreground">
                    {question.question}
                  </p>
                  <Badge variant={confidence.variant} size="sm" className="shrink-0">
                    {confidence.label}
                  </Badge>
                </div>
                <p className="text-sm text-foreground">{suggestion.text}</p>
                <p className="text-[11px] text-muted-foreground">
                  {suggestion.source_kind === "answer"
                    ? "Z odpowiedzi w poprzednim screeningu"
                    : "Z notatki rekrutera"}
                  : „{suggestion.source_quote}”
                </p>
                {!readOnly && (
                  <div className="flex flex-wrap items-center gap-2">
                    <Button type="button" size="sm" onClick={() => fill(suggestion, false)}>
                      Przyjmij
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      onClick={() => fill(suggestion, true)}
                    >
                      Popraw
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      onClick={() => markHandled(suggestion.question_id)}
                    >
                      Odrzuć podpowiedź
                    </Button>
                    {hasAnswer && (
                      <span className="text-[11px] text-warning-muted-foreground">
                        Zastąpi obecną odpowiedź
                      </span>
                    )}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}

      {!readOnly && (
        <div className="space-y-2 border-t border-primary/20 pt-3">
          <label className="inline-flex cursor-pointer items-center gap-2 text-xs font-medium text-foreground">
            <Checkbox
              checked={skipMissing}
              onCheckedChange={(v) => toggleSkip(v === true)}
              aria-label="Pomiń brakujące — przepięcie"
            />
            <span>Pomiń brakujące — przepięcie</span>
          </label>
          {skipMissing && (
            <>
              <p className="text-[11px] text-muted-foreground">
                {emptyCount > 0
                  ? `${countPl(emptyCount, "pytanie", "pytania", "pytań")} bez odpowiedzi zapisze się jako pominięte. Pominięte odpowiedzi i ta notatka nie trafiają do klienta.`
                  : "Wszystkie pytania mają odpowiedź — nic nie zostanie pominięte."}
              </p>
              <FormField
                name="internal_note"
                label="Notatka wewnętrzna"
                description="Dlaczego pomijasz — widzi tylko zespół rekrutacji."
              >
                <TextareaField
                  name="internal_note"
                  rows={2}
                  placeholder="Np. te same pytania co w poprzedniej rekrutacji, klient zna kandydata"
                />
              </FormField>
            </>
          )}
        </div>
      )}
    </section>
  );
}
