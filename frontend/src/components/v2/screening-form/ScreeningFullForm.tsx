"use client";

/**
 * Jeden formularz screeningu pary (0424, decyzje Artura D1–D10, 07.10.2026).
 *
 * Do tej pory po rozmowie z kandydatem rekruter wypełniał trzy miejsca:
 * arkusz Championa (z polem „Notatki rekrutera”, które widział klient),
 * ręczne pola karty rekomendacji w osobnym oknie i stawkę w oknie ruchu na
 * „Zweryfikowany”. Teraz jest jeden formularz w trzech sekcjach — „Pytania”,
 * „Warunki” (pola karty + stawka kandydata) i „Ocena” (ogólne dopasowanie
 * i pola opisowe karty) — zapisywany jednym `PUT /api/screening-form`
 * z wersją. Wszystko w nim jest dla Delivery Leada; nic nie idzie do klienta.
 *
 * Trzy części:
 * - `useScreeningFormModel` — stan po stronie przeglądarki (jeden `useForm`,
 *   hydratacja z serwera, wypełnienie z notatki, pochodzenie pól), bez zapytań;
 * - `ScreeningFullFormView` — sam widok (harness `/preview/screening-form`);
 * - `ScreeningFullForm` — zapis, ruch „Zapisz i przekaż dalej”, odrzucenie.
 *
 * Konflikt wersji (ktoś zapisał w międzyczasie) nie kasuje pracy: formularz
 * wczytuje nowszy stan i zostawia niezapisane zmiany (`keepDirtyValues`).
 * Odświeżenie w tle robi to samo: pola, których rekruter nie ruszył, pokazują
 * świeże wartości z serwera, a zapis liczy różnice i odsyła `state_token`
 * względem tego samego stanu, który widać w polach (`baseState`).
 */

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { FormProvider, useForm, type Path, type UseFormReturn } from "react-hook-form";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowRight, Ban, Clock, History, Loader2, Lock, Save, StickyNote } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { FormField, TextField, TextareaField } from "@/components/v2/forms";
import { ScreeningReassignSuggestions } from "@/components/v2/jobs/ScreeningReassignSuggestions";
import { RejectionV2, type CandidateOfferResponse } from "@/components/v2/modals/RejectionV2";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";
import { PhraseAllBar } from "@/components/v2/screening/PhraseAllBar";
import {
  PhraseButton,
  PhraseProposal,
  usePhraseSuggestions,
  type PhraseController,
} from "@/components/v2/screening/PhraseSuggestion";
import {
  OverallFitField,
  ScreeningFormFields,
  ScreeningNoQuestions,
  ScreeningSubmitError,
  type ScreeningFormValues,
} from "@/components/v2/screening/ScreeningForm";
import { ScreeningAnswersList } from "@/components/v2/screening/ScreeningAnswersList";
import { ScreeningSuggestionChips } from "@/components/v2/screening/ScreeningSuggestionChips";
import { VerifiedRateFields } from "@/components/v2/screening/VerifiedRateFields";
import { useCapability } from "@/hooks/useCapability";
import { usePipelineMoveCore } from "@/hooks/usePipelineMoveCore";
import { candidatesApi, type RateUnit, type ScreeningQuestion } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import type { NoteProposal } from "@/lib/api/recommendationCards";
import {
  isScreeningFormReadOnly,
  screeningFormConflictOf,
  screeningFormQueryKey,
  useRestoreScreeningForm,
  useSaveScreeningForm,
  useScreeningFormState,
  type FormRate,
  type ScreeningFormSaveResult,
  type ScreeningFormState,
} from "@/lib/api/screeningForm";
import { countPl } from "@/lib/plural-pl";
import {
  CARD_FIELD_HINT,
  CARD_PHRASABLE_FIELDS,
  cardFieldSource,
  cardFieldValue,
} from "@/lib/recommendation-card";
import { loadJobRejectionReasons, type RejectionReasonOption } from "@/lib/rejection-reasons";
import {
  answerOriginAfterEdit,
  applyNoteProposal,
  buildSavePayload,
  cardAssessmentKeys,
  cardOriginAfterEdit,
  cardTermsKeys,
  editableCardKeys,
  fillPatches,
  formatFormRate,
  formDefaultsFromState,
  formFieldLabel,
  formQuestions,
  mergeLegacyNote,
  missingAnswersForForward,
  rateFromValues,
  rateNotRestoredMessage,
  type NoteFill,
  type NoteHint,
  type NoteImport,
  type NoteOffer,
  type ScreeningFullFormValues,
} from "@/lib/screening-form";
import type { ScreeningSuggestions } from "@/lib/screening-suggestions";
import { cn } from "@/lib/utils";
import { evaluateRateGate } from "@/lib/verified-rate-gate";
import { fixFieldState } from "@/lib/screening-fix-request";

import { FixMark, FixRequestBanner } from "./FixRequestBanner";
import { NoteFillBar } from "./NoteFillBar";
import { ScreeningFormHistory } from "./ScreeningFormHistory";

const EMPTY_VALUES: ScreeningFullFormValues = {
  answers: {},
  overall_fit: "uncertain",
  notes: "",
  skip_missing: false,
  internal_note: "",
  experience_checks: [],
  card: {},
  card_origins: {},
  rate_amount: "",
  rate_unit: "hourly",
  rate_currency: "PLN",
  clear_legacy_notes: false,
};

const SET = { shouldDirty: true } as const;

/** Arkusz screeningu (`ScreeningFormFields`) zna tylko swoją część wartości. */
function sheetMethods(
  methods: UseFormReturn<ScreeningFullFormValues>,
): UseFormReturn<ScreeningFormValues> {
  return methods as unknown as UseFormReturn<ScreeningFormValues>;
}

const DATE_TIME = new Intl.DateTimeFormat("pl-PL", { dateStyle: "short", timeStyle: "short" });

function shortDateTime(value: string | null | undefined): string | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : DATE_TIME.format(date);
}

// ── Model: stan formularza po stronie przeglądarki ───────────────────────

export interface NoteState {
  source: NoteImport;
  filled: number;
  /** Poprzednie wartości miejsc wypełnionych z notatki — „Cofnij wypełnienie”. */
  undo: Array<[string, unknown]>;
}

