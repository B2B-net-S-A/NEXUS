"use client";

/**
 * Co edytor wymagań mówi pod wierszem, który nie jest słowem do szukania
 * (wariant A, decyzja Artura 13.10.2026, makieta P1:
 * https://claude.ai/artifact/8qx5WrueDSLHht7VezW2L5).
 *
 * Wyszukiwanie szuka słów dosłownie: „doświadczenie w przetargach” ma w CV
 * jedna osoba z 65 tys., „przetarg*” — 727. Zdanie, umiejętność miękka, język
 * i branża opisana zdaniem nie zostają więc słowem do szukania bez decyzji:
 * „zamień na słowa” albo „do rozmowy” (lista „Rekruter sprawdza w rozmowie”).
 */

import { Button } from "@/components/ui/button";
import { peopleCountLabel } from "@/components/champion/SearchRequirementsEditor";
import { useWordCounts } from "@/lib/requirement-rows-api";
import type { PhraseReading } from "@/lib/requirement-rows";

const DECISION_TEXT: Partial<Record<PhraseReading["kind"], (text: string) => string>> = {
  prose: (text) =>
    `„${text}” to zdanie — w CV szukamy słów, więc prawie nikogo nie znajdziemy. Szukać po słowach czy zostawić rekruterowi?`,
  domain: (text) =>
    `„${text}” to branża opisana zdaniem. Szukać po słowach czy zostawić rekruterowi?`,
  soft: (text) => `„${text}” to umiejętność miękka — CV jej nie potwierdzi. Sprawdzi ją rekruter.`,
  language: (text) =>
    `„${text}” — język i poziom sprawdza rekruter. Trafi do pola „Język”, a nie do wyszukiwania.`,
};

export function DecisionCallout({
  reading,
  countEnabled,
  onUseWord,
  onTalk,
}: {
  reading: PhraseReading;
  countEnabled: boolean;
  onUseWord: (word: string) => void;
  onTalk: () => void;
}) {
  const counts = useWordCounts(reading.suggestions, countEnabled);
  const text = DECISION_TEXT[reading.kind]?.(reading.text) ?? DECISION_TEXT.prose!(reading.text);
  return (
    <div
      role="note"
      className="flex flex-wrap items-center gap-2 rounded-md border border-warning/40 bg-warning-muted px-3 py-1.5 text-xs text-warning-muted-foreground"
      data-testid="requirement-row-decision"
    >
      <span className="min-w-0 flex-[1_1_16rem]">{text}</span>
      {reading.suggestions.map((word) => {
        const count = counts[word];
        return (
          <Button
            key={word}
            type="button"
            size="sm"
            variant="outline"
            onClick={() => onUseWord(word)}
            title={`Szukaj po „${word}” — zdanie przejdzie do rozmowy`}
          >
            {word}
            {typeof count === "number" ? (
              <span className="tabular-nums text-muted-foreground">
                {" "}
                · {peopleCountLabel(count)}
              </span>
            ) : null}
          </Button>
        );
      })}
      <Button type="button" size="sm" onClick={onTalk}>
        {reading.talk === "language" ? "Do pola „Język”" : "Do rozmowy"}
      </Button>
    </div>
  );
}

export function CommentCallout({
  reading,
  onSplit,
}: {
  reading: PhraseReading;
  onSplit: () => void;
}) {
  return (
    <div
      role="note"
      className="flex flex-wrap items-center gap-2 rounded-md border border-primary/20 bg-primary/5 px-3 py-1.5 text-xs text-foreground"
      data-testid="requirement-row-comment"
    >
      <span className="min-w-0 flex-[1_1_16rem]">
        Szukamy „{reading.keyword}”.{" "}
        {reading.talk_text
          ? `„${reading.comment}” przejdzie do „Rekruter sprawdza w rozmowie”.`
          : `Komentarz „${reading.comment}” pominiemy.`}
      </span>
      <Button type="button" size="sm" variant="outline" onClick={onSplit}>
        Rozdziel teraz
      </Button>
    </div>
  );
}

export function CityCallout({
  reading,
  onRemove,
  onKeep,
}: {
  reading: PhraseReading;
  onRemove: () => void;
  onKeep: () => void;
}) {
  return (
    <div
      role="note"
      className="flex flex-wrap items-center gap-2 rounded-md border border-warning/40 bg-warning-muted px-3 py-1.5 text-xs text-warning-muted-foreground"
      data-testid="requirement-row-city"
    >
      <span className="min-w-0 flex-[1_1_16rem]">
        „{reading.text}” to miasto. Lokalizację rekrutacji wpisz w polu „Lokalizacja” — porównujemy
        ją z miastem w profilu kandydata, a nie szukamy w CV.
      </span>
      <Button type="button" size="sm" variant="outline" onClick={onRemove}>
        Usuń wiersz
      </Button>
      <Button type="button" size="sm" variant="ghost" onClick={onKeep}>
        Zostaw
      </Button>
    </div>
  );
}

/**
 * Słowo „musi mieć”, które ma w bazie mniej niż `RARE_WORD_PEOPLE` osób
 * (pomiar 27.10.2026). Najczęściej to nazwa z requestu klienta, którą ludzie
 * opisują w CV inaczej („Crisis plans” 0, „Business Continuity” 773). Nic nie
 * blokuje: DL zamienia słowo, rozdziela sklejone warianty, przenosi wymaganie
 * do rozmowy albo zostawia, gdy rzadkość jest prawdziwa (niszowa technologia).
 */
export function RareWordCallout({
  word,
  count,
  split,
  countEnabled,
  onSplit,
  onTalk,
  onKeep,
}: {
  word: string;
  count: number;
  /** Warianty sklejone w słowie („SoapUI/ReadyAPI”), gdy są. */
  split: readonly string[] | null;
  countEnabled: boolean;
  onSplit: (parts: string[]) => void;
  onTalk: () => void;
  onKeep: () => void;
}) {
  const counts = useWordCounts(split ?? [], countEnabled && split != null);
  const splitTotal = (split ?? []).reduce((sum, part) => {
    const n = counts[part];
    return typeof n === "number" ? Math.max(sum, n) : sum;
  }, 0);
  const people = count === 0 ? "nikt w bazie" : `tylko ${peopleCountLabel(count)} w bazie`;
  return (
    <div
      role="note"
      className="flex flex-wrap items-center gap-2 rounded-md border border-warning/40 bg-warning-muted px-3 py-1.5 text-xs text-warning-muted-foreground"
      data-testid="requirement-row-rare"
    >
      <span className="min-w-0 flex-[1_1_16rem]">
        „{word}” — {people}. Tak tego w CV nie piszą: wpisz słowo, którym ludzie to opisują
        (technologię, narzędzie), albo zostaw rekruterowi do rozmowy.
      </span>
      {split && splitTotal > count ? (
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={() => onSplit([...split])}
          title="Wystarczy jedno z tych słów"
        >
          Rozdziel: {split.join(" lub ")}
          <span className="tabular-nums text-muted-foreground">
            {" "}
            · co najmniej {peopleCountLabel(splitTotal)}
          </span>
        </Button>
      ) : null}
      <Button type="button" size="sm" onClick={onTalk}>
        Do rozmowy
      </Button>
      <Button type="button" size="sm" variant="ghost" onClick={onKeep}>
        Zostaw
      </Button>
    </div>
  );
}
