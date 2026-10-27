"use client";

/**
 * Wymagania rekrutacji jako jedna lista słów kluczowych (decyzje Artura
 * 02.10.2026, makiety https://claude.ai/artifact/UPDv1tSQBeo5t9kLW6WJoH).
 *
 * Wiersz = wymaganie, słowa w wierszu = warianty (wystarczy jedno), poziom =
 * krytyczne / musi mieć / mile widziane. Zastępuje trzy pola, w które Delivery
 * Lead wpisywał to samo: must-have, umiejętności krytyczne i „wymagania do
 * wyszukiwania w bazie”. Reguły: `lib/requirement-rows.ts`; ten sam edytor
 * stoi na `/jobs/new` i w Profilu Championa.
 *
 * Wpisywanie (decyzja D1, 10.10.2026): Enter, przecinek, średnik i wklejona
 * lista dają OSOBNE wymagania. Wariant powstaje tylko świadomie — „A / B”,
 * „A lub B” albo przycisk „+ lub” w wypełnionym wierszu — bo wiersz „A lub B”
 * spełnia kandydat z jednym z tych słów.
 */

import { useEffect, useId, useMemo, useRef, useState } from "react";
import { Lightbulb, Plus, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import { ChipField, type ChipCommitSource } from "@/components/v2/filters/AdvancedSearchPopover";
import { peopleCountLabel } from "@/components/champion/SearchRequirementsEditor";
import {
  CityCallout,
  CommentCallout,
  DecisionCallout,
  RareWordCallout,
} from "@/components/champion/RequirementRowCallouts";
import { statSentence } from "@/lib/critical-skills";
import {
  hintKey,
  keywordHints,
  splitWordInRow,
  type KeywordHint,
} from "@/lib/keyword-requirements";
import {
  LEVEL_LABEL,
  NICE_ROWS_MAX,
  REQUIRED_ROWS_MAX,
  ROW_WORDS_MAX,
  addRowVariants,
  acceptRequirementWord,
  addRow,
  applySuggestion,
  canAddRow,
  criticalReachWarning,
  criticalRows,
  criticalSummary,
  enterRequirements,
  gluedVariants,
  isRareRowCount,
  levelBlockedReason,
  parseRequirementEntry,
  requiredOverflowNotice,
  replaceRowWord,
  requiredRows,
  rowCity,
  rowComment,
  rowCountHint,
  rowDecision,
  rowHead,
  setRowLevel,
  suggestedRowKeys,
  talkTextFor,
  type RequirementEntryResult,
  type RequirementLevel,
  type RequirementRowForm,
  type RowCriticalState,
  type TalkItem,
} from "@/lib/requirement-rows";
import { useRowCounts } from "@/lib/requirement-rows-api";
import { cn } from "@/lib/utils";

/**
 * Krytyczny wiersz, którego słownik technologii nie zna (narzędzie spoza
 * słownika, branża, język, zdanie): o tym, co jest krytyczne, decyduje
 * Delivery Lead (09.10.2026), a bramka szuka wtedy dosłownie słów wiersza.
 */
export const OUTSIDE_DICTIONARY_NOTE =
  "Spoza słownika technologii — w propozycjach AI zostają osoby, które mają którekolwiek ze słów tego wiersza w profilu, CV albo notatkach. Szukamy dokładnie tych słów; odmianę łapie początek słowa z gwiazdką, np. „bankow*”.";

export interface RequirementRowsEditorProps {
  rows: RequirementRowForm[];
  onRowsChange: (rows: RequirementRowForm[]) => void;
  /** Świadome „Brak krytycznych”. */
  noCritical: boolean;
  onNoCriticalChange: (value: boolean) => void;
  exclude: string[];
  onExcludeChange: (next: string[]) => void;
  /** Co serwer wie o wierszach (`useRowCriticalInfo`) albo dane harnessu. */
  critical: RowCriticalState;
  /** Brak wymagań blokuje „Przekaż do searchu”. */
  invalid?: boolean;
  /** Brak decyzji o krytycznych blokuje „Przekaż do searchu”. */
  criticalMissing?: boolean;
  /** Harness `/preview/*` — bez zapytań o liczbę osób. */
  countEnabled?: boolean;
  /** Bez prawa edycji: sama lista wymagań z poziomami, bez pól. */
  disabled?: boolean;
  className?: string;
  /**
   * „Do rozmowy” (wariant A, 13.10.2026): zdanie, język albo umiejętność
   * miękka wypada z wiersza i trafi do „Rekruter sprawdza w rozmowie” /
   * pola „Język” — rodzic dopisuje je do Profilu Championa.
   */
  onMoveToTalk?: (item: TalkItem) => void;
  /** Ile osób zostawiają krytyczne razem (`undefined` = liczę, `null` = nie wiadomo). */
  onCriticalCountChange?: (count: number | null | undefined) => void;
}

/** Podpowiedzi w wierszu: lista dopiero po wpisaniu tekstu (nie zasłania wiersza niżej). */
const ROW_SUGGEST = { quietWhenEmpty: true } as const;

/**
 * Co edytor mówi o wpisie, z którego nie wszystko trafiło na listę — żadne
 * słowo nie znika po cichu. `null` = wszystko weszło.
 */
function entryNoteText(result: RequirementEntryResult, skipped: readonly string[]): string | null {
  const parts: string[] = [];
  if (result.duplicates.length > 0) parts.push(`Już na liście: ${result.duplicates.join(", ")}.`);
  if (result.overLimit.length > 0) {
    parts.push(
      `Nie zmieściło się: ${result.overLimit.join(", ")} — lista ma najwyżej ${REQUIRED_ROWS_MAX + NICE_ROWS_MAX} wymagań.`,
    );
  }
  if (skipped.length > 0) {
    parts.push(`Pominięto za krótkie: ${skipped.map((word) => `„${word}”`).join(", ")}.`);
  }
  return parts.length > 0 ? parts.join(" ") : null;
}

function countText(value: number | null | undefined): string {
  if (value === undefined) return "liczę…";
  if (value === null) return "—";
  return `~${value.toLocaleString("pl-PL")}`;
}

export function RequirementRowsEditor({
  rows,
  onRowsChange,
  noCritical,
  onNoCriticalChange,
  exclude,
  onExcludeChange,
  critical,
  invalid = false,
  criticalMissing = false,
  countEnabled = true,
  disabled = false,
  className,
  onMoveToTalk,
  onCriticalCountChange,
}: RequirementRowsEditorProps) {
  const noCriticalId = useId();
  const shown = useMemo<RequirementRowForm[]>(
    () => (rows.length > 0 ? rows : addRow([])),
    [rows],
  );
  // Wiersz dodany przyciskiem albo wpisem dostaje kursor — od razu można
  // pisać. Ustawiamy go po renderze: wiersz bywa już zamontowany (pusty wiersz
  // pod spodem), więc samo `autoFocus` by nie zadziałało. `addVariant` =
  // przycisk „+ lub” wiersza (po zamknięciu pola wariantu).
  const rootRef = useRef<HTMLDivElement | null>(null);
  const pendingFocus = useRef<{ key: string; on: "field" | "addVariant" } | null>(null);
  useEffect(() => {
    const pending = pendingFocus.current;
    if (!pending) return;
    pendingFocus.current = null;
    // Po pozycji, nie po kluczu: klucz pustego wiersza startowego powstaje
    // osobno na serwerze i w przeglądarce, więc nie może trafić do atrybutu.
    const index = shown.findIndex((row) => row.key === pending.key);
    if (index < 0) return;
    const target = pending.on === "field" ? "input[data-keyword-field]" : "button[data-add-variant]";
    rootRef.current
      ?.querySelector<HTMLElement>(`[data-row-index="${index}"] ${target}`)
      ?.focus();
  });
  // Wiersz z otwartym polem wariantu („+ lub”) — jedno naraz.
  const [variantKey, setVariantKey] = useState<string | null>(null);
  const [entryNote, setEntryNote] = useState<string | null>(null);
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  const counts = useRowCounts(shown, exclude, countEnabled && !disabled);
  const criticalCount = criticalRows(shown).length > 0 ? counts.critical : null;
  useEffect(() => {
    onCriticalCountChange?.(criticalCount);
  }, [criticalCount, onCriticalCountChange]);
  const hints = useMemo(
    () =>
      keywordHints(shown.map((row) => row.words)).filter(
        (hint) =>
          (hint.kind === "split" || hint.kind === "ambiguous") &&
          !dismissed.has(hintKey(hint)),
      ),
    [shown, dismissed],
  );

  const setWords = (key: string, words: string[]) =>
    onRowsChange(shown.map((row) => (row.key === key ? { ...row, words } : row)));
  const setLevel = (key: string, level: RequirementLevel) => {
    onRowsChange(setRowLevel(shown, key, level));
    if (level === "critical" && noCritical) onNoCriticalChange(false);
  };
  const remove = (key: string) => {
    setEntryNote(null);
    onRowsChange(shown.filter((row) => row.key !== key));
  };
  const add = () => {
    const next = addRow(shown);
    pendingFocus.current = { key: next[next.length - 1].key, on: "field" };
    setEntryNote(null);
    onRowsChange(next);
  };
  /**
   * Wpis w PUSTYM wierszu: każda grupa to osobne wymaganie (pierwsza wypełnia
   * ten wiersz, kolejne dochodzą pod nim), a kursor idzie do pustego wiersza
   * na końcu. Wszystko JEDNĄ zmianą listy — dwie zmiany liczone z tego samego
   * `shown` gubiłyby pierwszą. Przy wyjściu z pola nie dokładamy pustego
   * wiersza: lista urosłaby pod kursorem myszy w trakcie kliknięcia i klik
   * w „Dodaj słowo kluczowe” trafiałby obok.
   * Zwraca słowa odrzucone, gdy wiersz został pusty — pokazuje je wtedy samo
   * pole; po dodaniu wymagań pole znika, więc mówi o nich notka pod listą.
   */
  const enter = (
    key: string,
    groups: readonly (readonly string[])[],
    via: ChipCommitSource,
    rejected: readonly string[] = [],
  ): string[] => {
    const result = enterRequirements(shown, key, groups, { trailing: via !== "blur" });
    if (result.added === 0) {
      setEntryNote(entryNoteText(result, []));
      return [...rejected];
    }
    setEntryNote(entryNoteText(result, rejected));
    if (via !== "blur") {
      // Bez miejsca na kolejny wiersz kursor nie ma dokąd iść — fokus zostaje
      // przy wpisanym wymaganiu (pole tego wiersza właśnie zniknęło).
      pendingFocus.current = result.focusKey
        ? { key: result.focusKey, on: "field" }
        : { key, on: "addVariant" };
    }
    if (variantKey === key) setVariantKey(null);
    onRowsChange(result.rows);
    return [];
  };
  const openVariant = (key: string) => {
    pendingFocus.current = { key, on: "field" };
    setVariantKey(key);
  };
  /** Pusty Enter albo Esc w polu wariantu: pole znika, fokus wraca na „+ lub”. */
  const closeVariant = (key: string) => {
    pendingFocus.current = { key, on: "addVariant" };
    setVariantKey(null);
  };
  const applyHint = (hint: KeywordHint) => {
    const parts =
      hint.kind === "split" ? hint.parts : hint.kind === "ambiguous" && hint.instead ? [hint.instead] : null;
    if (!parts) return;
    const words = splitWordInRow(
      shown.map((row) => row.words),
      hint.row,
      hint.word,
      parts,
    );
    onRowsChange(shown.map((row, index) => ({ ...row, words: words[index] ?? row.words })));
  };

  const suggested = suggestedRowKeys(shown, critical.info);
  const hasCritical = criticalRows(shown).length > 0;
  const required = requiredRows(shown);
  const showSuggestion = suggested.length > 0 && !hasCritical && !noCritical;
  const canRemove = shown.length > 1 || shown[0].words.length > 0;
  const overflowNotice = requiredOverflowNotice(shown);
  // Które „musi mieć” zawężają listę do zera (pomiar 27.10.2026: w 50 ze 129
  // rekrutacji wszystkie razem nie zostawiały nikogo, a DL widział samo „~0”).
  const narrowest = isRareRowCount(counts.required)
    ? required
        .filter((row) => row.level === "must" && isRareRowCount(counts.perRow[row.key]))
        .sort((a, b) => (counts.perRow[a.key] ?? 0) - (counts.perRow[b.key] ?? 0))
        .slice(0, 3)
    : [];

  if (disabled) {
    const filled = shown.filter((row) => row.words.length > 0);
    return (
      <div className={cn("flex flex-col gap-2", className)}>
        {filled.length === 0 ? (
          <p className="text-sm text-muted-foreground">Brak wymagań.</p>
        ) : (
          <ul className="flex flex-col gap-1.5" aria-label="Wymagania — słowa kluczowe">
            {filled.map((row) => (
              <li key={row.key} className="flex flex-wrap items-baseline gap-2 text-sm">
                <span className="font-medium text-foreground">{row.words.join(" lub ")}</span>
                <span
                  className={cn(
                    "rounded-full px-2 py-0.5 text-[11px] font-medium",
                    row.level === "critical"
                      ? "bg-primary/10 text-primary"
                      : "bg-muted text-muted-foreground",
                  )}
                >
                  {LEVEL_LABEL[row.level]}
                </span>
              </li>
            ))}
          </ul>
        )}
        {exclude.length > 0 ? (
          <p className="text-xs text-muted-foreground">Wyklucz: {exclude.join(", ")}</p>
        ) : null}
        <p className="text-xs text-muted-foreground">{criticalSummary(shown, noCritical)}</p>
      </div>
    );
  }

  return (
    <div ref={rootRef} className={cn("@container flex flex-col gap-3", className)}>
      <div
        role="group"
        aria-label="Wymagania — słowa kluczowe"
        className="flex flex-col gap-2"
      >
        <div
          aria-hidden
          className="hidden gap-3 px-1 text-xs font-medium text-muted-foreground @xl:grid @xl:grid-cols-[minmax(0,1fr)_auto_5.5rem_1.5rem]"
        >
          <span>Słowo kluczowe — Enter albo przecinek: następne wymaganie</span>
          <span className="w-[17rem]">Poziom</span>
          <span className="text-right">W bazie</span>
          <span />
        </div>
        {shown.map((row, index) => {
          const info = critical.info?.[row.key];
          const head = rowHead(row.words);
          const name = head || `wiersz ${index + 1}`;
          // O tym, co jest krytyczne, decyduje Delivery Lead (09.10.2026):
          // „Krytyczne” wyłącza wyłącznie limit, nigdy treść wiersza ani
          // oczekiwanie na odpowiedź serwera.
          // Wariant A (13.10.2026): zdanie, język i umiejętność miękka czekają
          // na decyzję i nie mogą być krytyczne — CV ich nie potwierdzi.
          const decision = rowDecision(info);
          const comment = decision ? null : rowComment(info);
          const city = decision ? null : rowCity(info);
          const cityKey = city ? `city:${city.text}` : "";
          const talkLevel = row.level === "nice" ? "nice" : "must";
          const toTalk = (text: string, kind: TalkItem["kind"]) =>
            onMoveToTalk?.({ name: text, kind, level: talkLevel });
          const criticalTitle =
            row.level === "critical"
              ? undefined
              : decision
                ? "Najpierw zdecyduj: słowa do szukania czy rozmowa."
                : (levelBlockedReason(shown, row.key, "critical") ?? undefined);
          const stat = info?.suggested ? statSentence(info.stat) : null;
          // N8 (06.10.2026): liczba osób jest tylko przy wierszach obowiązkowych.
          const counted =
            !decision && !city && countEnabled && row.level !== "nice" && row.words.length > 0;
          const countHint = counted ? rowCountHint(counts.perRow[row.key]) : null;
          const rowCount = counts.perRow[row.key];
          const rareKey = `rare:${head}`;
          const rareCount =
            counted && isRareRowCount(rowCount) && !dismissed.has(rareKey) ? rowCount : null;
          const rowHints = hints.filter((hint) => hint.row === index);
          // Pusty wiersz przyjmuje wymagania. Wypełniony pokazuje same chipy:
          // bez pola kolejne słowo nie stanie się po cichu wariantem — pole
          // wariantu otwiera dopiero „+ lub”.
          const filled = row.words.length > 0;
          const variantOpen = filled && variantKey === row.key;
          return (
            <div key={row.key} data-row-index={index} className="flex flex-col gap-1.5">
              <div className="grid grid-cols-[minmax(0,1fr)_1.5rem] items-start gap-x-3 gap-y-1.5 @xl:grid-cols-[minmax(0,1fr)_auto_5.5rem_1.5rem]">
                <div
                  className="min-w-0"
                  // Esc dociera tu tylko z pustego pola bez listy podpowiedzi —
                  // listę i wpisany tekst pole zamyka samo (`stopPropagation`).
                  onKeyDown={
                    variantOpen
                      ? (event) => {
                          if (event.key === "Escape") closeVariant(row.key);
                        }
                      : undefined
                  }
                >
                  <ChipField
                    layout="inline"
                    joiner="lub"
                    chips={row.words}
                    // Podpowiedź wybrana w pustym wierszu to całe wymaganie
                    // (nazwa z wariantami) — kursor idzie dalej jak po Enterze.
                    onChange={(next) =>
                      filled ? setWords(row.key, next) : enter(row.key, [next], "enter")
                    }
                    placeholder={
                      filled
                        ? "lub… (wariant)"
                        : "np. Java — Enter albo przecinek dodaje kolejne wymaganie"
                    }
                    tone={row.level === "nice" ? "sky" : "emerald"}
                    ariaLabel={`Wymaganie ${index + 1} — słowo albo wariant`}
                    suggest={ROW_SUGGEST}
                    invalid={invalid && index === 0 && !filled}
                    acceptWord={acceptRequirementWord}
                    onCommitText={(text, via) => {
                      if (filled) {
                        // Pole wariantu: przecinek i średnik dopisują do TEGO wiersza.
                        const variants = addRowVariants(row.words, text);
                        if (variants.words.length > row.words.length) {
                          setWords(row.key, variants.words);
                        }
                        return variants.rejected;
                      }
                      const entry = parseRequirementEntry(text);
                      return enter(row.key, entry.groups, via, entry.rejected);
                    }}
                    onSubmitEmpty={variantOpen ? () => closeVariant(row.key) : undefined}
                    hideInput={filled && !variantOpen}
                    trailing={
                      filled && !variantOpen && row.words.length < ROW_WORDS_MAX ? (
                        <button
                          type="button"
                          data-add-variant=""
                          onClick={() => openVariant(row.key)}
                          aria-label={`Dodaj wariant do wymagania ${index + 1}`}
                          title="Dodaj wariant — wystarczy, że kandydat ma jedno ze słów tego wiersza"
                          className="hit-area inline-flex h-6 shrink-0 items-center rounded-md border border-dashed border-border px-1.5 text-xs font-medium text-muted-foreground hover:bg-muted hover:text-foreground"
                        >
                          + lub
                        </button>
                      ) : undefined
                    }
                  />
                </div>
                <button
                  type="button"
                  onClick={() => remove(row.key)}
                  disabled={disabled || !canRemove}
                  aria-label={`Usuń wymaganie: ${name}`}
                  title="Usuń wymaganie"
                  className="hit-area mt-2 inline-flex h-6 w-6 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground disabled:invisible @xl:order-last"
                >
                  <X className="h-4 w-4" aria-hidden />
                </button>
                <div className="col-span-2 flex flex-wrap items-center gap-x-3 gap-y-1 @xl:col-span-1 @xl:w-[17rem]">
                  <SegmentedRadio<RequirementLevel>
                    label={`Poziom wymagania: ${name}`}
                    size="sm"
                    value={row.level}
                    onChange={(level) => setLevel(row.key, level)}
                    disabled={disabled}
                    options={[
                      {
                        value: "critical",
                        label: LEVEL_LABEL.critical,
                        disabled: row.level !== "critical" && criticalTitle != null,
                        title: criticalTitle,
                      },
                      { value: "must", label: LEVEL_LABEL.must },
                      {
                        value: "nice",
                        label: LEVEL_LABEL.nice,
                        disabled: levelBlockedReason(shown, row.key, "nice") != null,
                        title: levelBlockedReason(shown, row.key, "nice") ?? undefined,
                      },
                    ]}
                  />
                </div>
                <span
                  className={cn(
                    "col-span-2 text-xs tabular-nums text-muted-foreground @xl:col-span-1 @xl:mt-2 @xl:text-right",
                    (!countEnabled || row.level === "nice" || row.words.length === 0) &&
                      "hidden @xl:invisible @xl:block",
                  )}
                  aria-label={`Osób w bazie ze słowem ${name}`}
                >
                  {countText(counts.perRow[row.key])}
                </span>
              </div>
              {stat ? (
                <p className="px-1 text-xs text-muted-foreground">
                  Podpowiedź z historii: {stat}.
                </p>
              ) : null}
              {row.level === "critical" && info && !info.eligible ? (
                <p
                  className="px-1 text-xs text-muted-foreground"
                  data-testid="requirement-row-outside-dictionary"
                >
                  {OUTSIDE_DICTIONARY_NOTE}
                </p>
              ) : null}
              {decision ? (
                <DecisionCallout
                  reading={decision}
                  countEnabled={countEnabled && !disabled}
                  onUseWord={(word) => {
                    onRowsChange(replaceRowWord(shown, row.key, decision.text, [word]));
                    toTalk(talkTextFor(decision, row.words), decision.talk ?? "skills");
                  }}
                  onTalk={() => {
                    onRowsChange(replaceRowWord(shown, row.key, decision.text, []));
                    toTalk(talkTextFor(decision, row.words), decision.talk ?? "skills");
                  }}
                />
              ) : null}
              {comment ? (
                <CommentCallout
                  reading={comment}
                  onSplit={() => {
                    onRowsChange(
                      replaceRowWord(shown, row.key, comment.text, [comment.keyword ?? comment.text]),
                    );
                    if (comment.talk_text) toTalk(comment.talk_text, "skills");
                  }}
                />
              ) : null}
              {city && !dismissed.has(cityKey) ? (
                <CityCallout
                  reading={city}
                  onRemove={() => remove(row.key)}
                  onKeep={() => setDismissed((prev) => new Set(prev).add(cityKey))}
                />
              ) : null}
              {rareCount != null ? (
                <RareWordCallout
                  word={row.words.join(" lub ")}
                  count={rareCount}
                  split={row.words.length === 1 ? gluedVariants(row.words[0]) : null}
                  countEnabled={countEnabled}
                  onSplit={(parts) => setWords(row.key, parts)}
                  onTalk={() => {
                    remove(row.key);
                    toTalk(row.words.join(" / "), "skills");
                  }}
                  onKeep={() => setDismissed((prev) => new Set(prev).add(rareKey))}
                />
              ) : null}
              {countHint ? (
                <p
                  className="px-1 text-xs text-warning-muted-foreground"
                  data-testid="requirement-row-count-hint"
                >
                  {countHint}
                </p>
              ) : null}
              {rowHints.map((hint) => (
                <div
                  key={hintKey(hint)}
                  role="note"
                  className="flex flex-wrap items-center gap-2 rounded-md border border-warning/40 bg-warning-muted px-3 py-1.5 text-xs text-warning-muted-foreground"
                >
                  <Lightbulb className="h-3.5 w-3.5 shrink-0" aria-hidden />
                  <span className="min-w-0 flex-1">
                    {hint.kind === "split"
                      ? `„${hint.word}” to kilka wariantów — rozdzielić? Wystarczy jedno z nich: ${hint.parts.join(" lub ")}.`
                      : hint.kind === "ambiguous"
                        ? `„${hint.word}” to słowo wieloznaczne — łapie też ${hint.catches}.`
                        : null}
                  </span>
                  {hint.kind === "split" || (hint.kind === "ambiguous" && hint.instead) ? (
                    <Button type="button" size="sm" variant="outline" onClick={() => applyHint(hint)}>
                      {hint.kind === "split" ? "Rozdziel" : `Zamień na „${hint.instead}”`}
                    </Button>
                  ) : null}
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    onClick={() => setDismissed((prev) => new Set(prev).add(hintKey(hint)))}
                  >
                    Zostaw
                  </Button>
                </div>
              ))}
            </div>
          );
        })}
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={add}
          disabled={disabled || !canAddRow(shown)}
          className="gap-1.5 border-dashed"
        >
          <Plus className="h-3.5 w-3.5" aria-hidden />
          Dodaj słowo kluczowe
        </Button>
        {showSuggestion ? (
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={disabled}
            onClick={() => onRowsChange(applySuggestion(shown, suggested))}
          >
            Oznacz krytyczne z historii:{" "}
            {shown
              .filter((row) => suggested.includes(row.key))
              .map((row) => rowHead(row.words))
              .join(", ")}
          </Button>
        ) : null}
        <label
          htmlFor={noCriticalId}
          className="inline-flex cursor-pointer items-center gap-2 text-sm text-foreground"
        >
          <Checkbox
            id={noCriticalId}
            checked={noCritical && !hasCritical}
            disabled={disabled}
            onCheckedChange={(checked) => {
              const value = checked === true;
              if (value && hasCritical) {
                onRowsChange(
                  shown.map((row) =>
                    row.level === "critical" ? { ...row, level: "must" as const } : row,
                  ),
                );
              }
              onNoCriticalChange(value);
            }}
          />
          Brak krytycznych
        </label>
        {/* Pod przyciskami, nie nad nimi: notka pojawia się też przy wyjściu
            z pola, a przycisk przesunięty w trakcie kliknięcia by go zgubił. */}
        {entryNote ? (
          <p
            role="status"
            className="basis-full text-xs text-warning-muted-foreground"
            data-testid="requirement-entry-note"
          >
            {entryNote}
          </p>
        ) : null}
        {overflowNotice ? (
          <p
            role="note"
            className="basis-full text-xs text-warning-muted-foreground"
            data-testid="requirement-rows-overflow"
          >
            {overflowNotice}
          </p>
        ) : null}
      </div>

      <div
        className={cn(
          "flex flex-col gap-1 rounded-lg border px-3 py-2 text-sm",
          criticalMissing || invalid
            ? "border-warning bg-warning-muted text-warning-muted-foreground"
            : "border-primary/20 bg-primary/5 text-foreground",
        )}
        aria-live="polite"
      >
        <span>
          {required.length === 0
            ? invalid
              ? "Dodaj co najmniej jedno słowo kluczowe — bez niego rekrutacja nie trafi do searchu."
              : "Po tych słowach szukamy w bazie. Krytyczne ukrywają w propozycjach AI osoby, które ich nie mają."
            : criticalSummary(shown, noCritical)}
        </span>
        {countEnabled && required.length > 0 ? (
          <span className="text-xs tabular-nums">
            Wszystkie „musi mieć” naraz:{" "}
            <strong className="font-semibold">
              {counts.required === undefined
                ? "liczę…"
                : counts.required === null
                  ? "nie policzono"
                  : `~${peopleCountLabel(counts.required)}`}
            </strong>{" "}
            w bazie
            {hasCritical ? (
              <>
                {" "}
                · same krytyczne:{" "}
                <strong className="font-semibold">
                  {counts.critical === undefined
                    ? "liczę…"
                    : counts.critical === null
                      ? "nie policzono"
                      : `~${peopleCountLabel(counts.critical)}`}
                </strong>
              </>
            ) : null}
            . „Szukaj ręcznie” wymaga tylko krytycznych — reszta podnosi w kolejności.
          </span>
        ) : null}
        {narrowest.length > 0 ? (
          <span
            className="text-xs font-medium text-warning-muted-foreground"
            data-testid="requirement-rows-narrowest"
          >
            Najbardziej zawężają:{" "}
            {narrowest
              .map((row) => `„${rowHead(row.words)}” (${counts.perRow[row.key]})`)
              .join(", ")}
            . Tych słów prawie nikt nie ma w CV, więc nie podnoszą nikogo w kolejności — zamień je
            na słowa z CV albo przenieś do rozmowy.
          </span>
        ) : null}
        {criticalReachWarning(criticalCount) ? (
          <span
            className="text-xs font-medium text-warning-muted-foreground"
            data-testid="requirement-critical-reach"
          >
            {criticalReachWarning(criticalCount)} Zmień któreś krytyczne na „Musi mieć” albo
            zostaw, jeśli tak ma być.
          </span>
        ) : null}
      </div>

      <div className="flex items-start gap-3 border-t border-border pt-3">
        <span className="flex h-10 shrink-0 items-center text-xs font-semibold text-destructive-muted-foreground">
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
            suggest={ROW_SUGGEST}
          />
        </div>
      </div>
    </div>
  );
}