export interface ScreeningFormModel {
  methods: UseFormReturn<ScreeningFullFormValues>;
  questions: ScreeningQuestion[];
  note: NoteState | null;
  offers: NoteOffer[];
  hints: NoteHint[];
  /** Stawka wpisana z notatki (plakietka przy polu). */
  rateFromNote: boolean;
  notice: string | null;
  setNotice: (notice: string | null) => void;
  /** Wypełnia puste miejsca z notatki; mówi, ile wypełnił i ile czeka na „Użyj”. */
  applyNote: (
    proposal: Pick<NoteProposal, "fields" | "answers">,
    source: NoteImport,
  ) => { filled: number; offers: number };
  acceptOffer: (id: string) => void;
  dismissOffer: (id: string) => void;
  undoNote: () => void;
  /** Własny zapis albo przywrócenie — przed odświeżeniem cache. */
  markSaved: (result: ScreeningFormState) => void;
  /**
   * Stan, z którego formularz wziął wartości startowe — względem niego zapis
   * liczy różnice i jego `state_token` odsyła (`null` przed pierwszym stanem).
   */
  baseState: () => ScreeningFormState | null;
}

export function useScreeningFormModel(state: ScreeningFormState | undefined): ScreeningFormModel {
  const methods = useForm<ScreeningFullFormValues>({
    defaultValues: state ? formDefaultsFromState(state) : EMPTY_VALUES,
  });
  const [note, setNote] = useState<NoteState | null>(null);
  const [offers, setOffers] = useState<NoteOffer[]>([]);
  const [hints, setHints] = useState<NoteHint[]>([]);
  const [rateFromNote, setRateFromNote] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const questions = useMemo(() => (state ? formQuestions(state) : []), [state]);

  // Subskrypcja `isDirty` w renderze — efekt hydratacji czyta świeżą wartość.
  const dirty = methods.formState.isDirty;
  const dirtyRef = useRef(dirty);
  dirtyRef.current = dirty;

  const clearNote = useCallback(() => {
    setNote(null);
    setOffers([]);
    setHints([]);
    setRateFromNote(false);
  }, []);

  const hydrated = useRef<{ key: string; version: number; state: ScreeningFormState } | null>(null);
  useEffect(() => {
    if (!state) return;
    const key = `${state.candidate_id}:${state.job_id}`;
    const prev = hydrated.current;
    if (prev && prev.state === state) return;
    hydrated.current = { key, version: state.version, state };
    if (prev && prev.key === key && dirtyRef.current) {
      // Odświeżenie w tle przy niezapisanych zmianach: pola nieruszone biorą
      // świeże wartości, ruszone zostają — i różnice zapisu liczą się od tego
      // samego stanu, który widać w polach (inaczej nieruszone pole ze starą
      // wartością cofnęłoby zmianę zrobioną obok formularza).
      methods.reset(formDefaultsFromState(state), { keepDirtyValues: true });
      if (prev.version !== state.version) {
        setNotice(
          (current) =>
            current ??
            "Ktoś zapisał ten formularz w międzyczasie — wczytałem nowszą wersję, Twoje niezapisane zmiany zostały. Sprawdź je i zapisz.",
        );
      } else if (prev.state.state_token !== state.state_token) {
        setNotice(
          (current) =>
            current ??
            "Ktoś zmienił dane tej osoby obok formularza — wczytałem je, Twoje niezapisane zmiany zostały. Sprawdź je i zapisz.",
        );
      }
      return;
    }
    methods.reset(formDefaultsFromState(state));
    if (!prev || prev.key !== key) {
      clearNote();
      setNotice(null);
    }
  }, [state, methods, clearNote]);

  const markSaved = useCallback(
    (result: ScreeningFormState) => {
      hydrated.current = {
        key: `${result.candidate_id}:${result.job_id}`,
        version: result.version,
        state: result,
      };
      methods.reset(formDefaultsFromState(result));
      clearNote();
      setNotice(null);
    },
    [methods, clearNote],
  );

  const baseState = useCallback(() => hydrated.current?.state ?? null, []);

  // Ręczna poprawka zdejmuje pochodzenie „z notatki” / „z podpowiedzi”.
  useEffect(() => {
    const subscription = methods.watch((_values, { name, type }) => {
      if (type !== "change" || !name) return;
      const answer = /^answers\.(.+)\.response$/.exec(name);
      if (answer) {
        const id = answer[1];
        const next = answerOriginAfterEdit(
          methods.getValues(`answers.${id}.origin`),
          methods.getValues(`answers.${id}.response`) ?? "",
        );
        if (next) {
          methods.setValue(`answers.${id}.origin`, next, SET);
          methods.setValue(`answers.${id}.keywords`, null, SET);
        }
        return;
      }
      const card = /^card\.(.+)$/.exec(name);
      if (card) {
        const key = card[1];
        const verdict = cardOriginAfterEdit(
          methods.getValues(`card_origins.${key}`),
          methods.getValues(`card.${key}`) ?? "",
        );
        if (verdict === "clear") methods.setValue(`card_origins.${key}`, null, SET);
        return;
      }
      if (name === "rate_amount") setRateFromNote(false);
    });
    return () => subscription.unsubscribe();
  }, [methods]);

  const applyFill = useCallback(
    (fill: NoteFill, undo?: Array<[string, unknown]>) => {
      for (const [path, value] of fillPatches(fill)) {
        const typed = path as Path<ScreeningFullFormValues>;
        if (undo && !undo.some(([p]) => p === path)) undo.push([path, methods.getValues(typed)]);
        methods.setValue(typed, value as never, SET);
      }
      if (fill.kind === "rate") setRateFromNote(true);
    },
    [methods],
  );

  const applyNote = useCallback<ScreeningFormModel["applyNote"]>(
    (proposal, source) => {
      if (!state) return { filled: 0, offers: 0 };
      const result = applyNoteProposal(methods.getValues(), proposal, {
        editableCardKeys: editableCardKeys(state),
        canEditRate: state.can_edit_rate,
        questionIds: questions.map((q) => q.id),
      });
      const undo: Array<[string, unknown]> = [];
      for (const fill of result.fills) applyFill(fill, undo);
      setNote({ source, filled: result.fills.length, undo });
      setOffers(result.offers);
      setHints(result.hints);
      return { filled: result.fills.length, offers: result.offers.length };
    },
    [state, methods, questions, applyFill],
  );

  const acceptOffer = useCallback(
    (id: string) => {
      const offer = offers.find((o) => o.id === id);
      if (!offer) return;
      // Przyjęta propozycja też wraca przy „Cofnij wypełnienie”.
      applyFill(offer, note?.undo);
      setOffers((prev) => prev.filter((o) => o.id !== id));
    },
    [offers, applyFill, note],
  );

  const dismissOffer = useCallback((id: string) => {
    setOffers((prev) => prev.filter((o) => o.id !== id));
  }, []);

  const undoNote = useCallback(() => {
    for (const [path, value] of [...(note?.undo ?? [])].reverse()) {
      methods.setValue(path as Path<ScreeningFullFormValues>, value as never, SET);
    }
    clearNote();
  }, [note, methods, clearNote]);

  return {
    methods,
    questions,
    note,
    offers,
    hints,
    rateFromNote,
    notice,
    setNotice,
    applyNote,
    acceptOffer,
    dismissOffer,
    undoNote,
    markSaved,
    baseState,
  };
}

