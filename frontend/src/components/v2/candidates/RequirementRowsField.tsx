"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Lightbulb, Plus, X } from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { ChipField, type ChipFieldSuggest } from "@/components/v2/filters/AdvancedSearchPopover";
import {
  MAX_REQUIREMENT_ROWS,
  experienceRangeLabel,
  foldWord,
  hintKey,
  keywordHints,
  splitWordInRow,
  withoutWord,
  type ExperienceRange,
  type KeywordHint,
} from "@/lib/keyword-requirements";

/** Miasto podpowiadamy dopiero od tylu mieszkańców — „Kotlin” to wieś. */
const CITY_MIN_POPULATION = 20_000;

interface PlaceItem {
  name: string;
  voivodeship: string;
  population: number;
}

const cityCache = new Map<string, string | null>();

/** Klucz nazwy jak `pl_places.place_key` (bez polskich znaków, myślnik = spacja). */
function placeKey(value: string): string {
  return foldWord(value.split(",")[0]).replace(/[\s-]+/g, " ").trim();
}

/**
 * Słowa, które są nazwą większego polskiego miasta (spis `pl_places` przez
 * `/api/candidates/places/suggest`, bez bazy). Pamięć na słowo, bez
 * react-query — pole żyje też w oknach bez `QueryClientProvider`.
 */
