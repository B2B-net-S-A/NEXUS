"use client";

/**
 * „Strona 1” w edytorze nowego CV (wariant A, decyzja Artura 22.11.2026).
 *
 * - Punkty 1–2 „Dlaczego nasz kandydat” to punkty sekcji `why_points`
 *   W DOKUMENCIE edytora (wspólne z plikiem Word): pole pisze transakcją,
 *   pogrubienia zostają, autozapis, historia i QC działają jak na kartce.
 * - Punkt 3 „Najmocniejszy wynik” to dodatek nowego CV (`page1_extras`):
 *   zdanie rekrutera (`result_text`) albo wybrany sprawdzony wynik
 *   (`result_index`); bez nich strona 1 bierze punkt 3 z treści CV
 *   (`services/cv_layout.compose_page1_why`).
 * - Pozostałe części strony 1 to zwinięte wiersze z podsumowaniem; klik
 *   prowadzi do „Stanowisk” albo do „Cały tekst” na tej sekcji.
 */

import { useEffect, useRef, useState } from "react";
import type { Editor } from "@tiptap/core";
import { Check, ChevronDown, ChevronRight, Loader2, RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { CvPage1Extras, CvPage1Result, CvPage1Update } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import type { CvSectionKey } from "@/lib/cv-editor-blocks";
import { page1Summaries, setWhyPoint, tenureHint, whyPoints } from "@/lib/cv-new-layout-form";
import { cn } from "@/lib/utils";

import { DocTextarea, dispatchCv, useEditorDoc } from "./cv-new-layout-fields";
import { WreathChoice } from "@/components/v2/cv-generator/WreathChoice";

/** Ile czeka zapis zdania „Najmocniejszy wynik” po ostatnim znaku. */
export const RESULT_SAVE_DELAY_MS = 1200;

/**
 * Wynik z odczytu CV niesie pogrubienia jako `**…**` (render strony 1 je
 * rysuje). Pole pokazuje czysty tekst; zdanie poprawione ręcznie zapisuje się
 * bez nich.
 */
export function plainResult(text: string | null | undefined): string {
  return (text ?? "").replace(/\*\*(.+?)\*\*/g, "$1");
}

export interface VerifiedResult {
  index: number;
  result: CvPage1Result;
}

/** Sprawdzone wyniki z listy (tylko te mogą trafić na stronę 1), z numerem w `results`. */
export function verifiedResults(extras: CvPage1Extras | null | undefined): VerifiedResult[] {
  return (extras?.results ?? []).flatMap((result, index) =>
    result && result.verified === true && result.text?.trim() ? [{ index, result }] : [],
  );
}

/** Wynik wybrany z listy — lustro `cv_layout.chosen_result` (bez zdania rekrutera). */
export function chosenResult(extras: CvPage1Extras | null | undefined): VerifiedResult | null {
  const results = extras?.results ?? [];
  if (!results.length) return null;
  const raw = extras?.result_index;
  const index = typeof raw === "number" && raw >= 0 && raw < results.length ? raw : 0;
  const result = results[index];
  return result?.verified === true && result.text?.trim() ? { index, result } : null;
}

export interface CvNewLayoutPage1Props {
  editor: Editor;
  extras: CvPage1Extras | null | undefined;
  disabled: boolean;
  /** Zapis dodatku strony 1; brak = bez pola wyniku (np. CV bez etapu). */
  onSaveResult?: (patch: CvPage1Update) => Promise<void>;
  /** „Policz wyniki od nowa” — model szuka wyników w zapisanym CV; brak = bez przycisku. */
  onRecalcResults?: () => Promise<void>;
  onOpenPositions: () => void;
  onOpenText: (section: CvSectionKey) => void;
}

export function CvNewLayoutPage1({
  editor,
  extras,
  disabled,
  onSaveResult,
  onRecalcResults,
  onOpenPositions,
  onOpenText,
}: CvNewLayoutPage1Props) {
  const { doc } = useEditorDoc(editor);
  const points = whyPoints(doc);
  const summaries = page1Summaries(doc);
  const tenure = tenureHint(doc);

  const editPoint = (index: number) => (value: string) => {
    dispatchCv(editor, setWhyPoint(index, value));
  };

  return (
    <div className="space-y-4 p-4" data-testid="cv-new-page1">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 border-b border-border pb-2">
        <h2 className="text-base font-semibold text-foreground">Strona 1</h2>
        <p className="text-xs text-muted-foreground">podgląd odświeża się kilka sekund po zmianie</p>
      </div>
      <section aria-labelledby="cv-new-why" className="space-y-3">
        <h3 id="cv-new-why" className="flex items-center gap-1.5 text-sm font-semibold text-foreground">
          <ChevronDown aria-hidden className="h-4 w-4 text-muted-foreground" />
          Dlaczego nasz kandydat
        </h3>
        {points.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            CV nie ma punktów „Dlaczego nasz kandydat”. Dopisz je w „Cały tekst” — strona 1 bierze je stamtąd.
          </p>
        ) : null}
        {points[0] ? (
          <DocTextarea
            editor={editor}
            label="1 · Lata doświadczenia"
            value={points[0].text}
            onChange={editPoint(0)}
            disabled={disabled}
            hint={tenure ?? undefined}
          />
        ) : null}
        {points[1] ? (
          <DocTextarea
            editor={editor}
            label="2 · Technologie"
            value={points[1].text}
            onChange={editPoint(1)}
            disabled={disabled}
          />
        ) : null}
        {onSaveResult ? (
          <StrongestResult
            editor={editor}
            extras={extras}
            fallback={points[2]?.text ?? null}
            disabled={disabled}
            onSave={onSaveResult}
            onRecalc={onRecalcResults}
          />
        ) : null}
      </section>
      <nav aria-label="Pozostałe części strony 1" className="divide-y divide-border border-t border-border">
        <SectionRow label="Przebieg kariery" summary={summaries.career} onOpen={onOpenPositions} />
        <SectionRow label="Umiejętności" summary={summaries.skills} onOpen={() => onOpenText("skills")} />
        <SectionRow label="Edukacja" summary={summaries.education} onOpen={() => onOpenText("education")} />
        <SectionRow label="Języki" summary={summaries.languages} onOpen={() => onOpenText("languages")} />
      </nav>
      {onSaveResult ? (
        <WreathChoice
          value={extras?.wreath ?? "auto"}
          onChange={(wreath) => void onSaveResult({ wreath })}
          disabled={disabled}
        />
      ) : null}
    </div>
  );
}

