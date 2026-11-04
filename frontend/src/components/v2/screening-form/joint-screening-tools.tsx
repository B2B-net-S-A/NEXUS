"use client";

/**
 * Narzędzia pojedynczego formularza screeningu w formularzu wspólnym
 * („Screening dla”, 15.10.2026 — „Znalezione” po PR #2236):
 *
 * - wcześniejsze odpowiedzi (Luna, `…/screening/reassign-suggestions`) per
 *   para — pod wspólnym pytaniem podpowiedź z dowolnej rekrutacji, która ją ma;
 *   „Użyj tej odpowiedzi” wpisuje ją z pochodzeniem `reassign_suggested`;
 * - „Pomiń brakujące” per rekrutacja — serwer mówi, czy wolno
 *   (`reassign-context.skip_reason`), notatka wewnętrzna tej rekrutacji;
 * - „Ułóż w zdanie” — zdania z haseł w języku CV klienta danej rekrutacji.
 *
 * Wszystko jak w pojedynczym formularzu: nic nie zapisuje się samo, awaria
 * Luny jest komunikatem z „Spróbuj ponownie”, a formularz działa ręcznie.
 */

import { useCallback, useMemo, useRef, useState } from "react";
import { useQueries } from "@tanstack/react-query";
import { Loader2, Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  SKIP_MISSING_LABEL,
  answerAgeNote,
  earlierConversationsLabel,
  reassignContextQueryKey,
  screeningSuggestionsQueryKey,
} from "@/components/v2/jobs/ScreeningReassignSuggestions";
import {
  screeningApi,
  type ScreeningReassignContext,
  type ScreeningReassignSuggestion,
  type ScreeningReassignSuggestionsResponse,
  type ScreeningSkipReason,
} from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import {
  recommendationCardsApi,
  type PhraseLanguage,
  type PhraseRequestItem,
} from "@/lib/api/recommendationCards";
import type { PhraseSuggestionState } from "@/components/v2/screening/PhraseSuggestion";
import { formQuestions } from "@/lib/screening-form";
import type { JointGroup, JointPair } from "@/lib/joint-screening";
import { formatDate } from "@/lib/utils";

const LUNA_FAILED = "Luna nie odpowiedziała — uzupełnij odpowiedzi ręcznie.";

// ── Wcześniejsze odpowiedzi i „Pomiń brakujące” ─────────────────────────────

export interface EarlierSuggestion {
  pair: JointPair;
  suggestion: ScreeningReassignSuggestion;
}

export interface JointEarlierAnswers {
  /** Podpowiedź dla grupy pytań — z pierwszej rekrutacji, która ją ma. */
  suggestionFor: (group: JointGroup) => EarlierSuggestion | null;
  /** Rekrutacje, w których wolno pominąć pytania bez odpowiedzi, z powodem. */
  skipReasons: ReadonlyMap<number, ScreeningSkipReason>;
  /** Najwięcej wcześniejszych rozmów wśród par (osoba ta sama). */
  conversations: number;
  available: boolean;
  loading: boolean;
  /** Komunikat awarii Luny albo `null`. */
  failure: string | null;
  contextFailed: boolean;
  retry: () => void;
}

function skipReasonOf(context: ScreeningReassignContext | undefined): ScreeningSkipReason | null {
  if (!context) return null;
  // Serwer sprzed 12.10.2026 nie zna `skip_reason` — wtedy tylko przepięcie.
  const kind = context.kind ?? (context.source ? "reassign" : null);
  return context.skip_reason ?? (context.available && kind === "reassign" ? "reassign" : null);
}

