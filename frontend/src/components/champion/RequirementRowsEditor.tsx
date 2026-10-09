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
 */

import { useEffect, useId, useMemo, useRef, useState } from "react";
import { Lightbulb, Plus, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import { ChipField } from "@/components/v2/filters/AdvancedSearchPopover";
import { peopleCountLabel } from "@/components/champion/SearchRequirementsEditor";
import { statSentence } from "@/lib/critical-skills";
import {
  hintKey,
  keywordHints,
  splitWordInRow,
  type KeywordHint,
} from "@/lib/keyword-requirements";
import {
  LEVEL_LABEL,
  acceptRequirementWord,
  addRow,
  applySuggestion,
  canAddRow,
  criticalRows,
  criticalSummary,
  levelBlockedReason,
  requiredOverflowNotice,
  requiredRows,
  rowCountHint,
  rowHead,
  setRowLevel,
  suggestedRowKeys,
  type RequirementLevel,
  type RequirementRowForm,
  type RowCriticalState,
} from "@/lib/requirement-rows";
import { useRowCounts } from "@/lib/requirement-rows-api";
import { cn } from "@/lib/utils";

/**
 * Krytyczny wiersz, którego słownik technologii nie zna (narzędzie spoza
 * słownika, branża, język, zdanie): o tym, co jest krytyczne, decyduje
 * Delivery Lead (09.10.2026), a bramka szuka wtedy dosłownie słów wiersza.
 */
export const OUTSIDE_DICTIONARY_NOTE =
  "Spoza słownika technologii — w propozycjach AI zostają osoby, które mają którekolwiek ze słów tego wiersza w profilu, CV albo notatkach.";

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
}

/** Podpowiedzi w wierszu: lista dopiero po wpisaniu tekstu (nie zasłania wiersza niżej). */
const ROW_SUGGEST = { quietWhenEmpty: true } as const;

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
}: RequirementRowsEditorProps) {
  const noCriticalId = useId();
  const shown = useMemo<RequirementRowForm[]>(
    () => (rows.length > 0 ? rows : addRow([])),
    [rows],
  );
  // Wiersz dodany przyciskiem albo Enterem dostaje kursor — od razu można
  // pisać. Ustawiamy go po renderze: wiersz bywa już zamontowany (pusty wiersz
  // pod spodem), więc samo `autoFocus` by nie zadziałało.
  const rootRef = useRef<HTMLDivElement | null>(null);
  const focusKey = useRef<string | null>(null);
  // Po pozycji, nie po kluczu: klucz pustego wiersza startowego powstaje
  // osobno na serwerze i w przeglądarce, więc nie może trafić do atrybutu.
  const focusRow = (index: number) =>
    rootRef.current
      ?.querySelector<HTMLInputElement>(`[data-row-index="${index}"] input[data-keyword-field]`)
      ?.focus();
  useEffect(() => {
    const key = focusKey.current;
    if (!key) return;
    focusKey.current = null;
    const index = shown.findIndex((row) => row.key === key);
    if (index >= 0) focusRow(index);
  });
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  const counts = useRowCounts(shown, exclude, countEnabled && !disabled);
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
  const remove = (key: string) => onRowsChange(shown.filter((row) => row.key !== key));
  const add = () => {
    const next = addRow(shown);
    focusKey.current = next[next.length - 1].key;
    onRowsChange(next);
  };
  /**
   * Enter w wierszu = to wymaganie gotowe, kursor idzie do następnego
   * (09.10.2026: po Enterze kursor zostawał w tym samym wierszu, więc kolejne
   * must-have stawało się wariantem „lub”). Słowo i nowy wiersz idą JEDNĄ
   * zmianą listy — dwie zmiany liczone z tego samego `shown` gubiłyby pierwszą.
   * W środku listy (wiersz niżej już wypełniony) kursor zostaje: tam dopisuje
   * się warianty.
   */
  const commitAndAdvance = (key: string, words?: string[]) => {
    const base = words
      ? shown.map((row) => (row.key === key ? { ...row, words } : row))
      : shown;
    const index = base.findIndex((row) => row.key === key);
    if (index < 0 || base[index].words.length === 0) return;
    const below = base[index + 1];
    if (below && below.words.length === 0) {
      if (words) {
        focusKey.current = below.key;
        onRowsChange(base);
      } else {
        focusRow(index + 1);
      }
      return;
    }
    if (below || !canAddRow(base)) {
      if (words) onRowsChange(base);
      return;
    }
    const next = addRow(base);
    focusKey.current = next[next.length - 1].key;
    onRowsChange(next);
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
          <span>Słowo kluczowe — Enter: następne wymaganie, przecinek: wariant</span>
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
          const criticalTitle =
            row.level === "critical"
              ? undefined
              : (levelBlockedReason(shown, row.key, "critical") ?? undefined);
          const stat = info?.suggested ? statSentence(info.stat) : null;
          // N8 (06.10.2026): liczba osób jest tylko przy wierszach obowiązkowych.
          const countHint =
            countEnabled && row.level !== "nice" && row.words.length > 0
              ? rowCountHint(counts.perRow[row.key])
              : null;
          const rowHints = hints.filter((hint) => hint.row === index);
          return (
            <div key={row.key} data-row-index={index} className="flex flex-col gap-1.5">
              <div className="grid grid-cols-[minmax(0,1fr)_1.5rem] items-start gap-x-3 gap-y-1.5 @xl:grid-cols-[minmax(0,1fr)_auto_5.5rem_1.5rem]">
                <div className="min-w-0">
                  <ChipField
                    layout="inline"
                    joiner="lub"
                    chips={row.words}
                    onChange={(next) => setWords(row.key, next)}
                    placeholder={
                      row.words.length ? "lub… (wariant)" : "np. Java — Enter i wpisujesz kolejne wymaganie"
                    }
                    tone={row.level === "nice" ? "sky" : "emerald"}
                    ariaLabel={`Wymaganie ${index + 1} — słowo albo wariant`}
                    suggest={ROW_SUGGEST}
                    invalid={invalid && index === 0 && row.words.length === 0}
                    acceptWord={acceptRequirementWord}
                    onEnterCommit={(next) => commitAndAdvance(row.key, next)}
                    onSubmitEmpty={() => commitAndAdvance(row.key)}
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
