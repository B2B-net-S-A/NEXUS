"use client";

/**
 * Pod wierszem wymagań: słowo, którego słownik nie zna (06.11.2026, makieta S2).
 *
 * Słowo spoza słownika dopasowanie i bramka must-have szukają dosłownie, więc
 * „mikroserwisy” nie znajduje 2 327 osób z „Microservices”. Delivery Lead
 * dopisuje warianty do SWOJEGO wiersza; słownik całej aplikacji zmienia tylko
 * Head of Recruitment albo admin (`canCurate`, trasa ma własną bramkę).
 * „Zostaw” chowa podpowiedź na tym ekranie.
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { skillsAdminApi } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import {
  curateActionLabel,
  hintMessage,
  missingWords,
  rowActionLabel,
  type DictionaryHint,
} from "@/lib/dictionary-hints";
import { dictionaryHintsKey } from "@/lib/requirement-rows-api";

export function DictionaryHintCallout({
  hint,
  rowWords,
  canCurate,
  onAddWords,
  onKeep,
}: {
  hint: DictionaryHint;
  rowWords: readonly string[];
  canCurate: boolean;
  onAddWords: (words: string[]) => void;
  onKeep: () => void;
}) {
  const queryClient = useQueryClient();
  const curate = useMutation({
    mutationFn: () => skillsAdminApi.acceptProposal(hint.proposal_id as number),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: dictionaryHintsKey });
      void queryClient.invalidateQueries({ queryKey: ["skills-admin"] });
    },
  });
  const missing = missingWords(rowWords, hint);
  const rowLabel = rowActionLabel(hint, missing);
  const curateLabel = canCurate ? curateActionLabel(hint) : null;
  // Wiersz ma już wszystkie warianty, a słownika ta osoba nie zmienia: nic do zrobienia.
  if (!rowLabel && !curateLabel && !curate.isError) return null;
  return (
    <div
      role="note"
      data-testid="dictionary-hint"
      className="flex flex-wrap items-center gap-2 rounded-md border border-warning/40 bg-warning-muted px-3 py-1.5 text-xs text-warning-muted-foreground"
    >
      <span className="min-w-0 flex-[1_1_16rem]">{hintMessage(hint)}</span>
      {rowLabel ? (
        <Button type="button" size="sm" variant="outline" onClick={() => onAddWords(missing)}>
          {rowLabel}
        </Button>
      ) : null}
      {curateLabel ? (
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={curate.isPending || curate.isSuccess}
          onClick={() => curate.mutate()}
        >
          {curate.isSuccess ? "Dodano do słownika" : curateLabel}
        </Button>
      ) : null}
      <Button type="button" size="sm" variant="ghost" onClick={onKeep}>
        Zostaw
      </Button>
      {curate.isError ? (
        <p className="basis-full text-destructive" role="alert">
          {apiErrorMessage(curate.error, "Nie udało się zmienić słownika")}
        </p>
      ) : null}
    </div>
  );
}