export function useJointEarlierAnswers(pairs: readonly JointPair[], enabled: boolean): JointEarlierAnswers {
  const staged = pairs.filter((p) => p.state.stage_id != null);
  const contexts = useQueries({
    queries: staged.map((pair) => ({
      queryKey: reassignContextQueryKey(pair.state.stage_id!),
      queryFn: () => screeningApi.reassignContext(pair.state.stage_id!).then((r) => r.data),
      staleTime: 60_000,
      enabled,
    })),
  });
  // Luna tylko dla par z wcześniejszymi rozmowami i pytaniem bez zapisanej odpowiedzi.
  const wanted = staged.map((pair, i) => {
    const context = contexts[i]?.data;
    const saved = pair.state.sheet?.answers ?? [];
    const gap = formQuestions(pair.state).some(
      (q) => !(saved.find((a) => a.question_id === q.id)?.response ?? "").trim(),
    );
    return enabled && Boolean(context?.available) && gap;
  });
  const suggestions = useQueries({
    queries: staged.map((pair, i) => ({
      queryKey: screeningSuggestionsQueryKey(pair.state.stage_id!),
      queryFn: () =>
        screeningApi.reassignSuggestions(pair.state.stage_id!).then((r) => r.data as ScreeningReassignSuggestionsResponse),
      enabled: wanted[i],
      // Jedno płatne wywołanie na parę — ponowne otwarcie czyta pamięć.
      staleTime: Infinity,
      retry: false,
      refetchOnWindowFocus: false,
      refetchOnReconnect: false,
    })),
  });

  const byPair = new Map<number, Map<string, ScreeningReassignSuggestion>>();
  staged.forEach((pair, i) => {
    // Pamięć zapytań może trzymać podpowiedzi z dawnej wizyty — liczą się tylko,
    // gdy serwer dziś mówi, że są wcześniejsze rozmowy.
    const result = suggestions[i]?.data;
    if (!contexts[i]?.data?.available || !result?.available) return;
    byPair.set(pair.jobId, new Map(result.suggestions.map((s) => [s.question_id, s])));
  });
  const skipReasons = new Map<number, ScreeningSkipReason>();
  staged.forEach((pair, i) => {
    const reason = skipReasonOf(contexts[i]?.data);
    if (reason) skipReasons.set(pair.jobId, reason);
  });
  const failedIndex = suggestions.findIndex(
    (q, i) => wanted[i] && (q.isError || (q.data != null && !q.data.available)),
  );
  const failedQuery = failedIndex >= 0 ? suggestions[failedIndex] : null;

  return {
    suggestionFor: (group) => {
      for (const member of group.members) {
        const suggestion = byPair.get(member.jobId)?.get(member.questionId);
        const pair = pairs.find((p) => p.jobId === member.jobId);
        if (suggestion && pair) return { pair, suggestion };
      }
      return null;
    },
    skipReasons,
    conversations: Math.max(0, ...contexts.map((q) => q.data?.earlier_conversations ?? 0)),
    available: contexts.some((q) => Boolean(q.data?.available)),
    loading: suggestions.some((q, i) => wanted[i] && q.isFetching && !q.data),
    failure: failedQuery
      ? failedQuery.isError
        ? apiErrorMessage(failedQuery.error, LUNA_FAILED)
        : (failedQuery.data?.message ?? LUNA_FAILED)
      : null,
    contextFailed: contexts.some((q) => q.isError),
    retry: () => {
      contexts.forEach((q) => q.isError && void q.refetch());
      suggestions.forEach((q, i) => wanted[i] && void q.refetch());
    },
  };
}

/** Pasek nad pytaniami: skąd podpowiedzi, „Użyj wszystkich odpowiedzi (N)”. */
export function EarlierAnswersBar({
  earlier,
  open,
  onUseAll,
}: {
  earlier: JointEarlierAnswers;
  /** Ile podpowiedzi stoi jeszcze pod pustymi pytaniami. */
  open: number;
  onUseAll: () => void;
}) {
  if (earlier.contextFailed) {
    return (
      <p role="status" className="rounded-md border border-border bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
        Nie udało się sprawdzić wcześniejszych rozmów tej osoby — formularz działa normalnie.{" "}
        <button type="button" className="font-medium text-primary hover:underline" onClick={earlier.retry}>
          Spróbuj ponownie
        </button>
      </p>
    );
  }
  if (!earlier.available) return null;
  let state;
  if (earlier.loading) {
    state = (
      <span className="inline-flex items-center gap-1.5">
        <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />
        Luna dopasowuje wcześniejsze odpowiedzi do pytań…
      </span>
    );
  } else if (earlier.failure) {
    state = (
      <>
        {earlier.failure}{" "}
        <button type="button" className="font-medium text-primary hover:underline" onClick={earlier.retry}>
          Spróbuj ponownie
        </button>
      </>
    );
  } else if (open > 0) {
    state = "Pod pytaniami widzisz, co ta osoba już mówiła — nie trzeba pytać drugi raz.";
  } else {
    state = "Wcześniejsze rozmowy nie mają już nic do podpowiedzenia w pustych pytaniach.";
  }
  return (
    <section
      aria-label="Wcześniejsze odpowiedzi kandydata"
      className="space-y-1.5 rounded-lg border border-primary/30 bg-primary/5 p-3"
    >
      <p className="flex items-start gap-2 text-sm font-medium text-foreground">
        <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
        Ta osoba ma {earlierConversationsLabel(Math.max(1, earlier.conversations))}
      </p>
      <p role="status" className="text-xs text-muted-foreground">
        {state}
      </p>
      {!earlier.loading && !earlier.failure && open > 1 ? (
        <Button type="button" size="sm" variant="outline" onClick={onUseAll}>
          Użyj wszystkich odpowiedzi ({open})
        </Button>
      ) : null}
    </section>
  );
}

