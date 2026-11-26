"use client";

/**
 * „Strona 1” w edytorze nowego CV (wariant A, decyzja Artura 22.11.2026).
 *
 * - Zdania 1–3 „Dlaczego nasz kandydat” (25.11.2026) to dodatek nowego CV
 *   (`page1_extras.why`, trzy sloty): doświadczenie, wymagania klienta,
 *   najważniejsze zadanie. Slot to sprawdzone zdanie generatora strony 1
 *   albo poprawka rekrutera; pusty slot bierze punkt z treści CV (wspólny
 *   z Wordem), w slocie 3 najmocniejszy wynik (`lib/cv-page1-why.ts`,
 *   `services/cv_layout.compose_page1_why`). Treść edytora się nie zmienia.
 * - „Wyróżnik” (25.11.2026) to dodatek `page1_extras.highlight`: jedna rzecz
 *   dająca kandydatowi przewagę, na stronie 1 pod nazwiskiem w wieńcu
 *   laurowym. „Automatycznie” = wcześniejsza praca u klienta rekrutacji.
 *   Od 26.11.2026 obok stoi propozycja AI z CV (`CvNewLayoutHighlightAi`):
 *   trafia do CV dopiero po „Przyjmij” rekrutera (tryb „Propozycja AI”).
 * - Pozostałe części strony 1 to zwinięte wiersze z podsumowaniem; klik
 *   prowadzi do „Stanowisk” albo do „Cały tekst” na tej sekcji.
 */

import { type ReactNode, useEffect, useId, useRef, useState } from "react";
import type { Editor } from "@tiptap/core";
import { Check, ChevronDown, ChevronRight, Loader2, RefreshCw, RotateCcw } from "lucide-react";

import { Input, SegmentedRadio, Textarea } from "@/components/ui";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type {
  CvHighlightMode,
  CvPage1Extras,
  CvPage1Highlight,
  CvPage1Result,
  CvPage1Update,
} from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import type { CvSectionKey } from "@/lib/cv-editor-blocks";
import { page1Summaries, setWhyPoint, tenureHint, whyPoints } from "@/lib/cv-new-layout-form";
import {
  autoTexts,
  chosenResultText,
  fallbackTexts,
  generatedFor,
  isEdited,
  plainText,
  whyPatch,
  whySlots,
} from "@/lib/cv-page1-why";
import { cn } from "@/lib/utils";

import { DocTextarea, dispatchCv, useEditorDoc } from "./cv-new-layout-fields";
import { HighlightAi, pendingProposals } from "./CvNewLayoutHighlightAi";

/** Ile czeka zapis zdania strony 1 (i pól wyróżnika) po ostatnim znaku. */
export const RESULT_SAVE_DELAY_MS = 1200;

/**
 * Wynik z odczytu CV niesie pogrubienia jako `**…**` (render strony 1 je
 * rysuje). Pole pokazuje czysty tekst; zdanie poprawione ręcznie zapisuje się
 * bez nich.
 */
export function plainResult(text: string | null | undefined): string {
  return plainText(text);
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
  /** Zapis dodatków strony 1 (zdania, wyróżnik); brak = bez tych pól (np. CV bez etapu). */
  onSaveResult?: (patch: CvPage1Update) => Promise<void>;
  /**
   * „Ułóż zdania od nowa” — zdania 1–3 i najmocniejsze wyniki z zapisanego CV
   * (ta sama trasa co dawne „Policz wyniki od nowa”); brak = bez przycisku.
   */
  onRecalcResults?: () => Promise<void>;
  /** „Poszukaj w CV” — propozycje AI wyróżnika (ta sama trasa co bieg w tle); brak = bez przycisku. */
  onFindHighlight?: () => Promise<void>;
  onOpenPositions: () => void;
  onOpenText: (section: CvSectionKey) => void;
}

