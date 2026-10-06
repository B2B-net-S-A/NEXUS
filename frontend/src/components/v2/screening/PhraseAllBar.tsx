"use client";

/**
 * „Ułóż wszystkie w zdania (N)” nad arkuszem screeningu (0421). Jedno wywołanie
 * modelu dla odpowiedzi pisanych hasłami; propozycje pojawiają się pod każdym
 * pytaniem (`ScreeningFormFields`) i czekają na „Użyj zdania”.
 */

import type { UseFormReturn } from "react-hook-form";

import type { ScreeningQuestion } from "@/lib/api";
import { looksLikeKeywords } from "@/lib/recommendation-card";

import {
  type PhraseController,
  PhraseButton,
  PhraseLanguageToggle,
} from "./PhraseSuggestion";
import type { ScreeningFormValues } from "./ScreeningForm";

export function PhraseAllBar({
  phrase,
  questions,
  methods,
}: {
  phrase: PhraseController;
  questions: ScreeningQuestion[];
  methods: UseFormReturn<ScreeningFormValues>;
}) {
  const candidates = questions.filter((q) => {
    const response = methods.watch(`answers.${q.id}.response`) ?? "";
    const origin = methods.watch(`answers.${q.id}.origin`);
    return (
      origin !== "phrased" &&
      looksLikeKeywords(response) &&
      !phrase.results[q.id]
    );
  });
  const pending = questions.some((q) => phrase.isPending(q.id));
  return (
    <div className="mb-3 flex flex-wrap items-center gap-2 rounded-md border border-border bg-muted/30 px-3 py-2">
      <p className="mr-auto text-xs text-muted-foreground">
        Wpisz odpowiedzi hasłami — Luna ułoży z nich zdania do sprawdzenia.
      </p>
      <PhraseLanguageToggle
        idPrefix="screening-phrase-language"
        value={phrase.language}
        onChange={phrase.setLanguage}
      />
      <PhraseButton
        label={`Ułóż wszystkie w zdania (${candidates.length})`}
        disabled={!candidates.length}
        pending={pending}
        onClick={() =>
          void phrase.request(
            candidates.map((q) => ({
              key: q.id,
              keywords: methods.getValues(`answers.${q.id}.response`) ?? "",
              question: q.question,
            })),
          )
        }
      />
    </div>
  );
}
