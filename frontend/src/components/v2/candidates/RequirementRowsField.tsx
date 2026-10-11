"use client";

import { useEffect, useId, useMemo, useRef, useState } from "react";
import { Lightbulb, Plus, X } from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import {
  ChipField,
  type ChipCommitSource,
  type ChipFieldSuggest,
} from "@/components/v2/filters/AdvancedSearchPopover";
import {
  MAX_REQUIREMENT_ROWS,
  enterKeywordRows,
  experienceRangeLabel,
  foldWord,
  hintKey,
  keywordHints,
  keywordLongEnough,
  splitWordInRow,
  tooShortKeywordMessage,
  withoutWord,
  type ExperienceRange,
  type KeywordEntryResult,
  type KeywordHint,
} from "@/lib/keyword-requirements";
import { ROW_WORDS_MAX, parseRequirementEntry } from "@/lib/requirement-rows";

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
  /**
   * Panel 56–94rem: „Musi mieć” i „Wyklucz” obok siebie (dwie kolumny) — na
   * laptopie z Windows (okno ≈ 1280 × 650 px) panel słów kluczowych zabierał
   * liście kandydatów jedną trzecią wysokości (28.09.2026). Szerokość liczy
   * najbliższy `@container` (KeywordFields), nie okno — U8, 06.10.2026.
   */
  split?: boolean;
  className?: string;
}

/** Co wpis pominął: powtórzone wymagania, nadmiar ponad limit, za krótkie słowa. */
function entryNoteText(result: KeywordEntryResult, skipped: readonly string[]): string | null {
  const parts: string[] = [];
  if (result.duplicates.length > 0) {
    const list = result.duplicates.map((word) => `„${word}”`).join(", ");
    parts.push(`${list} już ${result.duplicates.length > 1 ? "są" : "jest"} na liście.`);
  }
  if (result.overLimit.length > 0) {
    parts.push(
      `Najwyżej ${MAX_REQUIREMENT_ROWS} wymagań — nie dodano: ${result.overLimit.join(", ")}.`,
    );
  }
  if (skipped.length > 0) parts.push(tooShortKeywordMessage(skipped));
  return parts.length > 0 ? parts.join(" ") : null;
}