// ── Widok ────────────────────────────────────────────────────────────────

function SectionTitle({ children, hint }: { children: ReactNode; hint?: ReactNode }) {
  return (
    <div className="space-y-0.5">
      <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">{children}</h3>
      {hint ? <p className="text-[11px] text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

function OfferChip({
  offer,
  onUse,
  onDismiss,
}: {
  offer: NoteOffer;
  onUse: () => void;
  onDismiss: () => void;
}) {
  return (
    <div
      data-testid="note-offer"
      className="flex flex-wrap items-center gap-2 rounded-md border border-primary/30 bg-primary/5 px-2.5 py-1.5 text-xs"
    >
      <StickyNote className="h-3 w-3 shrink-0 text-primary" aria-hidden />
      <span className="min-w-0 flex-1 [overflow-wrap:anywhere]">
        Z notatki: <span className="font-medium text-foreground">{offer.text}</span>
      </span>
      <Button type="button" size="sm" variant="outline" onClick={onUse} aria-label={`Użyj z notatki: ${offer.label}`}>
        Użyj
      </Button>
      <Button type="button" size="sm" variant="ghost" onClick={onDismiss}>
        Zostaw
      </Button>
    </div>
  );
}

const ORIGIN_CAPTION: Record<string, string> = {
  note_ai: "z notatki (AI)",
  note_rule: "z notatki",
  phrased: "zdanie z haseł",
};

function HintChip({ text, onUse, label }: { text: string; onUse?: () => void; label: string }) {
  return (
    <span className="inline-flex max-w-full items-center gap-1.5 rounded-full border border-border bg-muted/40 px-2 py-0.5 text-[11px] text-muted-foreground">
      <span className="min-w-0 truncate" title={text}>
        {label}: <span className="font-medium text-foreground">{text}</span>
      </span>
      {onUse ? (
        <button
          type="button"
          onClick={onUse}
          aria-label={`Użyj — ${label}`}
          className="shrink-0 font-semibold text-primary hover:underline"
        >
          Użyj
        </button>
      ) : null}
    </span>
  );
}

export interface ScreeningFullFormViewProps {
  state: ScreeningFormState;
  model: ScreeningFormModel;
  jobBudgetHourly: number | null;
  /** „Ułóż w zdanie” (0421) — tylko przy włączonej funkcji karty z notatki. */
  phrase?: PhraseController;
  /** „Uzupełnij z notatki” — tylko przy włączonej funkcji i prawie zapisu. */
  noteBar?: ReactNode;
  /** Pasek nad formularzem (np. „zmiana trafi do DL” po wysłaniu CV). */
  banner?: ReactNode;
  /** Trwały komunikat porażki zapisu. */
  error?: string | null;
  /** Stopka z przyciskami (przyklejona do dołu przewijanego obszaru). */
  footer?: ReactNode;
  /** Historia zmian pod formularzem. */
  history?: ReactNode;
  onOpenChampion?: () => void;
  /** Zapis dostępności z notatek w PROFILU kandydata (brak = bez prawa edycji). */
  onSaveAvailability?: (patch: { availability_date: string }) => void;
  savingAvailability?: boolean;
}

export function ScreeningFullFormView({
  state,
  model,
  jobBudgetHourly,
  phrase,
  noteBar,
  banner,
  error,
  footer,
  history,
  onOpenChampion,
  onSaveAvailability,
  savingAvailability = false,
}: ScreeningFullFormViewProps) {
  const { methods, questions, offers, hints } = model;
  const values = methods.watch();
  // D6 (08.10.2026): pola, które Delivery Lead wskazał do poprawy.
  const fixRequest = state.fix_request ?? null;
  const dirtyFields = methods.formState.dirtyFields as Record<string, unknown>;
  const fixState = (key: string) => (fixRequest ? fixFieldState(fixRequest, key, dirtyFields) : null);
  const termsKeys = cardTermsKeys(state);
  const assessmentKeys = cardAssessmentKeys(state);
  const offerById = new Map(offers.map((o) => [o.id, o]));
  const fields = state.card?.fields ?? {};
  const answeredCount = questions.filter((q) => (values.answers?.[q.id]?.response ?? "").trim()).length;
  const dealBreakerHit = questions.some((q) => values.answers?.[q.id]?.deal_breaker_hit);
  const noteAnswers = new Map((state.note_answers ?? []).map((a) => [a.question_id, a]));

  const gate = evaluateRateGate({
    rawRate: values.rate_amount ?? "",
    unit: values.rate_unit ?? "hourly",
    currency: values.rate_currency || "PLN",
    jobBudgetHourly,
  });
  const nonPln = (values.rate_currency || "PLN").toUpperCase() !== "PLN";
  const setRate = (rate: FormRate) => {
    methods.setValue("rate_amount", String(rate.amount), SET);
    methods.setValue("rate_unit", rate.unit, SET);
    methods.setValue("rate_currency", rate.currency || "PLN", SET);
  };
  const rateOffer = offerById.get("rate");
  const rateHint = hints.find((h) => h.id === "rate");

  const renderQuestionExtra = (reassignExtra: (q: ScreeningQuestion, i: number) => ReactNode) =>
    function QuestionExtra(q: ScreeningQuestion, i: number): ReactNode {
      const empty = !(values.answers?.[q.id]?.response ?? "").trim();
      const fromCard = noteAnswers.get(q.id);
      const offer = offerById.get(`answer:${q.id}`);
      return (
        <>
          <FixMark state={fixState(`question:${q.id}`)} />
          {reassignExtra(q, i)}
          {empty && fromCard?.answer?.trim() ? (
            <div className="flex flex-wrap items-center gap-2 text-xs" data-testid="note-card-answer">
              <HintChip
                label="Z karty w notatce"
                text={fromCard.answer}
                onUse={() => {
                  methods.setValue(`answers.${q.id}.response`, fromCard.answer, { ...SET, shouldValidate: true });
                  methods.setValue(`answers.${q.id}.origin`, "note_import", SET);
                  methods.setValue(`answers.${q.id}.keywords`, null, SET);
                }}
              />
            </div>
          ) : null}
          {offer ? (
            <OfferChip offer={offer} onUse={() => model.acceptOffer(offer.id)} onDismiss={() => model.dismissOffer(offer.id)} />
          ) : null}
        </>
      );
    };

  const sheetFields = (extra: (q: ScreeningQuestion, i: number) => ReactNode) => (
    <ScreeningFormFields
      questions={questions}
      methods={sheetMethods(methods)}
      renderQuestionExtra={renderQuestionExtra(extra)}
      phrase={phrase}
      withOverallFit={false}
    />
  );

  const cardField = (key: string, multiline: boolean) => {
    const name = `card.${key}`;
    const value = values.card?.[key] ?? "";
    const origin = values.card_origins?.[key] ?? null;
    const offer = offerById.get(`card:${key}`);
    const hint = state.card?.previous?.[key]?.raw ?? state.card?.suggestions?.[key];
    const caption = origin
      ? `${ORIGIN_CAPTION[origin.origin] ?? "z notatki"} — zapisz formularz`
      : value.trim() === String(fields[key]?.raw ?? "").trim()
        ? cardFieldSource(fields[key])
        : null;
    const keepsNoteValue = !value.trim() && fields[key]?.source === "note";
    const suggestion = phrase?.results[key];
    const canPhrase = phrase != null && CARD_PHRASABLE_FIELDS.has(key);
    const label = `${formFieldLabel(state, key)}${key === "red_flags" ? " — tylko dla zespołu" : ""}`;
    const applyPhrase = (sentence: string, keywords: string) => {
      methods.setValue(name as Path<ScreeningFullFormValues>, sentence as never, SET);
      methods.setValue(`card_origins.${key}`, { origin: "phrased", keywords }, SET);
      phrase?.dismiss(key);
    };
    const fixMark = fixState(`field:${key}`);
    return (
      <div
        key={key}
        className={cn(
          "space-y-1",
          fixMark === "todo" && "rounded-md ring-2 ring-warning/50 ring-offset-2 ring-offset-background",
        )}
        data-card-field={key}
        data-fix-state={fixMark ?? undefined}
      >
        <FixMark state={fixMark} />
        <FormField name={name} label={label}>
          {multiline ? (
            <TextareaField
              name={name}
              rows={key === "recommendation" ? 4 : 3}
              placeholder={hint ? `ostatnio: ${hint}` : CARD_FIELD_HINT[key]}
            />
          ) : (
            <TextField name={name} placeholder={hint ? `ostatnio: ${hint}` : CARD_FIELD_HINT[key]} />
          )}
        </FormField>
        {caption ? <p className="text-[11px] text-muted-foreground">{caption}</p> : null}
        {keepsNoteValue ? (
          <p className="text-[11px] text-muted-foreground">
            Wartość z notatki zostaje — wpisz inną, żeby ją zastąpić.
          </p>
        ) : null}
        {offer ? (
          <OfferChip offer={offer} onUse={() => model.acceptOffer(offer.id)} onDismiss={() => model.dismissOffer(offer.id)} />
        ) : null}
        {canPhrase && !suggestion ? (
          <PhraseButton
            disabled={!value.trim()}
            pending={phrase.isPending(key)}
            onClick={() =>
              void phrase.request([{ key, keywords: value, question: formFieldLabel(state, key) }])
            }
          />
        ) : null}
        {canPhrase && suggestion ? (
          <PhraseProposal
            suggestion={suggestion}
            onUse={(sentence) => applyPhrase(sentence, suggestion.keywords)}
            onEdit={(sentence) => {
              applyPhrase(sentence, suggestion.keywords);
              methods.setFocus(name as Path<ScreeningFullFormValues>);
            }}
            onKeep={() => phrase.dismiss(key)}
          />
        ) : null}
      </div>
    );
  };

  const legacy = state.legacy_notes?.trim() ?? "";
  const legacyMoved = Boolean(values.clear_legacy_notes);
  const canMoveLegacy = assessmentKeys.includes("recommendation");

  return (
    <FormProvider {...methods}>
      <div className="space-y-5" data-help="jobs.person.screening-form" data-testid="screening-full-form">
        {banner}
        {fixRequest ? <FixRequestBanner request={fixRequest} dirty={dirtyFields} /> : null}
        {model.notice ? (
          <p
            role="status"
            className="flex items-start gap-2 rounded-md border border-warning/30 bg-warning-muted px-3 py-2 text-xs text-warning-muted-foreground"
          >
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
            <span className="min-w-0 flex-1">{model.notice}</span>
            <button
              type="button"
              className="shrink-0 font-medium underline underline-offset-2"
              onClick={() => model.setNotice(null)}
            >
              Rozumiem
            </button>
          </p>
        ) : null}
        {noteBar}

        {/* ── Pytania ─────────────────────────────────────────────────── */}
        <section aria-label="Pytania z Profilu Championa" className="space-y-3">
          <SectionTitle
            hint={
              questions.length > 0
                ? `${answeredCount} z ${countPl(questions.length, "pytania", "pytań", "pytań")} z odpowiedzią${dealBreakerHit ? " · zaznaczony deal-breaker" : ""}`
                : undefined
            }
          >
            Pytania z Profilu Championa
          </SectionTitle>
          {questions.length === 0 ? (
            <ScreeningNoQuestions onOpenChampion={onOpenChampion} />
          ) : (
            <>
              {phrase ? <PhraseAllBar phrase={phrase} questions={questions} methods={sheetMethods(methods)} /> : null}
              {state.stage_id != null ? (
                <ScreeningReassignSuggestions
                  key={state.stage_id}
                  stageId={state.stage_id}
                  questions={questions}
                  methods={sheetMethods(methods)}
                  saved={state.sheet}
                  readOnly={!state.editable}
                >
                  {(extra) => sheetFields(extra)}
                </ScreeningReassignSuggestions>
              ) : (
                sheetFields(() => null)
              )}
            </>
          )}
        </section>

        {/* ── Warunki ─────────────────────────────────────────────────── */}
        <section aria-label="Warunki" className="space-y-3">
          <SectionTitle hint="Pola karty rekomendacji — widzi je Delivery Lead przed wysłaniem CV.">
            Warunki
          </SectionTitle>
          <div className="space-y-2 rounded-lg border border-border bg-background/40 p-3" data-testid="screening-form-rate">
            <div className="flex flex-wrap items-center gap-2">
              <p className="text-xs font-medium text-foreground">Stawka kandydata w tej rekrutacji</p>
              <FixMark state={fixState("candidate_rate")} />
              {model.rateFromNote ? (
                <Badge variant="soft" size="sm">
                  z notatki
                </Badge>
              ) : null}
            </div>
            {nonPln ? (
              <p className="text-[11px] text-muted-foreground">
                Stawka w walucie {values.rate_currency.toUpperCase()} — zapis zostawi tę walutę.
              </p>
            ) : null}
            <VerifiedRateFields
              rate={values.rate_amount ?? ""}
              onRateChange={(next) => {
                methods.setValue("rate_amount", next, SET);
              }}
              unit={values.rate_unit ?? "hourly"}
              onUnitChange={(next: RateUnit) => methods.setValue("rate_unit", next, SET)}
              gate={gate}
              disabled={!state.can_edit_rate}
              idPrefix="screening-form-rate"
            />
            {!state.can_edit_rate ? (
              <p className="text-[11px] text-muted-foreground">
                Nie możesz zmieniać stawki kandydata w tej rekrutacji — pole jest tylko do odczytu.
              </p>
            ) : null}
            {state.can_edit_rate ? (
              <div className="flex flex-wrap gap-1.5">
                {state.rate_hints?.card ? (
                  <HintChip
                    label="Z karty"
                    text={formatFormRate(state.rate_hints.card)}
                    onUse={() => setRate(state.rate_hints.card as FormRate)}
                  />
                ) : null}
                {state.rate_hints?.rate_from ? (
                  <HintChip
                    label="Stawka od"
                    text={formatFormRate(state.rate_hints.rate_from)}
                    onUse={() => setRate(state.rate_hints.rate_from as FormRate)}
                  />
                ) : null}
              </div>
            ) : null}
            <ScreeningSuggestionChips
              suggestions={state.suggestions_from_notes as ScreeningSuggestions | undefined}
              disabled={!state.can_edit_rate}
              onUseRate={(fill) => {
                methods.setValue("rate_amount", fill.rate, SET);
                methods.setValue("rate_unit", fill.unit, SET);
                methods.setValue("rate_currency", "PLN", SET);
              }}
              onSaveAvailability={onSaveAvailability}
              savingAvailability={savingAvailability}
              profileHref={`/candidates/${state.candidate_id}`}
            />
            {rateOffer ? (
              <OfferChip
                offer={rateOffer}
                onUse={() => model.acceptOffer(rateOffer.id)}
                onDismiss={() => model.dismissOffer(rateOffer.id)}
              />
            ) : null}
            {rateHint ? (
              <p className="text-[11px] text-muted-foreground" data-testid="note-rate-hint">
                Z notatki: „{rateHint.text}” — wpisz kwotę i jednostkę ręcznie.
              </p>
            ) : null}
            {state.rate_change_notifies && state.can_edit_rate ? (
              <p className="flex items-start gap-1.5 text-[11px] text-warning-muted-foreground">
                <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" aria-hidden />
                Kandydat jest od „Zweryfikowany” — zmiana stawki otworzy sprawę „zmiana stawki” u Delivery Leada.
              </p>
            ) : null}
          </div>
          {termsKeys.length > 0 ? (
            <div className="@container">
              <div className="grid gap-3 @lg:grid-cols-2">{termsKeys.map((key) => cardField(key, false))}</div>
            </div>
          ) : null}
        </section>

        {/* ── Ocena ───────────────────────────────────────────────────── */}
        <section aria-label="Ocena" className="space-y-3">
          <SectionTitle>Ocena</SectionTitle>
          <div className="space-y-1.5 rounded-lg border border-border bg-background/40 p-3">
            <FixMark state={fixState("field:overall_fit")} />
            <OverallFitField methods={sheetMethods(methods)} />
          </div>
          {assessmentKeys.map((key) => cardField(key, true))}
          {legacy ? (
            <div
              className="space-y-1.5 rounded-lg border border-dashed border-border bg-muted/30 p-3 text-xs"
              data-testid="legacy-sheet-note"
            >
              <p className="font-medium text-foreground">Notatka z arkusza</p>
              <p className="whitespace-pre-line text-muted-foreground [overflow-wrap:anywhere]">{legacy}</p>
              {legacyMoved ? (
                <p role="status" className="text-[11px] text-muted-foreground">
                  Przeniesiona do „Dlaczego ten kandydat” — zapisz formularz, żeby usunąć ją z arkusza.
                </p>
              ) : canMoveLegacy ? (
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    const current = methods.getValues("card.recommendation") ?? "";
                    methods.setValue("card.recommendation", mergeLegacyNote(current, legacy), SET);
                    methods.setValue("clear_legacy_notes", true, SET);
                  }}
                >
                  Przenieś do „Dlaczego ten kandydat”
                </Button>
              ) : null}
            </div>
          ) : null}
        </section>

        {error ? <ScreeningSubmitError message={error} /> : null}
        {footer}
        {history}
      </div>
    </FormProvider>
  );
}

/** Formularz tylko do odczytu: proces zakończony, rekrutacja zamknięta albo brak prawa zapisu. */
export function ScreeningFormReadOnlyView({ state }: { state: ScreeningFormState }) {
  const sheet = state.sheet;
  const questions = formQuestions(state);
  const answers = (sheet?.answers ?? []).map((answer) => ({
    ...answer,
    question_text: answer.question_text ?? questions.find((q) => q.id === answer.question_id)?.question ?? null,
  }));
  const keys = [...cardTermsKeys(state), ...cardAssessmentKeys(state)];
  const fields = state.card?.fields ?? {};
  return (
    <section aria-label="Formularz screeningu — tylko do odczytu" className="space-y-4 text-[13px]" data-testid="screening-form-readonly">
      {state.read_only_message ? (
        <p role="note" className="flex items-start gap-2 rounded-md bg-muted px-3 py-2 text-xs text-muted-foreground">
          <Lock className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          {state.read_only_message}
        </p>
      ) : null}
      {answers.length > 0 ? (
        <ScreeningAnswersList
          answers={answers}
          experienceChecks={sheet?.experience_checks}
          notes={state.legacy_notes}
          internalNote={sheet?.internal_note}
        />
      ) : (
        <p className="text-xs text-muted-foreground">Pytania z Profilu Championa nie mają zapisanych odpowiedzi.</p>
      )}
      <dl className="space-y-1.5">
        <div className="grid grid-cols-[9rem_minmax(0,1fr)] gap-x-2 text-xs">
          <dt className="text-muted-foreground">Stawka kandydata</dt>
          <dd className="font-medium text-foreground">{state.rate ? formatFormRate(state.rate) : "—"}</dd>
        </div>
        {keys.map((key) => {
          const value = cardFieldValue(key, fields[key]);
          return (
            <div key={key} className="grid grid-cols-[9rem_minmax(0,1fr)] gap-x-2 text-xs">
              <dt className="text-muted-foreground">{formFieldLabel(state, key)}</dt>
              <dd className={cn("whitespace-pre-line [overflow-wrap:anywhere]", value ? "font-medium text-foreground" : "text-muted-foreground")}>
                {value || "—"}
              </dd>
            </div>
          );
        })}
      </dl>
    </section>
  );
}

// ── Kontener: zapis, ruch, odrzucenie ────────────────────────────────────

export interface ScreeningFormMoveTarget {
  stage: string;
  stageDefId?: number | null;
}

export interface ScreeningFullFormProps {
  candidateId: number;
  jobId: number;
  candidateName: string;
  jobBudgetHourly: number | null;
  /** „Zapisz i przekaż dalej → Zweryfikowany” — tylko z „Nowych” i „Screeningu”. */
  forward?: (ScreeningFormMoveTarget & { label: string }) | null;
  /** „Odrzuć” z powodem — tylko z „Nowych” i „Screeningu”. */
  reject?: (ScreeningFormMoveTarget & { previousStage: string; previousCategory: "internal" | "external" }) | null;
  /** Ruch zablokowany (np. tryb odczytu) — przyciski ruchu znikają. */
  readOnly?: boolean;
  banner?: ReactNode;
  onMoved?: () => void;
  onSaved?: (result: ScreeningFormSaveResult) => void;
  onOpenChampion?: () => void;
  /** Okno z formularzem: „Anuluj” i zamknięcie po zapisie. */
  onCancel?: () => void;
  closeOnSave?: boolean;
  /** Historia zmian pod formularzem (panel osoby). */
  showHistory?: boolean;
}

export function ScreeningFullForm({
  candidateId,
  jobId,
  candidateName,
  jobBudgetHourly,
  forward = null,
  reject = null,
  readOnly = false,
  banner,
  onMoved,
  onSaved,
  onOpenChampion,
  onCancel,
  closeOnSave = false,
  showHistory = true,
}: ScreeningFullFormProps) {
  const { showSuccess, showError, showInfo, showActionToast } = useToast();
  const queryClient = useQueryClient();
  const query = useScreeningFormState(candidateId, jobId);
  const state = query.data;
  const model = useScreeningFormModel(state);
  const { methods } = model;
  const editable = Boolean(state?.editable) && !readOnly;
  const [error, setError] = useState<string | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [rejectOpen, setRejectOpen] = useState(false);
  const [forwarding, setForwarding] = useState(false);
  const [handingBack, setHandingBack] = useState(false);
  const dirty = methods.formState.isDirty || model.note != null;

  const phraseController = usePhraseSuggestions({
    candidateId,
    jobId,
    defaultLanguage: state?.phrase_language,
  });
  const phrase = state?.assist_enabled && editable ? phraseController : undefined;

  const save = useSaveScreeningForm({ onSaved: (result) => model.markSaved(result) });
  const moveCore = usePipelineMoveCore({ jobId });

  const reasonsQuery = useQuery<RejectionReasonOption[]>({
    queryKey: ["job-rejection-reasons", jobId],
    queryFn: () => loadJobRejectionReasons(jobId),
    staleTime: 5 * 60_000,
    enabled: Boolean(reject) && editable,
  });

  // Dostępność z notatek → PROFIL kandydata (jawny zapis). Nigdy do formularza
  // widocznego dla klienta — tak jak dotąd na stanowisku screeningu.
  const canEditCandidate = useCapability("candidate.write") && editable;
  const availabilityMut = useMutation({
    mutationFn: (patch: { availability_date: string }) => candidatesApi.update(candidateId, patch),
    onSuccess: () => {
      showSuccess("Zapisano dostępność w profilu kandydata");
      void queryClient.invalidateQueries({ queryKey: ["kanban", String(jobId)] });
      void queryClient.invalidateQueries({ queryKey: ["kanban", jobId] });
      void queryClient.invalidateQueries({ queryKey: candidateQueryKeys.detail(candidateId) });
    },
    onError: (err) => showError(apiErrorMessage(err, "Nie udało się zapisać dostępności w profilu")),
  });

  const handleSaveError = (err: unknown) => {
    const conflict = screeningFormConflictOf(err);
    if (conflict) {
      const who = conflict.savedByName?.trim();
      const at = shortDateTime(conflict.savedAt);
      // Bez autora = zmiana obok formularza (stara trasa, automat, DL) — zdanie serwera.
      model.setNotice(
        who
          ? `${who} zapisał(a) ten formularz w międzyczasie${at ? ` (${at})` : ""} — wczytałem nowszą wersję, Twoje niezapisane zmiany zostały. Sprawdź je i zapisz ponownie.`
          : (conflict.message ??
              "Ktoś zmienił formularz w międzyczasie — wczytaliśmy nową wersję, Twoje zmiany zostały w polach."),
      );
      void queryClient.invalidateQueries({ queryKey: screeningFormQueryKey(jobId, candidateId) });
      return;
    }
    if (isScreeningFormReadOnly(err)) {
      showError(apiErrorMessage(err, "Ten formularz jest już tylko do odczytu."));
      void queryClient.invalidateQueries({ queryKey: screeningFormQueryKey(jobId, candidateId) });
      return;
    }
    const message = apiErrorMessage(err, "Nie udało się zapisać formularza.");
    setError(message);
    showError(message);
  };

  /** Zapis; `null` = nic do zapisania albo porażka (komunikat już na ekranie). */
  const saveNow = async (): Promise<ScreeningFormSaveResult | "unchanged" | null> => {
    const base = model.baseState() ?? state;
    if (!base) return null;
    setError(null);
    const plan = buildSavePayload(base, methods.getValues(), { noteImport: model.note?.source ?? null });
    if (!plan.hasChanges) return "unchanged";
    const usedNote = plan.payload.note_import != null;
    try {
      const result = await save.mutateAsync(plan.payload);
      onSaved?.(result);
      if (usedNote && result.undo_to_version != null) {
        const undoTo = result.undo_to_version;
        showActionToast("Formularz zapisany — wypełniony z notatki.", {
          actionLabel: "Cofnij",
          onAction: () => undoSave(undoTo, result.version, result.state_token),
        });
      } else if (result.saved_version == null) {
        showInfo("Bez zmian — formularz jest taki sam jak zapisany.");
      } else {
        showSuccess("Formularz screeningu zapisany.");
      }
      return result;
    } catch (err) {
      handleSaveError(err);
      return null;
    }
  };

  // „Cofnij” po zapisie z notatki — nowa wersja z treścią sprzed zapisu.
  const undo = useRestoreScreeningForm({ onSaved: (result) => model.markSaved(result) });
  const undoSave = (versionNo: number, expectedVersion: number, stateToken: string) =>
    undo.mutate(
      {
        candidate_id: candidateId,
        job_id: jobId,
        version_no: versionNo,
        expected_version: expectedVersion,
        state_token: stateToken,
        mode: "undo",
      },
      {
        onSuccess: (result) => {
          // Stawka, której wersja sprzed zapisu nie miała, zostaje — mówimy to wprost.
          showSuccess(rateNotRestoredMessage(result, "undo") ?? "Cofnięto zapis z notatki.");
        },
        onError: (err) => {
          showError(apiErrorMessage(err, "Nie udało się cofnąć zapisu."));
          if (screeningFormConflictOf(err)) {
            void queryClient.invalidateQueries({ queryKey: screeningFormQueryKey(jobId, candidateId) });
          }
        },
      },
    );

  const onSave = async () => {
    const result = await saveNow();
    if (result === "unchanged") {
      showInfo("Nie ma zmian do zapisania.");
      return;
    }
    if (result && closeOnSave) onCancel?.();
  };

  const onForward = async () => {
    if (!state || !forward) return;
    const values = methods.getValues();
    const missing = missingAnswersForForward(model.questions, values);
    if (missing.length > 0) {
      for (const id of missing) {
        methods.setError(`answers.${id}.response`, { type: "required", message: "Odpowiedź jest wymagana" });
      }
      methods.setFocus(`answers.${missing[0]}.response`);
      setError(null);
      showError(
        `Uzupełnij ${countPl(missing.length, "odpowiedź", "odpowiedzi", "odpowiedzi")} przed przekazaniem dalej.`,
      );
      return;
    }
    setForwarding(true);
    try {
      const saved = await saveNow();
      if (saved === null) return;
      const current = saved === "unchanged" ? state : saved;
      const rate = current.can_edit_rate ? rateFromValues(values) : null;
      // Odmowa ruchu nie cofa zapisu — formularz zostaje zapisany.
      const outcome = await moveCore.send(
        {
          candidate_id: candidateId,
          job_id: jobId,
          stage: forward.stage,
          stage_def_id: forward.stageDefId ?? undefined,
          ...(rate
            ? {
                expected_rate_value: rate.amount,
                expected_rate_unit: rate.unit,
                expected_rate_currency: rate.currency,
              }
            : {}),
          expected_state_version: current.process_state_version,
        },
        { candidateName },
      );
      void queryClient.invalidateQueries({ queryKey: screeningFormQueryKey(jobId, candidateId) });
      if (outcome.ok) {
        showSuccess(`${candidateName} — przekazano dalej: ${forward.label}.`);
        onMoved?.();
      } else if (outcome.refusal.kind === "version_conflict") {
        onMoved?.();
      }
    } finally {
      setForwarding(false);
    }
  };

  // D6 (08.10.2026): po prośbie Delivery Leada o poprawki — zapis i ruch
  // z powrotem na „QC CV” jednym przyciskiem. Odmowa ruchu nie cofa zapisu.
  const handbackStageDefId =
    state?.fix_request && state.handback_stage_def_id ? state.handback_stage_def_id : null;
  const onHandBack = async () => {
    if (!state || handbackStageDefId == null) return;
    setHandingBack(true);
    try {
      const saved = await saveNow();
      if (saved === null) return;
      const current = saved === "unchanged" ? state : saved;
      const outcome = await moveCore.send(
        {
          candidate_id: candidateId,
          job_id: jobId,
          stage_def_id: handbackStageDefId,
          expected_state_version: current.process_state_version,
        },
        { candidateName },
      );
      void queryClient.invalidateQueries({ queryKey: screeningFormQueryKey(jobId, candidateId) });
      if (outcome.ok) {
        showSuccess(`${candidateName} — oddane do przeglądu Delivery Leada.`);
        onMoved?.();
      } else if (outcome.refusal.kind === "version_conflict") {
        onMoved?.();
      }
    } finally {
      setHandingBack(false);
    }
  };

  const rejectMut = useMutation({
    mutationFn: async (vars: {
      reasonId: string;
      notes: string;
      sendRejectionEmail: boolean | null;
      offerResponse: CandidateOfferResponse | null;
      freeReason?: string;
    }) => {
      if (!reject || !state) throw new Error("Brak etapu docelowego.");
      return moveCore.send(
        {
          candidate_id: candidateId,
          job_id: jobId,
          stage: reject.stage,
          stage_def_id: reject.stageDefId ?? undefined,
          rejection_reason_id: vars.reasonId || undefined,
          rejection_reason: vars.freeReason || undefined,
          notes: vars.notes,
          send_rejection_email: vars.sendRejectionEmail ?? undefined,
          candidate_offer_response: vars.offerResponse ?? undefined,
          expected_state_version: state.process_state_version,
        },
        { candidateName, fallbackMessage: "Nie udało się zapisać decyzji." },
      );
    },
    onSuccess: (outcome) => {
      if (!outcome.ok) {
        if (outcome.refusal.kind === "version_conflict") {
          setRejectOpen(false);
          onMoved?.();
        }
        return;
      }
      setRejectOpen(false);
      showSuccess("Zapisano decyzję.");
      void queryClient.invalidateQueries({ queryKey: screeningFormQueryKey(jobId, candidateId) });
      onMoved?.();
    },
    onError: (err) => showError(apiErrorMessage(err, "Nie udało się zapisać decyzji.")),
  });

  if (query.isLoading) {
    return (
      <p className="flex items-center gap-1.5 py-6 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Wczytywanie formularza screeningu…
      </p>
    );
  }
  if (query.isError || !state) {
    return (
      <p role="alert" className="py-4 text-sm text-destructive">
        {apiErrorMessage(query.error, "Nie udało się wczytać formularza screeningu.")}{" "}
        <button type="button" className="font-medium underline underline-offset-2" onClick={() => void query.refetch()}>
          Ponów
        </button>
      </p>
    );
  }

  const history =
    showHistory && (state.versions_count ?? 0) > 0 ? (
      historyOpen ? (
        <ScreeningFormHistory
          candidateId={candidateId}
          jobId={jobId}
          currentVersion={state.version}
          stateToken={state.state_token}
          canRestore={editable}
          dirty={dirty}
          onRestored={(result) => model.markSaved(result)}
        />
      ) : null
    ) : null;

  if (!editable) {
    return (
      <div className="space-y-4">
        <ScreeningFormReadOnlyView state={state} />
        {showHistory && (state.versions_count ?? 0) > 0 ? (
          <ScreeningFormHistory
            candidateId={candidateId}
            jobId={jobId}
            currentVersion={state.version}
            stateToken={state.state_token}
            canRestore={false}
          />
        ) : null}
      </div>
    );
  }

  const claimedByOther = state.claim && !state.claim.mine ? state.claim : null;
  const busy = save.isPending || forwarding || handingBack || rejectMut.isPending;

  const footer = (
    <div
      className="sticky bottom-0 z-10 -mx-1 flex flex-wrap items-center gap-2 border-t border-border bg-background/95 px-1 py-2.5 backdrop-blur supports-[backdrop-filter]:bg-background/80"
      data-testid="screening-form-footer"
    >
      <p className="mr-auto flex items-center gap-1 text-[11px] text-muted-foreground" role="status">
        {dirty ? (
          <>
            <Clock className="h-3 w-3" aria-hidden /> Niezapisane zmiany
          </>
        ) : state.version > 0 ? (
          `Wersja ${state.version}`
        ) : (
          "Formularz jeszcze niezapisany"
        )}
      </p>
      {(state.versions_count ?? 0) > 0 && showHistory ? (
        <Button
          type="button"
          size="sm"
          variant="ghost"
          aria-expanded={historyOpen}
          onClick={() => setHistoryOpen((open) => !open)}
        >
          <History className="h-3.5 w-3.5" aria-hidden /> Historia zmian ({state.versions_count})
        </Button>
      ) : null}
      {onCancel ? (
        <Button type="button" size="sm" variant="ghost" onClick={onCancel} disabled={busy}>
          Anuluj
        </Button>
      ) : null}
      {reject ? (
        <Button
          type="button"
          size="sm"
          variant="quiet"
          disabled={busy}
          onClick={() => setRejectOpen(true)}
          title="Ten sam modal powodu i ta sama reguła maila co na Tablicy"
        >
          <Ban className="h-3.5 w-3.5" aria-hidden /> Odrzuć
        </Button>
      ) : null}
      <Button
        type="button"
        size="sm"
        variant={forward || handbackStageDefId != null ? "outline" : "primary"}
        loading={save.isPending && !forwarding && !handingBack}
        disabled={busy}
        onClick={() => void onSave()}
      >
        <Save className="h-3.5 w-3.5" aria-hidden /> Zapisz
      </Button>
      {handbackStageDefId != null ? (
        <Button
          type="button"
          size="sm"
          loading={handingBack}
          disabled={busy}
          onClick={() => void onHandBack()}
          data-testid="screening-form-handback"
        >
          Zapisz i oddaj do przeglądu DL <ArrowRight className="h-3.5 w-3.5" aria-hidden />
        </Button>
      ) : null}
      {forward ? (
        <Button type="button" size="sm" loading={forwarding} disabled={busy} onClick={() => void onForward()}>
          Zapisz i przekaż dalej <ArrowRight className="h-3.5 w-3.5" aria-hidden /> {forward.label}
        </Button>
      ) : null}
    </div>
  );

  return (
    <>
      <ScreeningFullFormView
        state={state}
        model={model}
        jobBudgetHourly={jobBudgetHourly}
        phrase={phrase}
        banner={
          <>
            {banner}
            {claimedByOther ? (
              <p role="note" className="flex items-start gap-2 rounded-md bg-warning-muted px-3 py-2 text-xs text-warning-muted-foreground">
                <Lock className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
                {claimedByOther.user_name?.trim() || "Inny rekruter"} ma tę osobę na 12 h
                {shortDateTime(claimedByOther.until) ? ` (do ${shortDateTime(claimedByOther.until)})` : ""} — zapis
                odmówi, dopóki blokada trwa.
              </p>
            ) : null}
          </>
        }
        noteBar={
          state.assist_enabled ? (
            <NoteFillBar
              candidateId={candidateId}
              jobId={jobId}
              applied={
                model.note
                  ? {
                      filled: model.note.filled,
                      offers: model.offers.length,
                      sourceName: model.note.source.source_name ?? null,
                    }
                  : null
              }
              onProposal={(proposal, source) => {
                const applied = model.applyNote(proposal, source);
                if (applied.filled === 0 && applied.offers === 0) {
                  showInfo("Notatka nie wniosła nic nowego — formularz ma już te wartości.");
                }
              }}
              onUndo={model.undoNote}
              disabled={busy}
            />
          ) : null
        }
        error={error}
        footer={footer}
        history={history}
        onOpenChampion={onOpenChampion}
        onSaveAvailability={canEditCandidate ? (patch) => availabilityMut.mutate(patch) : undefined}
        savingAvailability={availabilityMut.isPending}
      />
      {moveCore.dialogs}
      {reject && rejectOpen ? (
        <RejectionV2
          open
          onOpenChange={setRejectOpen}
          terminalType="rejected"
          reasons={reasonsQuery.data ?? []}
          previousStageCategory={reject.previousCategory}
          previousStage={reject.previousStage}
          onConfirm={(reasonId, notes, sendRejectionEmail, offerResponse, freeReason) =>
            rejectMut.mutate({
              reasonId,
              notes,
              sendRejectionEmail,
              offerResponse: offerResponse ?? null,
              freeReason,
            })
          }
        />
      ) : null}
    </>
  );
}