/** Podpowiedź pod pustym pytaniem — „Użyj tej odpowiedzi” albo „Pomiń”. */
export function EarlierAnswerHint({
  hint,
  question,
  onUse,
  onSkip,
}: {
  hint: EarlierSuggestion;
  question: string;
  onUse: () => void;
  onSkip: () => void;
}) {
  const { suggestion } = hint;
  const source = suggestion.source ?? null;
  const stale = answerAgeNote(source?.date);
  const earlierQuestion = suggestion.source_question?.trim();
  return (
    <div data-testid="earlier-answer-hint" className="space-y-1.5 rounded-md border border-primary/30 bg-primary/5 p-2.5">
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
      {earlierQuestion && earlierQuestion !== question.trim() ? (
        <p className="text-[11px] text-muted-foreground [overflow-wrap:anywhere]">Pytanie wtedy: {earlierQuestion}</p>
      ) : null}
      <p className="text-sm text-foreground [overflow-wrap:anywhere]">
        {suggestion.source_kind === "answer" ? `„${suggestion.text}”` : suggestion.text}
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <Button type="button" size="sm" onClick={onUse}>
          Użyj tej odpowiedzi
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={onSkip}>
          Pomiń
        </Button>
      </div>
    </div>
  );
}

// ── „Ułóż w zdanie” ─────────────────────────────────────────────────────────

export interface JointPhrase {
  language: PhraseLanguage;
  setLanguage: (language: PhraseLanguage) => void;
  results: Record<string, PhraseSuggestionState>;
  isPending: (key: string) => boolean;
  /** Zdania z haseł w kontekście jednej rekrutacji (język CV jej klienta). */
  request: (jobId: number, items: PhraseRequestItem[]) => Promise<void>;
  dismiss: (key: string) => void;
  error: string | null;
}

/**
 * Jak `usePhraseSuggestions`, ale dla kilku rekrutacji: wywołanie idzie
 * w kontekście rekrutacji pola, a błąd stoi w formularzu (bez dymka).
 */
export function useJointPhrase(candidateId: number, pairs: readonly JointPair[]): JointPhrase {
  const anchor = pairs.find((p) => p.anchor) ?? pairs[0];
  const [picked, setPicked] = useState<PhraseLanguage | null>(null);
  const [results, setResults] = useState<Record<string, PhraseSuggestionState>>({});
  const [pending, setPending] = useState<ReadonlySet<string>>(() => new Set());
  const [error, setError] = useState<string | null>(null);
  const pairsRef = useRef(pairs);
  pairsRef.current = pairs;
  const language: PhraseLanguage = picked ?? anchor?.state.phrase_language ?? "pl";

  const request = useCallback(
    async (jobId: number, items: PhraseRequestItem[]) => {
      const clean = items.filter((item) => item.keywords.trim());
      if (!clean.length) return;
      const keys = clean.map((item) => item.key);
      setError(null);
      setPending((prev) => new Set([...prev, ...keys]));
      try {
        const pairLanguage = pairsRef.current.find((p) => p.jobId === jobId)?.state.phrase_language;
        const result = await recommendationCardsApi.phrase(candidateId, jobId, clean, picked ?? pairLanguage ?? "pl");
        if (!result.available) {
          setError(result.message ?? "Luna nie odpowiedziała — zostaw hasła albo spróbuj ponownie.");
          return;
        }
        const byKey = new Map(clean.map((item) => [item.key, item.keywords]));
        setResults((prev) => {
          const next = { ...prev };
          for (const item of result.items) next[item.key] = { ...item, keywords: byKey.get(item.key) ?? "" };
          return next;
        });
      } catch (err) {
        setError(apiErrorMessage(err, "Nie udało się ułożyć zdania. Spróbuj ponownie."));
      } finally {
        setPending((prev) => {
          const next = new Set(prev);
          for (const key of keys) next.delete(key);
          return next;
        });
      }
    },
    [candidateId, picked],
  );

  const dismiss = useCallback((key: string) => {
    setResults((prev) => {
      if (!(key in prev)) return prev;
      const next = { ...prev };
      delete next[key];
      return next;
    });
  }, []);

  return useMemo(
    () => ({
      language,
      setLanguage: setPicked,
      results,
      isPending: (key: string) => pending.has(key),
      request,
      dismiss,
      error,
    }),
    [language, results, pending, request, dismiss, error],
  );
}

export { SKIP_MISSING_LABEL };
