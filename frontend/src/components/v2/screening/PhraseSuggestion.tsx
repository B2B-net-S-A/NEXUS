"use client";

/**
 * „Ułóż w zdanie” (0421, decyzje D3–D4 z 06.10.2026): hasła rekrutera w pełnym
 * zdaniu dla Delivery Leada i klienta. Luna tylko przeformułowuje — serwer
 * odrzuca zdanie z liczbą, datą albo nazwą spoza haseł (`problem`). Nic nie
 * zapisuje się samo: rekruter klika „Użyj zdania”, „Popraw” albo „Zostaw hasła”.
 *
 * `PhraseProposal` i `PhraseButton` są prezentacyjne (harness renderuje je bez
 * zapytań); `usePhraseSuggestions` dokłada wywołanie API.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useToast } from "@/components/Toast";
import { apiErrorMessage } from "@/lib/api-error";
import {
  type PhraseLanguage,
  type PhraseRequestItem,
  type PhraseResultItem,
  recommendationCardsApi,
} from "@/lib/api/recommendationCards";

export interface PhraseSuggestionState extends PhraseResultItem {
  /** Hasła, z których powstało zdanie (zapisywane obok zdania). */
  keywords: string;
}

export interface PhraseController {
  language: PhraseLanguage;
  setLanguage: (language: PhraseLanguage) => void;
  results: Record<string, PhraseSuggestionState>;
  isPending: (key: string) => boolean;
  /** Ułóż zdania dla podanych pozycji (jedno wywołanie modelu). */
  request: (items: PhraseRequestItem[]) => Promise<void>;
  dismiss: (key: string) => void;
}

export function usePhraseSuggestions({
  candidateId,
  jobId,
  defaultLanguage,
}: {
  candidateId: number;
  jobId: number;
  /** Język CV klienta z karty — dochodzi po wczytaniu karty. */
  defaultLanguage?: PhraseLanguage | null;
}): PhraseController {
  const { showError } = useToast();
  const [picked, setPicked] = useState<PhraseLanguage | null>(null);
  const language = picked ?? defaultLanguage ?? "pl";
  const [results, setResults] = useState<Record<string, PhraseSuggestionState>>(
    {},
  );
  const [pending, setPending] = useState<ReadonlySet<string>>(new Set());

  const scopeRef = useRef("");
  scopeRef.current = `${candidateId}:${jobId}`;

  // Inna osoba albo rekrutacja = propozycje poprzedniej nie mają tu sensu.
  useEffect(() => {
    setResults({});
    setPicked(null);
  }, [candidateId, jobId]);

  const request = useCallback(
    async (items: PhraseRequestItem[]) => {
      const clean = items.filter((item) => item.keywords.trim());
      if (!clean.length) return;
      const keys = clean.map((item) => item.key);
      const scope = `${candidateId}:${jobId}`;
      setPending((prev) => new Set([...prev, ...keys]));
      try {
        const result = await recommendationCardsApi.phrase(
          candidateId,
          jobId,
          clean,
          language,
        );
        // Inna osoba w trakcie odczytu — zdania osoby A nie trafią do arkusza B.
        if (scopeRef.current !== scope) return;
        if (!result.available) {
          showError(
            result.message ??
              "Luna nie odpowiedziała — zostaw hasła albo spróbuj ponownie.",
          );
          return;
        }
        const byKey = new Map(clean.map((item) => [item.key, item.keywords]));
        setResults((prev) => {
          const next = { ...prev };
          for (const item of result.items) {
            next[item.key] = { ...item, keywords: byKey.get(item.key) ?? "" };
          }
          return next;
        });
      } catch (err) {
        showError(
          apiErrorMessage(
            err,
            "Nie udało się ułożyć zdania. Spróbuj ponownie.",
          ),
        );
      } finally {
        setPending((prev) => {
          const next = new Set(prev);
          for (const key of keys) next.delete(key);
          return next;
        });
      }
    },
    [candidateId, jobId, language, showError],
  );

  const dismiss = useCallback((key: string) => {
    setResults((prev) => {
      if (!(key in prev)) return prev;
      const next = { ...prev };
      delete next[key];
      return next;
    });
  }, []);

  return {
    language,
    setLanguage: setPicked,
    results,
    isPending: (key) => pending.has(key),
    request,
    dismiss,
  };
}

export function PhraseButton({
  disabled,
  pending,
  onClick,
  label = "Ułóż w zdanie",
}: {
  disabled?: boolean;
  pending?: boolean;
  onClick: () => void;
  label?: string;
}) {
  return (
    <Button
      type="button"
      size="sm"
      variant="outline"
      disabled={disabled || pending}
      onClick={onClick}
    >
      {pending ? (
        <Loader2 className="size-3.5 animate-spin" aria-hidden />
      ) : (
        <Sparkles className="size-3.5" aria-hidden />
      )}
      {label}
    </Button>
  );
}

/** Przełącznik języka zdań — domyślnie język CV klienta (D3). */
export function PhraseLanguageToggle({
  value,
  onChange,
  idPrefix,
}: {
  value: PhraseLanguage;
  onChange: (language: PhraseLanguage) => void;
  idPrefix: string;
}) {
  return (
    <div
      role="radiogroup"
      aria-label="Język zdań"
      className="inline-flex rounded-md border border-border p-0.5"
    >
      {(["pl", "en"] as const).map((language) => (
        <button
          key={language}
          id={`${idPrefix}-${language}`}
          type="button"
          role="radio"
          aria-checked={value === language}
          onClick={() => onChange(language)}
          className={
            value === language
              ? "rounded px-2 py-0.5 text-[11px] font-semibold text-primary-foreground bg-primary"
              : "rounded px-2 py-0.5 text-[11px] text-muted-foreground hover:text-foreground"
          }
        >
          {language.toUpperCase()}
        </button>
      ))}
    </div>
  );
}

export function PhraseProposal({
  suggestion,
  onUse,
  onEdit,
  onKeep,
}: {
  suggestion: PhraseSuggestionState;
  onUse: (sentence: string) => void;
  onEdit: (sentence: string) => void;
  onKeep: () => void;
}) {
  if (!suggestion.sentence) {
    return (
      <div
        role="status"
        className="space-y-1.5 rounded-md bg-warning-muted p-2.5 text-xs text-foreground"
      >
        <p>
          {suggestion.problem
            ? `Zdanie zawierało coś, czego nie ma w hasłach: „${suggestion.problem}”. Popraw hasła albo zostaw je tak, jak są.`
            : "Luna nie ułożyła zdania z tych haseł — zostaw je tak, jak są."}
        </p>
        <Button type="button" size="sm" variant="ghost" onClick={onKeep}>
          Zamknij
        </Button>
      </div>
    );
  }
  const sentence = suggestion.sentence;
  return (
    <div
      data-testid="phrase-proposal"
      className="space-y-2 rounded-md border-l-2 border-primary bg-primary/5 p-2.5 text-sm"
    >
      <p className="text-[11px] font-semibold uppercase tracking-wide text-primary">
        Propozycja zdania
      </p>
      <p className="whitespace-pre-line text-foreground">{sentence}</p>
      <div className="flex flex-wrap gap-2">
        <Button type="button" size="sm" onClick={() => onUse(sentence)}>
          Użyj zdania
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={() => onEdit(sentence)}
        >
          Popraw
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={onKeep}>
          Zostaw hasła
        </Button>
      </div>
    </div>
  );
}
