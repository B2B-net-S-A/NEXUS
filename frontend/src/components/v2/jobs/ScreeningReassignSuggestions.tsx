"use client";

/**
 * Wcześniejsze odpowiedzi kandydata w arkuszu screeningu.
 *
 * Pipeline v4 (23.09.2026) dał podpowiedzi Luny osobom przepiętym z podobnej
 * rekrutacji; od 02.10.2026 dostaje je każda osoba, która odpowiadała już na
 * pytania screeningowe w innej rekrutacji — żeby nie pytać trzeci raz o to
 * samo. Serwer mówi, czy jest z czego podpowiadać (`GET
 * …/screening/reassign-context`, bez modelu). Luna rusza RAZ, po otwarciu
 * arkusza, i tylko gdy: są wcześniejsze rozmowy, patrzący może zapisać arkusz,
 * a zapisany arkusz ma pytanie bez odpowiedzi.
 *
 * Podpowiedź stoi POD pytaniem: skąd jest (data rozmowy, rekrutacja, klient),
 * dosłowna wcześniejsza odpowiedź i „Użyj tej odpowiedzi” (wpisuje ją w pole
 * z `origin: reassign_suggested`; poprawiona ręcznie wraca do `manual`).
 * Odpowiedź starsza niż 30 dni dostaje „dopytaj”. Nic nie zapisuje się samo —
 * zapis to dalej „Zapisz screening”. Awaria Luny to komunikat z „Spróbuj
 * ponownie”, nie blokada: arkusz działa ręcznie jak dotąd.
 *
 * „Pomiń brakujące — przepięcie” zostaje wyłącznie przy przepięciu; pominięte
 * odpowiedzi i notatka wewnętrzna NIGDY nie idą do klienta.
 *
 * Komponent musi stać WEWNĄTRZ `<Form>` arkusza — pole notatki korzysta
 * z kontekstu formularza. Pola arkusza renderuje jako `children`, którym
 * przekazuje treść pod pytaniem (`ScreeningFormFields.renderQuestionExtra`).
 */