function SectionRow({ label, summary, onOpen }: { label: string; summary: string | null; onOpen: () => void }) {
  return (
    <button
      type="button"
      onClick={onOpen}
      className="flex w-full min-w-0 items-center gap-2 py-2.5 text-left hover:bg-muted/60 focus-visible:outline-hidden focus-visible:bg-muted/60"
    >
      <ChevronRight aria-hidden className="h-4 w-4 flex-none text-muted-foreground" />
      <span className="flex-none text-sm font-medium text-foreground">{label}</span>
      <span className="ml-auto min-w-0 truncate text-xs text-muted-foreground" title={summary ?? undefined}>
        {summary ?? "—"}
      </span>
    </button>
  );
}

function StrongestResult({
  editor,
  extras,
  fallback,
  disabled,
  onSave,
  onRecalc,
}: {
  editor: Editor;
  extras: CvPage1Extras | null | undefined;
  fallback: string | null;
  disabled: boolean;
  onSave: (patch: CvPage1Update) => Promise<void>;
  onRecalc?: () => Promise<void>;
}) {
  const chosen = chosenResult(extras);
  const verified = verifiedResults(extras);
  const typed = extras?.result_text?.trim() || null;
  const shown = plainResult(typed ?? chosen?.result.text ?? "");
  const [draft, setDraft] = useState(shown);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [recalculating, setRecalculating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const draftRef = useRef(draft);
  draftRef.current = draft;

  useEffect(() => {
    if (!dirty) setDraft(shown);
  }, [shown, dirty]);
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );

  const save = async (patch: CvPage1Update, sentText: string | null) => {
    setSaving(true);
    setError(null);
    try {
      await onSave(patch);
      // Rekruter mógł pisać dalej w trakcie zapisu — wtedy pole zostaje „brudne”.
      if (sentText === null || draftRef.current === sentText) setDirty(false);
    } catch (reason) {
      setError(apiErrorMessage(reason, "Nie udało się zapisać wyniku na stronie 1."));
    } finally {
      setSaving(false);
    }
  };
  const flush = () => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
    if (!dirty) return;
    const text = draftRef.current;
    if (text.trim() === shown.trim()) {
      setDirty(false);
      return;
    }
    void save({ result_text: text.trim() || null }, text);
  };
  const change = (value: string) => {
    const text = value.replace(/\s*[\r\n]+\s*/g, " ");
    setDraft(text);
    setDirty(true);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      timer.current = null;
      const current = draftRef.current;
      if (current.trim() === shown.trim()) {
        setDirty(false);
        return;
      }
      void save({ result_text: current.trim() || null }, current);
    }, RESULT_SAVE_DELAY_MS);
  };
  const recalc = async () => {
    if (!onRecalc) return;
    setRecalculating(true);
    setError(null);
    try {
      await onRecalc();
    } catch (reason) {
      setError(apiErrorMessage(reason, "Nie udało się policzyć wyników od nowa."));
    } finally {
      setRecalculating(false);
    }
  };
  const pick = (choice: VerifiedResult) => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
    setDraft(plainResult(choice.result.text));
    void save({ result_index: choice.index, result_text: null }, null);
  };

  const source = typed
    ? "Źródło: wpisane ręcznie · tylko w nowym CV"
    : chosen
      ? `Źródło: ${chosen.result.company?.trim() || "CV kandydata"}, zakres zadań`
      : "Bez wyniku strona 1 pokazuje punkt 3 „Dlaczego nasz kandydat” z treści CV.";

  return (
    <div className="space-y-1.5" data-testid="cv-new-result">
      <DocTextarea
        editor={editor}
        label="3 · Najmocniejszy wynik"
        value={draft}
        onChange={change}
        onBlur={flush}
        editorHistory={false}
        disabled={disabled}
        placeholder={fallback ? `Punkt 3 z CV: ${fallback}` : "Wpisz wynik z liczbą, np. skrócenie testów o 40%"}
      />
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <p className={cn("min-w-48 flex-1 text-xs text-muted-foreground")} title={chosen?.result.quote ?? undefined}>
          {source}
        </p>
        <div className="ml-auto flex flex-wrap items-center justify-end gap-x-2 gap-y-1">
          {saving ? (
            <span role="status" className="flex items-center gap-1 text-xs text-muted-foreground">
              <Loader2 aria-hidden className="h-3 w-3 animate-spin" /> Zapisuję…
            </span>
          ) : null}
          {onRecalc ? (
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={() => void recalc()}
              disabled={disabled || saving || recalculating}
              aria-busy={recalculating}
              className="h-7 rounded-full px-2.5 text-xs"
            >
              {recalculating ? (
                <Loader2 aria-hidden className="mr-1 h-3.5 w-3.5 animate-spin" />
              ) : (
                <RefreshCw aria-hidden className="mr-1 h-3.5 w-3.5" />
              )}
              {recalculating ? "Szukam wyników w CV…" : "Policz wyniki od nowa"}
            </Button>
          ) : null}
          {verified.length > 0 ? (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={disabled || saving || recalculating}
                  className="h-7 rounded-full px-2.5 text-xs"
                >
                  Inny wynik ({verified.length})
                  <ChevronDown aria-hidden className="ml-1 h-3.5 w-3.5" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-80">
                {verified.map((choice) => {
                  const active = !typed && chosen?.index === choice.index;
                  return (
                    <DropdownMenuItem key={choice.index} onSelect={() => pick(choice)} className="items-start gap-2">
                      <Check
                        aria-hidden
                        className={cn("mt-0.5 h-3.5 w-3.5 flex-none", active ? "opacity-100" : "opacity-0")}
                      />
                      <span className="grid min-w-0">
                        <span className="line-clamp-2 text-sm text-foreground">{plainResult(choice.result.text)}</span>
                        {choice.result.company ? (
                          <span className="text-xs text-muted-foreground">{choice.result.company}</span>
                        ) : null}
                      </span>
                    </DropdownMenuItem>
                  );
                })}
              </DropdownMenuContent>
            </DropdownMenu>
          ) : null}
        </div>
      </div>
      {error ? (
        <p role="alert" className="text-xs text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  );
}