/**
 * Słowa kluczowe jako lista wymagań (makiety 25.09.2026): wiersz = jedno
 * wymaganie, słowa w wierszu to warianty („lub”), wiersze łączy „i”, na dole
 * „Wyklucz”. Pod wierszem podpowiedzi przy typowych pomyłkach — nic nie
 * zmienia się samo, każda ma przycisk i „Zostaw”.
 *
 * Wpisywanie jak w wierszach wymagań rekrutacji (11.10.2026): w pustym
 * wierszu Enter, przecinek, średnik i wklejona lista to OSOBNE wymagania,
 * a wypełniony wiersz pokazuje same słowa — wariant dodaje dopiero „+ lub”.
 * Do tej daty przecinek dopisywał wariant, więc „Java, Spring” znajdowało
 * osoby z samą Javą.
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
  split = false,
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
  // U8 (audyt 06.10.2026): po „Usuń wymaganie” kursor szedł na `body` —
  // przenosimy go do wiersza, który zajął miejsce usuniętego. Tak samo po
  // wpisie (pusty wiersz niżej) i po otwarciu albo zamknięciu pola wariantu.
  // Wypełniony wiersz nie ma pola do pisania, więc celem bywa jego „+ lub”.
  const baseId = useId();
  const inputIdFor = (rowId: number) => `${baseId}-row-${rowId}`;
  const variantButtonIdFor = (rowId: number) => `${baseId}-or-${rowId}`;
  const [refocus, setRefocus] = useState<string | null>(null);
  useEffect(() => {
    if (refocus == null) return;
    document.getElementById(refocus)?.focus();
    setRefocus(null);
  }, [refocus]);
  // Wiersz z otwartym polem wariantu („+ lub”) — jedno naraz.
  const [variantId, setVariantId] = useState<number | null>(null);
  const [entryNote, setEntryNote] = useState<string | null>(null);
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  const allWords = useMemo(() => shown.flat(), [shown]);
  const cityWords = useCityWords(allWords, Boolean(onUseLocation));

  const hints = useMemo(() => {
    const out: KeywordHint[] = keywordHints(shown).filter(
      (hint) =>
        hint.kind === "split" ||
        hint.kind === "ambiguous" ||
        (hint.kind === "seniority" && Boolean(onUseExperience)),
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
    // Wiersz bez słów wraca do wpisywania wymagań — pole wariantu znika.
    if (next.length === 0 && variantId === idsRef.current[index]) setVariantId(null);
    onRowsChange(shown.map((row, i) => (i === index ? next : [...row])));
  };
  const removeRow = (index: number) => {
    if (variantId === idsRef.current[index]) setVariantId(null);
    setEntryNote(null);
    idsRef.current.splice(index, 1);
    const next = shown.filter((_, i) => i !== index).map((row) => [...row]);
    // Pusta lista wraca jako jeden pusty wiersz o nowym kluczu.
    if (next.length === 0) {
      setRefocus(inputIdFor(nextIdRef.current));
    } else {
      const at = Math.min(index, next.length - 1);
      const rowId = idsRef.current[at];
      // Przycisk „+ lub” ma tylko wypełniony wiersz z zamkniętym polem wariantu.
      const hasButton = next[at].length > 0 && variantId !== rowId;
      setRefocus(hasButton ? variantButtonIdFor(rowId) : inputIdFor(rowId));
    }
    onRowsChange(next);
  };
  const addRow = () => {
    setFocusId(nextIdRef.current);
    setEntryNote(null);
    onRowsChange([...shown.map((row) => [...row]), []]);
  };
  /**
   * Wpis w PUSTYM wierszu: każda grupa to osobne wymaganie (pierwsza wypełnia
   * ten wiersz, kolejne dochodzą pod nim), a kursor idzie do pustego wiersza
   * na końcu — całość jedną zmianą listy. Przy wyjściu z pola pustego wiersza
   * nie dokładamy (lista urosłaby pod kursorem myszy w trakcie kliknięcia).
   * Zwraca słowa odrzucone, gdy wiersz został pusty — pokazuje je wtedy pole.
   */
  const enter = (
    index: number,
    groups: readonly (readonly string[])[],
    via: ChipCommitSource,
    rejected: readonly string[] = [],
  ): string[] => {
    const result = enterKeywordRows(shown, index, groups, { trailing: via !== "blur" });
    if (result.added === 0) {
      setEntryNote(entryNoteText(result, []));
      return [...rejected];
    }
    setEntryNote(entryNoteText(result, rejected));
    // Nowe wiersze stają pod wierszem wpisu — ich klucze też, żeby tekst
    // pisany w wierszach niżej nie przeskoczył do sąsiada.
    const rowId = idsRef.current[index];
    const fresh = Array.from({ length: result.inserted }, () => nextIdRef.current++);
    idsRef.current.splice(index + 1, 0, ...fresh);
    if (via !== "blur") {
      // Pusty wiersz na końcu już jest albo powstanie z kolejnym kluczem.
      // Bez miejsca na niego kursor zostaje przy wpisanym wymaganiu.
      setRefocus(
        result.focusRow != null
          ? inputIdFor(idsRef.current[result.focusRow] ?? nextIdRef.current)
          : variantButtonIdFor(rowId),
      );
    }
    onRowsChange(result.rows);
    return [];
  };
  const openVariant = (rowId: number) => {
    setVariantId(rowId);
    setRefocus(inputIdFor(rowId));
  };
  /** Pusty Enter w polu wariantu: pole znika, kursor wraca na „+ lub”. */
  const closeVariant = (rowId: number) => {
    setVariantId(null);
    setRefocus(variantButtonIdFor(rowId));
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
    <div
      className={cn(
        "flex flex-col gap-2",
        split &&
          "@4xl:grid @4xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)] @4xl:gap-x-4 @min-[94rem]:flex",
        className,
      )}
    >
      <div
        role="group"
        aria-label="Wymagania — każdy wiersz musi być spełniony"
        className={cn("flex flex-col gap-2", split && "@4xl:col-start-1")}
      >
        {shown.map((row, index) => {
          const rowHints = hints.filter((hint) => hint.row === index);
          const rowId = idsRef.current[index];
          // Pusty wiersz przyjmuje wymagania. Wypełniony pokazuje same słowa:
          // bez pola kolejne słowo nie stanie się po cichu wariantem.
          const filled = row.length > 0;
          const variantOpen = filled && variantId === rowId;
          return (
            <div key={rowId} className="flex flex-col gap-1.5">
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
                <div
                  className="min-w-0 flex-1"
                  // Esc dociera tu tylko z pustego pola bez listy podpowiedzi —
                  // listę i wpisany tekst pole zamyka samo (`stopPropagation`).
                  onKeyDown={
                    variantOpen
                      ? (event) => {
                          if (event.key === "Escape") closeVariant(rowId);
                        }
                      : undefined
                  }
                >
                  <ChipField
                    layout="inline"
                    joiner="lub"
                    chips={row}
                    // Podpowiedź wybrana w pustym wierszu to całe wymaganie
                    // (nazwa z wariantami) — kursor idzie dalej jak po Enterze.
                    onChange={(next) =>
                      filled ? setRow(index, next) : enter(index, [next], "enter")
                    }
                    placeholder={
                      filled ? "lub… (wariant)" : "wpisz słowo — Enter albo przecinek: następne"
                    }
                    tone="emerald"
                    ariaLabel={`Wymaganie ${index + 1} — słowo albo wariant`}
                    suggest={suggest}
                    onCommitText={
                      filled
                        ? undefined
                        : (text, via) => {
                            const entry = parseRequirementEntry(text, keywordLongEnough);
                            return enter(index, entry.groups, via, entry.rejected);
                          }
                    }
                    onSubmitEmpty={
                      variantOpen
                        ? () => {
                            closeVariant(rowId);
                            onSubmitEmpty?.();
                          }
                        : onSubmitEmpty
                    }
                    hideInput={filled && !variantOpen}
                    trailing={
                      filled && !variantOpen && row.length < ROW_WORDS_MAX ? (
                        <button
                          type="button"
                          id={variantButtonIdFor(rowId)}
                          onClick={() => openVariant(rowId)}
                          aria-label={`Dodaj wariant do wymagania ${index + 1}`}
                          title="Dodaj wariant — wystarczy, że kandydat ma jedno ze słów tego wiersza"
                          className="hit-area inline-flex h-6 shrink-0 items-center rounded-md border border-dashed border-border px-1.5 text-xs font-medium text-muted-foreground hover:bg-muted hover:text-foreground"
                        >
                          + lub
                        </button>
                      ) : undefined
                    }
                    invalid={invalid && index === 0 && !filled}
                    autoFocus={rowId === focusId}
                    inputId={inputIdFor(rowId)}
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
                    } else if (hint.kind === "ambiguous") {
                      if (hint.instead) {
                        onRowsChange(splitWordInRow(shown, hint.row, hint.word, [hint.instead]));
                      }
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

      <div
        className={cn(
          "flex flex-wrap items-center gap-3 pl-[4.5rem] sm:pl-[5.75rem]",
          split && "@4xl:col-start-1",
        )}
      >
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
        <span
          className={cn(
            "text-xs text-muted-foreground",
            // W układzie dwukolumnowym zdanie łamało się do osobnej linii —
            // to samo mówi podpowiedź ⓘ panelu (limit wierszy zostaje zawsze).
            split && !atLimit && "@4xl:hidden @min-[94rem]:inline",
          )}
        >
          {atLimit
            ? `Najwyżej ${MAX_REQUIREMENT_ROWS} wymagań.`
            : "Słowa w jednym wierszu to warianty — wystarczy jedno z nich."}
        </span>
        {/* Pod przyciskiem, nie nad nim: notka pojawia się też przy wyjściu
            z pola, a przycisk przesunięty w trakcie kliknięcia by je zgubił. */}
        {entryNote ? (
          <p
            role="status"
            className="basis-full text-xs text-warning-muted-foreground"
            data-testid="requirement-entry-note"
          >
            {entryNote}
          </p>
        ) : null}
      </div>

      <div
        className={cn(
          "flex items-start gap-2 border-t border-border pt-2 sm:gap-3",
          split &&
            "@4xl:col-start-2 @4xl:row-span-2 @4xl:row-start-1 @4xl:self-start @4xl:border-t-0 @4xl:pt-0 @min-[94rem]:self-auto @min-[94rem]:border-t @min-[94rem]:pt-2",
        )}
      >
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
        : hint.kind === "ambiguous"
          ? `„${hint.word}” to słowo wieloznaczne — łapie też ${hint.catches}.`
          : `„${hint.word}” znajdzie tylko osoby, które same tak się opisały.`;
  // Słowo wieloznaczne bez sensownego zamiennika („it”, „net”) tylko ostrzega.
  const action: string | null =
    hint.kind === "split"
      ? "Rozdziel"
      : hint.kind === "city"
        ? `Ustaw lokalizację: ${hint.city}`
        : hint.kind === "ambiguous"
          ? hint.instead
            ? `Zamień na „${hint.instead}”`
            : null
          : `Użyj filtra stażu: ${experienceRangeLabel(hint.range)}`;
  return (
    <div
      role="note"
      className="ml-[4.5rem] flex flex-wrap items-center gap-2 rounded-md border border-warning/40 bg-warning-muted px-3 py-1.5 text-xs text-warning-muted-foreground sm:ml-[5.75rem]"
    >
      <Lightbulb className="h-3.5 w-3.5 shrink-0" aria-hidden />
      <span className="min-w-0 flex-1">{text}</span>
      {action && (
        <Button type="button" size="sm" variant="outline" onClick={onApply}>
          {action}
        </Button>
      )}
      <Button type="button" size="sm" variant="ghost" onClick={onDismiss}>
        Zostaw
      </Button>
    </div>
  );
}
