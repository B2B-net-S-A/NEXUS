"use client";

/**
 * „To słowo do szukania?” pod listą „Rekruter sprawdza w rozmowie”
 * (27.10.2026). Lista nie bierze udziału w wyszukiwaniu, więc technologia
 * wpisana tylko tam — 663525: „Alteryx (good/advanced)”, w wierszach „Data
 * handling” i „Reporting” — nie trafia do „Szukaj w bazie” ani do propozycji
 * AI. Technologię rozpoznaje serwer, tym samym odczytem co słowa wierszy
 * (`readings`); pozycja, której słowo już jest w wierszach, podpowiedzi nie ma.
 */

import { Button } from "@/components/ui/button";
import { peopleCountLabel } from "@/components/champion/SearchRequirementsEditor";
import type { ExperienceItem } from "@/lib/api";
import {
  canAddRow,
  talkItemTexts,
  talkSearchWords,
  type RequirementRowForm,
  type TalkSearchWord,
} from "@/lib/requirement-rows";
import { useTalkItemReadings, useWordCounts } from "@/lib/requirement-rows-api";

export interface TalkSearchWordHintsProps {
  items: readonly ExperienceItem[];
  rows: readonly RequirementRowForm[];
  onAdd: (hint: TalkSearchWord) => void;
  disabled?: boolean;
  enabled?: boolean;
}

export function TalkSearchWordHints({
  items,
  rows,
  onAdd,
  disabled = false,
  enabled = true,
}: TalkSearchWordHintsProps) {
  const readings = useTalkItemReadings(talkItemTexts(items), { enabled });
  const hints = readings ? talkSearchWords(items, readings, rows) : [];
  const counts = useWordCounts(
    hints.map((hint) => hint.words[0]),
    enabled && hints.length > 0,
  );
  if (hints.length === 0) return null;
  const full = !canAddRow(rows);
  return (
    <div className="flex flex-col gap-1.5" data-testid="talk-search-word-hints">
      {hints.map((hint) => {
        const word = hint.words.join(" lub ");
        const count = counts[hint.words[0]];
        return (
          <div
            key={hint.item.name}
            role="note"
            className="flex flex-wrap items-center gap-2 rounded-md border border-primary/20 bg-primary/5 px-3 py-1.5 text-xs text-foreground"
            data-testid="talk-search-word-hint"
          >
            <span className="min-w-0 flex-[1_1_16rem]">
              <strong className="font-medium">To słowo do szukania?</strong> „{word}” jest tylko
              na liście do rozmowy — wyszukiwanie w bazie go nie użyje.
              {typeof count === "number" ? (
                <span className="tabular-nums text-muted-foreground">
                  {" "}
                  W bazie: {peopleCountLabel(count)}.
                </span>
              ) : null}
            </span>
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={disabled || full}
              onClick={() => onAdd(hint)}
              title={
                full
                  ? "Lista słów do szukania jest pełna"
                  : hint.keepItem
                    ? `„${hint.item.name}” zostaje na liście do rozmowy`
                    : undefined
              }
            >
              {hint.keepItem ? "Dodaj do słów do szukania" : "Przenieś do słów do szukania"}
            </Button>
          </div>
        );
      })}
    </div>
  );
}