function useCityWords(words: readonly string[], enabled: boolean): Map<string, string> {
  const [found, setFound] = useState<Map<string, string>>(new Map());
  const key = words.map(placeKey).sort().join("|");
  useEffect(() => {
    if (!enabled) return;
    let alive = true;
    const pending = words.filter((w) => placeKey(w).length >= 3 && !cityCache.has(placeKey(w)));
    const publish = () => {
      if (!alive) return;
      const next = new Map<string, string>();
      for (const w of words) {
        const city = cityCache.get(placeKey(w));
        if (city) next.set(w, city);
      }
      setFound(next);
    };
    if (pending.length === 0) {
      publish();
      return;
    }
    Promise.all(
      pending.map((word) =>
        api
          .get<{ items?: PlaceItem[] }>("/api/candidates/places/suggest", {
            params: { q: word, limit: 3 },
          })
          .then(({ data }) => {
            const hit = (data?.items ?? []).find(
              (p) => placeKey(p.name) === placeKey(word) && p.population >= CITY_MIN_POPULATION,
            );
            cityCache.set(placeKey(word), hit ? hit.name : null);
          })
          .catch(() => {
            // Podpowiedź to dodatek — awaria nic nie pokazuje i nic nie psuje.
          }),
      ),
    ).then(publish);
    return () => {
      alive = false;
    };
    // `key` streszcza listę słów; sama tablica zmienia tożsamość co render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, enabled]);
  return found;
}

export interface RequirementRowsFieldProps {
  /** Wiersze w stanie roboczym — pusty wiersz to świeżo dodany. */
  rows: string[][];
  onRowsChange: (rows: string[][]) => void;
  exclude: string[];
  onExcludeChange: (next: string[]) => void;
  suggest?: ChipFieldSuggest;
  /** Enter w pustym polu = „Szukaj”. */
  onSubmitEmpty?: () => void;
  /** „Ustaw lokalizację” przy słowie-mieście; bez niego podpowiedzi o mieście nie ma. */
  onUseLocation?: (city: string) => void;
  /** „Użyj filtra stażu” przy „senior/junior…”; bez niego podpowiedzi o stażu nie ma. */
  onUseExperience?: (range: ExperienceRange) => void;
  /** Wymagane i puste (bramka przekazania rekrutacji). */
  invalid?: boolean;
  className?: string;
}

/**
 * Słowa kluczowe jako lista wymagań (makiety 25.09.2026): wiersz = jedno
 * wymaganie, słowa w wierszu to warianty („lub”), wiersze łączy „i”, na dole
 * „Wyklucz”. Pod wierszem podpowiedzi przy typowych pomyłkach — nic nie
 * zmienia się samo, każda ma przycisk i „Zostaw”.
 */
export function RequirementRowsField({
  rows,
  onRowsChange,
  exclude,
  onExcludeChange,
  suggest,
  onSubmitEmpty,
  onUseLocation,
  onUseExperience,
  invalid = false,
  className,
}: RequirementRowsFieldProps) {
  // Pusta lista = jeden pusty wiersz do pisania (nie zapisujemy go w stanie).
  const shown = useMemo<string[][]>(() => (rows.length > 0 ? rows : [[]]), [rows]);
  // Stałe klucze wierszy: usunięcie wiersza wyżej nie przenosi wpisywanego
  // tekstu do sąsiada (stan pola żyje w `ChipField`).
  const idsRef = useRef<number[]>([]);
  const nextIdRef = useRef(1);
  while (idsRef.current.length < shown.length) idsRef.current.push(nextIdRef.current++);
  if (idsRef.current.length > shown.length) idsRef.current.length = shown.length;

  // Wiersz dodany przyciskiem dostaje kursor — od razu można pisać.
  const [focusId, setFocusId] = useState<number | null>(null);
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  const allWords = useMemo(() => shown.flat(), [shown]);
  const cityWords = useCityWords(allWords, Boolean(onUseLocation));

  const hints = useMemo(() => {
    const out: KeywordHint[] = keywordHints(shown).filter(
      (hint) =>
        hint.kind === "split" || (hint.kind === "seniority" && Boolean(onUseExperience)),
    );
    shown.forEach((row, index) => {
      for (const word of row) {
        const city = cityWords.get(word);
        if (city) out.push({ kind: "city", row: index, word, city });
      }
    });
    return out.filter((hint) => !dismissed.has(hintKey(hint)));
  }, [shown, cityWords, dismissed, onUseExperience]);

  const setRow = (index: number, next: string[]) => {
    onRowsChange(shown.map((row, i) => (i === index ? next : [...row])));
  };
  const removeRow = (index: number) => {
    idsRef.current.splice(index, 1);
    onRowsChange(shown.filter((_, i) => i !== index).map((row) => [...row]));
  };
  const addRow = () => {
    setFocusId(nextIdRef.current);
    onRowsChange([...shown.map((row) => [...row]), []]);
  };
  const dismiss = (hint: KeywordHint) =>
    setDismissed((prev) => new Set(prev).add(hintKey(hint)));
  const dropWord = (hint: KeywordHint) => {
    const next = withoutWord(shown, hint.row, hint.word);
    if (next.length < shown.length) idsRef.current.splice(hint.row, 1);
    onRowsChange(next);
  };

  const atLimit = shown.length >= MAX_REQUIREMENT_ROWS;
  const canRemove = shown.length > 1 || shown[0].length > 0;

  return (
    <div className={cn("flex flex-col gap-2", className)}>
      <div role="group" aria-label="Wymagania — każdy wiersz musi być spełniony" className="flex flex-col gap-2">
        {shown.map((row, index) => {
          const rowHints = hints.filter((hint) => hint.row === index);
          return (
            <div key={idsRef.current[index]} className="flex flex-col gap-1.5">
              <div className="flex items-start gap-2 sm:gap-3">
                <span className="flex h-10 w-16 shrink-0 items-center justify-end sm:w-20">
                  {index === 0 ? (
                    <span className="text-xs font-semibold text-success-muted-foreground">
                      Musi mieć
                    </span>
                  ) : (
                    <span
                      aria-label="i"
                      className="rounded-md bg-muted px-2 py-0.5 text-[11px] font-bold tracking-wider text-muted-foreground"
                    >
                      I
                    </span>
                  )}
                </span>
                <div className="min-w-0 flex-1">
                  <ChipField
                    layout="inline"
                    joiner="lub"
                    chips={row}
                    onChange={(next) => setRow(index, next)}
                    placeholder={row.length ? "lub…" : "wpisz słowo, Enter dodaje"}
                    tone="emerald"
                    ariaLabel={`Wymaganie ${index + 1} — słowo albo wariant`}
                    suggest={suggest}
                    onSubmitEmpty={onSubmitEmpty}
                    invalid={invalid && index === 0 && row.length === 0}
                    autoFocus={idsRef.current[index] === focusId}
                  />
                </div>
                <button
                  type="button"
                  onClick={() => removeRow(index)}
                  disabled={!canRemove}
                  aria-label={`Usuń wymaganie ${index + 1}`}
                  title="Usuń wymaganie"
                  className="hit-area mt-2 inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground disabled:invisible"
                >
                  <X className="h-4 w-4" aria-hidden />
                </button>
              </div>
              {rowHints.map((hint) => (
                <HintRow
                  key={hintKey(hint)}
                  hint={hint}
                  onDismiss={() => dismiss(hint)}
                  onApply={() => {
                    if (hint.kind === "split") {
                      onRowsChange(splitWordInRow(shown, hint.row, hint.word, hint.parts));
                    } else if (hint.kind === "city") {
                      dropWord(hint);
                      onUseLocation?.(hint.city);
                    } else {
                      dropWord(hint);
                      onUseExperience?.(hint.range);
                    }
                  }}
                />
              ))}
            </div>
          );
        })}
      </div>

      <div className="flex flex-wrap items-center gap-3 pl-[4.5rem] sm:pl-[5.75rem]">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={addRow}
          disabled={atLimit}
          className="gap-1.5 border-dashed"
        >
          <Plus className="h-3.5 w-3.5" aria-hidden />
          Dodaj wymaganie
        </Button>
        <span className="text-xs text-muted-foreground">
          {atLimit
            ? `Najwyżej ${MAX_REQUIREMENT_ROWS} wymagań.`
            : "Słowa w jednym wierszu to warianty — wystarczy jedno z nich."}
        </span>
      </div>

      <div className="flex items-start gap-2 border-t border-border pt-2 sm:gap-3">
        <span className="flex h-10 w-16 shrink-0 items-center justify-end text-xs font-semibold text-destructive-muted-foreground sm:w-20">
          Wyklucz
        </span>
        <div className="min-w-0 flex-1">
          <ChipField
            layout="inline"
            chips={exclude}
            onChange={onExcludeChange}
            placeholder="osoba nie może mieć żadnego z tych słów"
            tone="rose"
            ariaLabel="Wyklucz — żadne z tych słów"
            suggest={suggest}
            onSubmitEmpty={onSubmitEmpty}
          />
        </div>
        <span className="w-6 shrink-0" aria-hidden />
      </div>
    </div>
  );
}

function HintRow({
  hint,
  onApply,
  onDismiss,
}: {
  hint: KeywordHint;
  onApply: () => void;
  onDismiss: () => void;
}) {
  const text =
    hint.kind === "split"
      ? `„${hint.word}” to kilka wariantów — rozdzielić? Wystarczy jedno z nich: ${hint.parts.join(" lub ")}.`
      : hint.kind === "city"
        ? `„${hint.word}” to miasto. Tu szukamy słowa w tekście profilu.`
        : `„${hint.word}” znajdzie tylko osoby, które same tak się opisały.`;
  const action =
    hint.kind === "split"
      ? "Rozdziel"
      : hint.kind === "city"
        ? `Ustaw lokalizację: ${hint.city}`
        : `Użyj filtra stażu: ${experienceRangeLabel(hint.range)}`;
  return (
    <div
      role="note"
      className="ml-[4.5rem] flex flex-wrap items-center gap-2 rounded-md border border-warning/40 bg-warning-muted px-3 py-1.5 text-xs text-warning-muted-foreground sm:ml-[5.75rem]"
    >
      <Lightbulb className="h-3.5 w-3.5 shrink-0" aria-hidden />
      <span className="min-w-0 flex-1">{text}</span>
      <Button type="button" size="sm" variant="outline" onClick={onApply}>
        {action}
      </Button>
      <Button type="button" size="sm" variant="ghost" onClick={onDismiss}>
        Zostaw
      </Button>
    </div>
  );
}