export function CvNewLayoutPage1({
  editor,
  extras,
  disabled,
  onSaveResult,
  onRecalcResults,
  onFindHighlight,
  onOpenPositions,
  onOpenText,
}: CvNewLayoutPage1Props) {
  const { doc } = useEditorDoc(editor);
  const points = whyPoints(doc);
  const summaries = page1Summaries(doc);
  const tenure = tenureHint(doc);

  // Liczenie od nowa trwa kilka sekund: pola zdań czekają, żeby poprawka nie minęła się z wynikiem.
  const [recalculating, setRecalculating] = useState(false);
  const fallback = fallbackTexts(
    points.map((point) => point.text),
    extras,
  );

  return (
    <div className="space-y-4 p-4" data-testid="cv-new-page1">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 border-b border-border pb-2">
        <h2 className="text-base font-semibold text-foreground">Strona 1</h2>
        <p className="text-xs text-muted-foreground">podgląd odświeża się kilka sekund po zmianie</p>
      </div>
      {onSaveResult ? (
        <HighlightChoice extras={extras} disabled={disabled} onSave={onSaveResult} onFind={onFindHighlight} />
      ) : null}
      <section aria-labelledby="cv-new-why" className="space-y-3" data-tour="cv-editor.page1.why">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <h3 id="cv-new-why" className="flex items-center gap-1.5 text-sm font-semibold text-foreground">
            <ChevronDown aria-hidden className="h-4 w-4 text-muted-foreground" />
            Dlaczego nasz kandydat
          </h3>
          {onRecalcResults ? (
            <RefreshWhy
              disabled={disabled}
              busy={recalculating}
              onBusy={setRecalculating}
              onRefresh={onRecalcResults}
            />
          ) : null}
        </div>
        {onSaveResult ? (
          WHY_FIELDS.map((field, index) => (
            <WhySentence
              key={field.label}
              editor={editor}
              index={index}
              label={field.label}
              extras={extras}
              fallback={fallback[index]}
              disabled={disabled || recalculating}
              onSave={onSaveResult}
              hint={index === 0 ? (tenure ?? undefined) : undefined}
            />
          ))
        ) : (
          // CV bez dodatków strony 1 (bez etapu): punkty z treści CV, jak w Wordzie.
          points.slice(0, 3).map((point, index) => (
            <DocTextarea
              key={WHY_FIELDS[index].label}
              editor={editor}
              label={WHY_FIELDS[index].label}
              value={point.text}
              onChange={(value) => dispatchCv(editor, setWhyPoint(index, value))}
              disabled={disabled}
              hint={index === 0 ? (tenure ?? undefined) : undefined}
            />
          ))
        )}
      </section>
      <nav aria-label="Pozostałe części strony 1" className="divide-y divide-border border-t border-border">
        <SectionRow label="Przebieg kariery" summary={summaries.career} onOpen={onOpenPositions} />
        <SectionRow label="Umiejętności" summary={summaries.skills} onOpen={() => onOpenText("skills")} />
        <SectionRow label="Edukacja" summary={summaries.education} onOpen={() => onOpenText("education")} />
        <SectionRow label="Języki" summary={summaries.languages} onOpen={() => onOpenText("languages")} />
      </nav>
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

const WHY_FIELDS = [
  { label: "1 · Doświadczenie", point: "punkt 1" },
  { label: "2 · Wymagania klienta", point: "punkt 2" },
  { label: "3 · Najważniejsze zadanie", point: "punkt 3" },
] as const;

/** Skąd jest zdanie w slocie — jedno zdanie pod polem. */
function whySource(extras: CvPage1Extras | null | undefined, index: number, fallback: string): string {
  if (isEdited(extras, index)) return "Wpisane ręcznie · tylko w nowym CV";
  const item = generatedFor(extras, index);
  if (whySlots(extras)[index] && item?.verified) {
    if (index === 0) return "Z generatora · lata policzone z dat stanowisk";
    if (index === 1) {
      const proof = (item.evidence ?? []).map((e) => `${e.must} (${e.company})`).join(", ");
      return proof ? `Z generatora · potwierdzone w CV: ${proof}` : "Z generatora";
    }
    return item.source === "screening"
      ? "Z generatora · dowód z odpowiedzi kandydata na screeningu"
      : `Z generatora · dowód z CV${item.company ? ` (${item.company})` : ""}`;
  }
  const point = WHY_FIELDS[index].point;
  if (index === 2 && item?.issue === "no_input") {
    return "Rekrutacja nie ma „Najważniejszego zadania” — strona 1 bierze najmocniejszy wynik albo punkt 3 z CV.";
  }
  if (index === 1 && item?.issue === "no_input") {
    return "Profil Championa nie ma wymagań MUST — strona 1 bierze punkt 2 z CV.";
  }
  if (item && !item.verified && item.issue !== "empty") {
    return `Zdanie z generatora nie przeszło sprawdzenia z CV — strona 1 bierze ${point} z CV.`;
  }
  if (!fallback) return "Brak zdania — wpisz je albo dopisz punkty w „Cały tekst”.";
  if (index === 2 && chosenResultText(extras)) return "Najmocniejszy wynik z CV";
  return `${point[0].toUpperCase()}${point.slice(1)} z treści CV (wspólny z Wordem)`;
}

function WhySentence({
  editor,
  index,
  label,
  extras,
  fallback,
  disabled,
  hint,
  onSave,
}: {
  editor: Editor;
  index: number;
  label: string;
  extras: CvPage1Extras | null | undefined;
  fallback: string;
  disabled: boolean;
  hint?: ReactNode;
  onSave: (patch: CvPage1Update) => Promise<void>;
}) {
  const slot = whySlots(extras)[index];
  const shown = plainText(slot || fallback);
  const edited = isEdited(extras, index);
  const [draft, setDraft] = useState(shown);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const draftRef = useRef(draft);
  draftRef.current = draft;
  const shownRef = useRef(shown);
  shownRef.current = shown;

  useEffect(() => {
    if (!dirty) setDraft(shown);
  }, [shown, dirty]);
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );

  const stopTimer = () => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
  };
  /** `sent` = tekst z pola, który poszedł; `null` = przycisk (przywróć, inny wynik). */
  const save = async (text: string, sent: string | null) => {
    setSaving(true);
    setError(null);
    try {
      await onSave({ why: whyPatch(index, text) });
      // Rekruter mógł pisać dalej w trakcie zapisu — wtedy pole zostaje „brudne”.
      if (sent === null || draftRef.current === sent) setDirty(false);
    } catch (reason) {
      setError(apiErrorMessage(reason, "Nie udało się zapisać zdania na stronie 1."));
    } finally {
      setSaving(false);
    }
  };
  const saveDraft = () => {
    const text = draftRef.current;
    if (text.trim() === shownRef.current.trim()) {
      setDirty(false);
      return;
    }
    void save(text.trim(), text);
  };
  const change = (value: string) => {
    const text = value.replace(/\s*[\r\n]+\s*/g, " ");
    setDraft(text);
    setDirty(true);
    stopTimer();
    timer.current = setTimeout(() => {
      timer.current = null;
      saveDraft();
    }, RESULT_SAVE_DELAY_MS);
  };
  const flush = () => {
    stopTimer();
    if (dirty) saveDraft();
  };
  const restore = () => {
    stopTimer();
    setDirty(false);
    void save("", null);
  };
  const pick = (choice: VerifiedResult) => {
    stopTimer();
    setDraft(plainText(choice.result.text));
    void save(choice.result.text, null);
  };
  const results = index === 2 ? verifiedResults(extras) : [];
  const auto = autoTexts(extras)[index];
  const quote = generatedFor(extras, index)?.quote ?? undefined;

  return (
    <div className="space-y-1.5" data-testid={`cv-new-why-${index + 1}`}>
      <DocTextarea
        editor={editor}
        label={label}
        value={draft}
        onChange={change}
        onBlur={flush}
        editorHistory={false}
        disabled={disabled}
        hint={hint}
        placeholder="Wpisz zdanie na stronę 1"
      />
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <p className="min-w-0 basis-full text-xs text-muted-foreground" title={quote}>
          {whySource(extras, index, fallback)}
        </p>
        {saving ? (
          <span role="status" className="flex items-center gap-1 text-xs text-muted-foreground">
            <Loader2 aria-hidden className="h-3 w-3 animate-spin" /> Zapisuję…
          </span>
        ) : null}
        {edited ? (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            disabled={disabled}
            // Bez zabrania fokusu: wyjście z pola zapisałoby poprawkę i zablokowało przycisk.
            onMouseDown={(event) => event.preventDefault()}
            onClick={restore}
            className="h-7 rounded-full px-2.5 text-xs"
            data-tour="cv-editor.page1.restore"
            title={auto ? plainText(auto) : `Strona 1 weźmie ${WHY_FIELDS[index].point} z treści CV`}
          >
            <RotateCcw aria-hidden className="mr-1 h-3.5 w-3.5" />
            Przywróć z generatora
          </Button>
        ) : null}
        {results.length > 0 ? (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={disabled || saving}
                className="h-7 rounded-full px-2.5 text-xs"
              >
                Wynik z CV ({results.length})
                <ChevronDown aria-hidden className="ml-1 h-3.5 w-3.5" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-80">
              {results.map((choice) => {
                const active = slot === choice.result.text.trim();
                return (
                  <DropdownMenuItem key={choice.index} onSelect={() => pick(choice)} className="items-start gap-2">
                    <Check
                      aria-hidden
                      className={cn("mt-0.5 h-3.5 w-3.5 flex-none", active ? "opacity-100" : "opacity-0")}
                    />
                    <span className="grid min-w-0">
                      <span className="line-clamp-2 text-sm text-foreground">{plainText(choice.result.text)}</span>
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
      {error ? (
        <p role="alert" className="text-xs text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  );
}

function RefreshWhy({
  disabled,
  busy,
  onBusy,
  onRefresh,
}: {
  disabled: boolean;
  busy: boolean;
  onBusy: (busy: boolean) => void;
  onRefresh: () => Promise<void>;
}) {
  const [error, setError] = useState<string | null>(null);
  const run = async () => {
    onBusy(true);
    setError(null);
    try {
      await onRefresh();
    } catch (reason) {
      setError(apiErrorMessage(reason, "Nie udało się ułożyć zdań od nowa. Spróbuj za chwilę."));
    } finally {
      onBusy(false);
    }
  };
  return (
    <div className="ml-auto flex min-w-0 flex-wrap items-center justify-end gap-x-2 gap-y-1">
      <Button
        type="button"
        size="sm"
        variant="outline"
        disabled={disabled || busy}
        aria-busy={busy}
        onClick={() => void run()}
        className="h-7 rounded-full px-2.5 text-xs"
        data-tour="cv-editor.page1.refresh"
        title="Zdania poprawione ręcznie zostają"
      >
        {busy ? (
          <Loader2 aria-hidden className="mr-1 h-3.5 w-3.5 animate-spin" />
        ) : (
          <RefreshCw aria-hidden className="mr-1 h-3.5 w-3.5" />
        )}
        {busy ? "Układam zdania…" : "Ułóż zdania od nowa"}
      </Button>
      {error ? (
        <p role="alert" className="basis-full text-right text-xs text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  );
}

/** Limity jak w `PATCH …/cv/page1`. */
export const HIGHLIGHT_LIMITS = { label: 60, token: 8, text: 160 } as const;

function highlightOptions(canPickAi: boolean): { value: CvHighlightMode; label: string; disabled?: boolean; title?: string }[] {
  return [
    { value: "auto", label: "Automatycznie" },
    {
      value: "ai",
      label: "Propozycja AI",
      disabled: !canPickAi,
      title: canPickAi ? undefined : "Brak propozycji z CV do przyjęcia",
    },
    { value: "custom", label: "Własny" },
    { value: "off", label: "Bez wyróżnika" },
  ];
}

interface HighlightDraft {
  label: string;
  token: string;
  text: string;
}

function highlightDraft(highlight: CvPage1Highlight | null | undefined): HighlightDraft {
  return { label: highlight?.label ?? "", token: highlight?.token ?? "", text: highlight?.text ?? "" };
}

/** Komplet „Własnego” do zapisu; bez etykiety albo zdania serwer odda 422, więc nie wysyłamy. */
function customHighlight(draft: HighlightDraft): CvPage1Highlight | null {
  const label = draft.label.trim();
  const text = draft.text.trim();
  if (!label || !text) return null;
  return { mode: "custom", label, token: draft.token.trim() || null, text };
}

function HighlightChoice({
  extras,
  disabled,
  onSave,
  onFind,
}: {
  extras: CvPage1Extras | null | undefined;
  disabled: boolean;
  onSave: (patch: CvPage1Update) => Promise<void>;
  onFind?: () => Promise<void>;
}) {
  const saved = extras?.highlight ?? null;
  const savedMode: CvHighlightMode = saved?.mode ?? "auto";
  const savedLabel = saved?.label ?? "";
  const savedToken = saved?.token ?? "";
  const savedText = saved?.text ?? "";
  const [mode, setMode] = useState<CvHighlightMode>(savedMode);
  const [draft, setDraft] = useState<HighlightDraft>(() => highlightDraft(saved));
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const draftRef = useRef(draft);
  const savedRef = useRef({ mode: savedMode, label: savedLabel, token: savedToken, text: savedText });
  savedRef.current = { mode: savedMode, label: savedLabel, token: savedToken, text: savedText };
  const ids = useId();

  useEffect(() => {
    setMode(savedMode);
  }, [savedMode]);
  useEffect(() => {
    if (dirty) return;
    const next = { label: savedLabel, token: savedToken, text: savedText };
    draftRef.current = next;
    setDraft(next);
  }, [savedLabel, savedToken, savedText, dirty]);
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );

  /** `sent` = szkic „Własnego”, który poszedł; `null` = sam wybór trybu (albo propozycji). */
  const save = async (patch: CvPage1Update, sent: HighlightDraft | null) => {
    setSaving(true);
    setError(null);
    try {
      await onSave(patch);
      // Rekruter mógł pisać dalej w trakcie zapisu — wtedy pola zostają „brudne”.
      if (sent === null || draftRef.current === sent) setDirty(false);
    } catch (reason) {
      setError(apiErrorMessage(reason, "Nie udało się zapisać wyróżnika na stronie 1."));
      if (sent === null) setMode(savedRef.current.mode);
    } finally {
      setSaving(false);
    }
  };
  const saveCustom = () => {
    const current = draftRef.current;
    const highlight = customHighlight(current);
    if (!highlight) return;
    const last = savedRef.current;
    if (
      last.mode === "custom" &&
      highlight.label === last.label.trim() &&
      (highlight.token ?? "") === last.token.trim() &&
      highlight.text === last.text.trim()
    ) {
      setDirty(false);
      return;
    }
    void save({ highlight }, current);
  };
  const stopTimer = () => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
  };
  const pending = pendingProposals(extras);
  /** „Przyjmij”: propozycja AI na stronę 1 (serwer sprawdza cytat jeszcze raz). */
  const accept = (index: number) => {
    stopTimer();
    setMode("ai");
    void save({ highlight: { mode: "ai", proposal: index } }, null);
  };
  /** „Odrzuć”: znika i nie wraca; odrzucona przyjęta wraca do automatu (tryb idzie za zapisem). */
  const reject = (index: number) => {
    stopTimer();
    void save({ highlight_reject: index }, null);
  };
  /** „Popraw jako własny”: słowa propozycji w polach „Własnego”, zapis od razu. */
  const editAsCustom = (proposal: { label?: string | null; token?: string | null; text?: string | null }) => {
    stopTimer();
    const next = {
      label: (proposal.label ?? "").slice(0, HIGHLIGHT_LIMITS.label),
      token: (proposal.token ?? "").slice(0, HIGHLIGHT_LIMITS.token),
      text: plainText(proposal.text).slice(0, HIGHLIGHT_LIMITS.text),
    };
    draftRef.current = next;
    setDraft(next);
    setDirty(true);
    setMode("custom");
    setError(null);
    saveCustom();
  };
  const pick = (next: CvHighlightMode) => {
    if (next === mode) return;
    stopTimer();
    setError(null);
    if (next === "ai") {
      // Wybór trybu = przyjęcie pierwszej propozycji z listy niżej.
      if (pending.length) accept(pending[0].index);
      return;
    }
    setMode(next);
    if (next === "custom") {
      saveCustom();
      return;
    }
    if (next === savedRef.current.mode) return;
    void save({ highlight: { mode: next } }, null);
  };
  const change = (field: keyof HighlightDraft) => (value: string) => {
    const clean = field === "text" ? value.replace(/\s*[\r\n]+\s*/g, " ") : value;
    const next = { ...draftRef.current, [field]: clean };
    draftRef.current = next;
    setDraft(next);
    setDirty(true);
    stopTimer();
    timer.current = setTimeout(() => {
      timer.current = null;
      saveCustom();
    }, RESULT_SAVE_DELAY_MS);
  };
  const flush = () => {
    stopTimer();
    if (dirty) saveCustom();
  };

  const incomplete = mode === "custom" && !customHighlight(draft);

  return (
    <section aria-labelledby={`${ids}-title`} className="space-y-2" data-testid="cv-new-highlight" data-tour="cv-editor.page1.highlight">
      <h3 id={`${ids}-title`} className="flex items-center gap-1.5 text-sm font-semibold text-foreground">
        <ChevronDown aria-hidden className="h-4 w-4 text-muted-foreground" />
        Wyróżnik
      </h3>
      <p className="text-xs text-muted-foreground">Jedna rzecz, która daje przewagę — pod nazwiskiem, w wieńcu.</p>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <SegmentedRadio<CvHighlightMode>
          label="Wyróżnik"
          size="sm"
          value={mode}
          onChange={pick}
          options={highlightOptions(mode === "ai" || pending.length > 0)}
          disabled={disabled || saving}
        />
        {saving ? (
          <span role="status" className="flex items-center gap-1 text-xs text-muted-foreground">
            <Loader2 aria-hidden className="h-3 w-3 animate-spin" /> Zapisuję…
          </span>
        ) : null}
      </div>
      {mode === "auto" ? (
        <p className="text-xs leading-relaxed text-muted-foreground">
          Gdy kandydat pracował wcześniej u klienta tej rekrutacji, strona 1 pokaże to pod nazwiskiem, np.
          „Doświadczenie w PKO BP · 2018–2023”. Bez takiej pracy wyróżnika nie ma.
        </p>
      ) : null}
      {mode === "off" ? (
        <p className="text-xs text-muted-foreground">Strona 1 nie pokaże wyróżnika pod nazwiskiem.</p>
      ) : null}
      {mode === "ai" ? (
        <p className="text-xs leading-relaxed text-muted-foreground">
          Strona 1 pokaże przyjętą propozycję z CV. Gdy rekruter usunie z CV jej fragment, strona 1 wróci do automatu.
        </p>
      ) : null}
      {mode === "custom" ? (
        <div className="space-y-2">
          <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_9rem]">
            <HighlightField id={`${ids}-label`} label="Etykieta" value={draft.label} max={HIGHLIGHT_LIMITS.label}>
              <Input
                id={`${ids}-label`}
                value={draft.label}
                maxLength={HIGHLIGHT_LIMITS.label}
                placeholder="np. Wyróżnienie"
                disabled={disabled}
                onChange={(event) => change("label")(event.target.value)}
                onBlur={flush}
                className="h-9"
              />
            </HighlightField>
            <HighlightField id={`${ids}-token`} label="Znak w wieńcu" value={draft.token} max={HIGHLIGHT_LIMITS.token}>
              <Input
                id={`${ids}-token`}
                value={draft.token}
                maxLength={HIGHLIGHT_LIMITS.token}
                placeholder="np. 2015 albo PMP"
                disabled={disabled}
                onChange={(event) => change("token")(event.target.value)}
                onBlur={flush}
                className="h-9"
              />
            </HighlightField>
          </div>
          <HighlightField id={`${ids}-text`} label="Zdanie" value={draft.text} max={HIGHLIGHT_LIMITS.text}>
            <Textarea
              id={`${ids}-text`}
              rows={2}
              value={draft.text}
              maxLength={HIGHLIGHT_LIMITS.text}
              placeholder="np. Best IT Project Manager klastra bałtyckiego Nordea za inicjatywę KYC."
              disabled={disabled}
              onChange={(event) => change("text")(event.target.value)}
              onBlur={flush}
              className="min-h-0 resize-none"
            />
          </HighlightField>
          {incomplete ? (
            <p className="text-xs text-muted-foreground">Uzupełnij etykietę i zdanie — wtedy wyróżnik się zapisze.</p>
          ) : null}
        </div>
      ) : null}
      {error ? (
        <p role="alert" className="text-xs text-destructive">
          {error}
        </p>
      ) : null}
      <HighlightAi
        extras={extras}
        disabled={disabled}
        saving={saving}
        onAccept={accept}
        onReject={reject}
        onEdit={editAsCustom}
        onFind={onFind}
      />
    </section>
  );
}

function HighlightField({
  id,
  label,
  value,
  max,
  children,
}: {
  id: string;
  label: string;
  value: string;
  max: number;
  children: ReactNode;
}) {
  return (
    <div className="min-w-0 space-y-1">
      <div className="flex items-baseline justify-between gap-2">
        <label htmlFor={id} className="text-xs font-medium text-foreground">
          {label}
        </label>
        <span
          aria-hidden
          className={cn("text-xs tabular-nums", value.length >= max ? "text-foreground" : "text-muted-foreground")}
        >
          {value.length}/{max}
        </span>
      </div>
      {children}
    </div>
  );
}