import Link from "next/link";
import { useMemo, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import type { UseFormReturn } from "react-hook-form";
import { Loader2, Sparkles } from "lucide-react";

import {
  screeningApi,
  type ScreeningAnswers,
  type ScreeningQuestion,
  type ScreeningReassignSuggestion,
  type ScreeningReassignSuggestionsResponse,
} from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { FormField, TextareaField } from "@/components/v2/forms";
import type { ScreeningFormValues } from "@/components/v2/screening/ScreeningForm";
import { countPl, pluralPl } from "@/lib/plural-pl";
import { formatDate } from "@/lib/utils";

export const reassignContextQueryKey = (stageId: number) =>
  ["screening-reassign-context", stageId] as const;
export const screeningSuggestionsQueryKey = (stageId: number) =>
  ["screening-suggestions", stageId] as const;

/** Od ilu dni wcześniejsza odpowiedź dostaje dopisek „dopytaj”. */
export const STALE_ANSWER_DAYS = 30;

const LUNA_FAILED = "Luna nie odpowiedziała — uzupełnij odpowiedzi ręcznie.";

/** „to 7 tygodni temu — dopytaj” dla odpowiedzi starszej niż 30 dni; inaczej `null`. */
export function answerAgeNote(date: string | null | undefined, now: Date = new Date()): string | null {
  if (!date) return null;
  const then = new Date(date).getTime();
  if (Number.isNaN(then)) return null;
  const days = Math.floor((now.getTime() - then) / 86_400_000);
  if (days <= STALE_ANSWER_DAYS) return null;
  const weeks = Math.floor(days / 7);
  const age =
    weeks <= 8
      ? countPl(weeks, "tydzień", "tygodnie", "tygodni")
      : countPl(Math.floor(days / 30), "miesiąc", "miesiące", "miesięcy");
  return `to ${age} temu — dopytaj, czy nadal aktualne`;
}

/** „1 wcześniejszą rozmowę screeningową”, „2 wcześniejsze rozmowy screeningowe”… */
export function earlierConversationsLabel(count: number): string {
  return `${count} ${pluralPl(
    count,
    "wcześniejszą rozmowę screeningową",
    "wcześniejsze rozmowy screeningowe",
    "wcześniejszych rozmów screeningowych",
  )}`;
}

export interface ScreeningReassignSuggestionsProps {
  stageId: number;
  questions: ScreeningQuestion[];
  methods: UseFormReturn<ScreeningFormValues>;
  /**
   * Zapisany arkusz pary (z `GET …/screening`). Luna rusza tylko, gdy zostało
   * w nim pytanie bez odpowiedzi — przy wypełnionym arkuszu nie ma czego
   * podpowiadać.
   */
  saved: ScreeningAnswers | null | undefined;
  readOnly?: boolean;
  /** Pola arkusza; dostają treść do wstawienia pod pytaniem. */
  children: (
    renderQuestionExtra: (question: ScreeningQuestion, index: number) => ReactNode,
  ) => ReactNode;
}

export function ScreeningReassignSuggestions({
  stageId,
  questions,
  methods,
  saved,
  readOnly = false,
  children,
}: ScreeningReassignSuggestionsProps) {
  // Podpowiedzi, które rekruter już wykorzystał albo pominął — znikają spod pytań.
  const [handled, setHandled] = useState<Set<string>>(() => new Set());

  const contextQuery = useQuery({
    queryKey: reassignContextQueryKey(stageId),
    queryFn: () => screeningApi.reassignContext(stageId).then((r) => r.data),
    staleTime: 60_000,
  });
  const context = contextQuery.data;
  const available = contextQuery.isSuccess && Boolean(context?.available);
  // Serwer sprzed 02.10.2026 nie zna `kind` — rekrutacja źródłowa znaczy przepięcie.
  const kind = context?.kind ?? (context?.source ? "reassign" : null);

  const savedHasGap = useMemo(
    () =>
      questions.some(
        (q) => !(saved?.answers.find((a) => a.question_id === q.id)?.response ?? "").trim(),
      ),
    [questions, saved],
  );
  const wantSuggestions = available && !readOnly && saved !== undefined && savedHasGap && questions.length > 0;

  const suggestQuery = useQuery<ScreeningReassignSuggestionsResponse>({
    queryKey: screeningSuggestionsQueryKey(stageId),
    queryFn: () => screeningApi.reassignSuggestions(stageId).then((r) => r.data),
    enabled: wantSuggestions,
    // Jedno płatne wywołanie na arkusz — ponowne otwarcie czyta pamięć.
    staleTime: Infinity,
    retry: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
  const result = suggestQuery.data;
  const byQuestion = useMemo(
    () => new Map((result?.suggestions ?? []).map((s) => [s.question_id, s])),
    [result],
  );

  const applyHint = (suggestion: ScreeningReassignSuggestion) => {
    const field = `answers.${suggestion.question_id}.response` as const;
    methods.setValue(field, suggestion.text, { shouldDirty: true, shouldValidate: true });
    methods.setValue(`answers.${suggestion.question_id}.origin`, "reassign_suggested", {
      shouldDirty: true,
    });
    setHandled((prev) => new Set(prev).add(suggestion.question_id));
    // Kursor w polu — odpowiedź zwykle trzeba dopytać albo uzupełnić.
    setTimeout(() => methods.setFocus(field), 0);
  };

  const renderQuestionExtra = (question: ScreeningQuestion): ReactNode => {
    if (!available || readOnly) return null;
    const empty = !(methods.watch(`answers.${question.id}.response`) ?? "").trim();
    if (!empty || handled.has(question.id)) return null;
    const suggestion = byQuestion.get(question.id);
    if (!suggestion) {
      return suggestQuery.isSuccess && result?.available ? (
        <p className="text-xs text-muted-foreground">
          We wcześniejszych rozmowach nie ma odpowiedzi na to pytanie.
        </p>
      ) : null;
    }
    const source = suggestion.source ?? null;
    const stale = answerAgeNote(source?.date);
    const earlierQuestion = suggestion.source_question?.trim();
    return (
      <div
        data-testid="earlier-answer-hint"
        className="space-y-1.5 rounded-md border border-primary/30 bg-primary/5 p-2.5"
      >
        <p className="text-[11px] text-muted-foreground [overflow-wrap:anywhere]">
          {suggestion.source_kind === "answer" && source ? (
            <>
              Z rozmowy {source.date ? formatDate(source.date) : "wcześniejszej"} · {source.job_title}
              {source.client_name ? `, ${source.client_name}` : ""}
            </>
          ) : (
            "Z notatki rekrutera"
          )}
          {stale ? <span className="font-medium text-warning-muted-foreground"> — {stale}</span> : null}
        </p>
        {earlierQuestion && earlierQuestion !== question.question.trim() ? (
          <p className="text-[11px] text-muted-foreground [overflow-wrap:anywhere]">
            Pytanie wtedy: {earlierQuestion}
          </p>
        ) : null}
        {/* Cudzysłów tylko dla dosłownej odpowiedzi kandydata — z notatki to zdanie Luny. */}
        <p className="text-sm text-foreground [overflow-wrap:anywhere]">
          {suggestion.source_kind === "answer" ? `„${suggestion.text}”` : suggestion.text}
        </p>
        {suggestion.source_kind === "note" ? (
          <p className="text-[11px] text-muted-foreground [overflow-wrap:anywhere]">
            Fragment notatki: „{suggestion.source_quote}”
          </p>
        ) : null}
        <div className="flex flex-wrap items-center gap-2">
          <Button type="button" size="sm" onClick={() => applyHint(suggestion)}>
            Użyj tej odpowiedzi
          </Button>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            onClick={() => setHandled((prev) => new Set(prev).add(question.id))}
          >
            Pomiń
          </Button>
        </div>
      </div>
    );
  };

  if (contextQuery.isError) {
    return (
      <>
        <p
          role="status"
          className="mb-4 rounded-md border border-border bg-muted/30 px-3 py-2 text-xs text-muted-foreground"
        >
          Nie udało się sprawdzić wcześniejszych rozmów tej osoby — arkusz działa normalnie.{" "}
          <button
            type="button"
            className="font-medium text-primary hover:underline"
            onClick={() => void contextQuery.refetch()}
          >
            Spróbuj ponownie
          </button>
        </p>
        {children(() => null)}
      </>
    );
  }
  if (!available || !context) return <>{children(() => null)}</>;

  const source = context.source;
  const conversations = context.earlier_conversations ?? 0;
  const hints = (result?.suggestions ?? []).filter((s) => questions.some((q) => q.id === s.question_id));
  // Podpowiedzi, które jeszcze stoją pod pytaniami (nieużyte, niepominięte, pole puste).
  const openHints = hints.filter(
    (s) => !handled.has(s.question_id) && !(methods.watch(`answers.${s.question_id}.response`) ?? "").trim(),
  ).length;
  const failed = suggestQuery.isError || (result != null && !result.available);
  const profileLink =
    context.candidate_id != null ? (
      <Link
        href={`/candidates/${context.candidate_id}`}
        target="_blank"
        rel="noreferrer"
        className="font-medium text-primary hover:underline"
      >
        Wszystkie odpowiedzi w profilu
      </Link>
    ) : null;

  let state: ReactNode;
  if (readOnly) {
    state = <>Wcześniejsze odpowiedzi zobaczysz w profilu kandydata. {profileLink}</>;
  } else if (!savedHasGap) {
    state = <>Arkusz ma już odpowiedź na każde pytanie. {profileLink}</>;
  } else if (suggestQuery.isFetching && !result) {
    state = (
      <span className="inline-flex items-center gap-1.5">
        <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />
        Luna dopasowuje wcześniejsze odpowiedzi do pytań…
      </span>
    );
  } else if (failed) {
    state = (
      <>
        {suggestQuery.isError ? apiErrorMessage(suggestQuery.error, LUNA_FAILED) : (result?.message ?? LUNA_FAILED)}{" "}
        <button
          type="button"
          className="font-medium text-primary hover:underline"
          onClick={() => void suggestQuery.refetch()}
        >
          Spróbuj ponownie
        </button>
        {profileLink ? <> · {profileLink}</> : null}
      </>
    );
  } else if (result && openHints > 0) {
    state = (
      <>
        Pod {countPl(openHints, "pytaniem", "pytaniami", "pytaniami")} widzisz, co ta osoba już mówiła — nie trzeba
        pytać drugi raz. {profileLink}
      </>
    );
  } else if (result && hints.length > 0) {
    // Wszystkie podpowiedzi użyte albo pominięte — zostaje droga do profilu.
    state = profileLink;
  } else if (result) {
    state = (
      <>
        {result.message ?? "Wcześniejsze rozmowy nie odpowiadają na pytania tej rekrutacji."} {profileLink}
      </>
    );
  } else {
    state = profileLink;
  }

  const skipMissing = Boolean(methods.watch("skip_missing"));
  const emptyCount = questions.filter(
    (q) => !(methods.watch(`answers.${q.id}.response`) ?? "").trim(),
  ).length;
  const toggleSkip = (checked: boolean) => {
    methods.setValue("skip_missing", checked, {
      shouldDirty: true,
      shouldValidate: methods.formState.isSubmitted,
    });
  };

  return (
    <>
      <section
        aria-label="Wcześniejsze odpowiedzi kandydata"
        className="mb-5 space-y-3 rounded-lg border border-primary/30 bg-primary/5 p-3"
      >
        <div className="flex items-start gap-2">
          <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
          <div className="min-w-0 flex-1 space-y-0.5">
            <p className="text-sm font-medium text-foreground [overflow-wrap:anywhere]">
              {kind === "reassign" && source
                ? `Przepięcie z: ${source.job_title}${source.date ? ` · ${formatDate(source.date)}` : ""}`
                : `Ta osoba ma ${earlierConversationsLabel(conversations)}`}
            </p>
            <p role="status" className="text-xs text-muted-foreground">
              {state}
            </p>
          </div>
        </div>

        {kind === "reassign" && !readOnly && (
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
      {children(renderQuestionExtra)}
    </>
  );
}
