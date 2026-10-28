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
 * Od 14.10.2026: etap bez stawki dostaje stawkę na start z podpisem, skąd jest
 * (D2, `ratePrefill`), notatka zapisana w doku osoby wypełnia formularz bez
 * drugiej kopii (D3, `noteFill`), a udane „Zapisz i przekaż dalej” woła
 * `onForwarded` (P3).
 *
 * Od 16.10.2026 w panelu osoby (Nowi/Screening) formularz pisze każdą zmianę
 * do pamięci rozmowy (`lib/screening-memory.ts`) i przy starcie bierze z niej
 * wpisy tej pary — także te z formularza wspólnego „Screening dla”. Zapis
 * czyści pamięć całej rozmowy (D2 A).
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
import { autofillMoveFields, type AutofillFeedbackChoice } from "@/lib/autofill-feedback";
import type { RejectionEmailText } from "@/lib/rejection-email";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";
import type { RejectionWorkModeChoice } from "@/components/v2/modals/RejectionWorkModeField";
import {
  rejectionRateMoveFields,
  type RejectionRateChoice,
} from "@/components/v2/modals/RejectionRateField";
import {
  useRejectionProfileWorkMode,
  useRejectionProfileRate,
  useRejectionWorkModeJob,
} from "@/hooks/useRejectionWorkModeContext";
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
import { ScreeningSuggestionChips } from "@/components/v2/screening/ScreeningSuggestionChips";
import { VerifiedRateFields } from "@/components/v2/screening/VerifiedRateFields";
import { useCapability } from "@/hooks/useCapability";
import { usePipelineMoveCore } from "@/hooks/usePipelineMoveCore";
import { candidatesApi, type RateUnit, type ScreeningQuestion } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { useAuthStore } from "@/store/auth";
import { recommendationCardsApi, type NoteProposal } from "@/lib/api/recommendationCards";
import type { NoteFillChannel, NoteFillReceiver } from "@/lib/note-fill-channel";
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
} from "@/lib/recommendation-card";
import type { RejectFollowUp } from "@/lib/reject-follow-up";
import { loadJobRejectionReasons, type RejectionReasonOption } from "@/lib/rejection-reasons";
import {
  answerOriginAfterEdit,
  applyNoteProposal,
  assessmentMissingForForward,
  buildSavePayload,
  cardAssessmentKeys,
  cardOriginAfterEdit,
  carriedCaption,
  carriedPrefill,
  cardTermsKeys,
  editableCardKeys,
  fillPatches,
  formatFormRate,
  formDefaultsFromState,
  formFieldLabel,
  formQuestions,
  mergeLegacyNote,
  missingAnswersForForward,
  lowerKnownRate,
  lowerKnownRateText,
  minimumMissingForForward,
  ratePrefill,
  ratePrefillCaption,
  rateFromValues,
  rateNotRestoredMessage,
  sameRate,
  type NoteFill,
  type NoteHint,
  type NoteImport,
  type NoteOffer,
  type RatePrefill,
  type ScreeningFullFormValues,
} from "@/lib/screening-form";
import type { CarriedCardField } from "@/lib/api/screeningForm";
import { onsiteText } from "@/lib/person-facts";
import { notedAtDateLabel, rateSuggestionFill, type ScreeningSuggestions } from "@/lib/screening-suggestions";
import {
  memoryFromSingle,
  singleRestore,
  type PendingMemoryItem,
  type ScreeningMemoryLink,
  type SingleDirty,
} from "@/lib/screening-memory";
import { cn } from "@/lib/utils";
import { evaluateRateGate } from "@/lib/verified-rate-gate";
import { fixFieldState } from "@/lib/screening-fix-request";

import { FixMark, FixRequestBanner } from "./FixRequestBanner";
import { NoteFillBar } from "./NoteFillBar";
import { MemoryPendingNote } from "./ScreeningMemoryNotes";
import { ScreeningFormHistory } from "./ScreeningFormHistory";
import { ScreeningLegacyText, ScreeningSummaryView } from "./ScreeningSummaryView";

/** D3 (21.10.2026): pole dołożone do minimum w karcie klienta — „Wymaga Nordea przed „Zweryfikowany””. */
function requiredByClient(state: ScreeningFormState, key: string): string | undefined {
  const extra = state.card?.required_by_client;
  if (!extra || !extra.fields.includes(key)) return undefined;
  return `Wymaga ${extra.client_name ?? "klient"} przed „Zweryfikowany”`;
}

/** Brudne pola bez wpisów z innej rekrutacji (D2) — to podpowiedź, nie wpis rekrutera. */
function withoutCarried(
  dirty: SingleDirty,
  card: Record<string, string> | undefined,
  carried: Record<string, CarriedCardField>,
): SingleDirty {
  if (!dirty.card) return dirty;
  const kept = Object.fromEntries(
    Object.entries(dirty.card).filter(([key]) => !(carried[key] && (card?.[key] ?? "") === carried[key].raw)),
  );
  return { ...dirty, card: kept };
}

const EMPTY_VALUES: ScreeningFullFormValues = {
  answers: {},
  overall_fit: "uncertain",
  notes: "",
  skip_missing: false,
  skip_reason: null,
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
  /**
   * Stawka wpisana na start, gdy etap jej nie ma (D2, 14.10.2026) — pod polem
   * stoi, skąd jest, dopóki pole ma tę wartość.
   */
  ratePrefilled: RatePrefill | null;
  /** Rekruter sam ruszył stawkę — formularz nie wpisze jej ponownie. */
  touchRate: () => void;
  /**
   * D2 (21.10.2026): pola o osobie wpisane z jej innej rekrutacji — pod polem
   * stoi, skąd są, dopóki pole ma tę wartość. Zapisują się z „Zapisz”.
   */
  carriedPrefilled: Record<string, CarriedCardField>;
  /**
   * Zmiany rekrutera (albo wypełnienie z notatki) czekają na zapis. Sama stawka
   * na start się nie liczy: zapisze się z „Zapisz”, ale stopka nie mówi
   * „Niezapisane zmiany” zaraz po otwarciu (przeklikanie 18.10.2026).
   */
  unsaved: boolean;
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

export function useScreeningFormModel(
  state: ScreeningFormState | undefined,
  /** Pamięć rozmowy osoby (panel osoby w Nowych/Screeningu, 16.10.2026). */
  memory?: ScreeningMemoryLink,
): ScreeningFormModel {
  const methods = useForm<ScreeningFullFormValues>({
    defaultValues: state ? formDefaultsFromState(state) : EMPTY_VALUES,
  });
  const [note, setNote] = useState<NoteState | null>(null);
  const [offers, setOffers] = useState<NoteOffer[]>([]);
  const [hints, setHints] = useState<NoteHint[]>([]);
  const [rateFromNote, setRateFromNote] = useState(false);
  const [ratePrefilled, setRatePrefilledState] = useState<RatePrefill | null>(null);
  // Ref obok stanu: wypełnienie z notatki zaraz po hydratacji widzi już wpis.
  const ratePrefilledRef = useRef<RatePrefill | null>(null);
  const setRatePrefilled = useCallback((next: RatePrefill | null) => {
    ratePrefilledRef.current = next;
    setRatePrefilledState(next);
  }, []);
  // Para, w której rekruter sam ruszył stawkę — odświeżenie w tle nie wpisze
  // jej z powrotem po wyczyszczeniu pola.
  const rateTouched = useRef<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const questions = useMemo(() => (state ? formQuestions(state) : []), [state]);
  const [carriedPrefilled, setCarriedPrefilledState] = useState<Record<string, CarriedCardField>>({});
  const carriedPrefilledRef = useRef<Record<string, CarriedCardField>>({});
  // Pola, które rekruter ruszył po wpisaniu z innej rekrutacji (klucz pary →
  // pola) — formularz nie wpisze ich ponownie po zapisie ani odświeżeniu.
  const carriedTouched = useRef<{ key: string; fields: Set<string> } | null>(null);

  // D2 (21.10.2026): jak stawka na start — po `reset`, jako zmiana formularza.
  const prefillCarried = useCallback(
    (next: ScreeningFormState) => {
      const key = `${next.candidate_id}:${next.job_id}`;
      const touched = carriedTouched.current?.key === key ? carriedTouched.current.fields : new Set<string>();
      const placed: Record<string, CarriedCardField> = {};
      for (const [field, value] of Object.entries(carriedPrefill(next))) {
        if (touched.has(field) || (methods.getValues(`card.${field}`) ?? "").trim()) continue;
        methods.setValue(`card.${field}`, value.raw, SET);
        placed[field] = value;
      }
      carriedPrefilledRef.current = placed;
      setCarriedPrefilledState(placed);
    },
    [methods],
  );

  // D2 (14.10.2026): etap bez stawki — pole dostaje stawkę z notatki, karty
  // albo „Stawkę od” jako zmianę formularza, więc zapisze się z „Zapisz”.
  // Po `reset`, bo ten ustawia wartości startowe ze stanu serwera.
  const prefillRate = useCallback(
    (next: ScreeningFormState) => {
      const key = `${next.candidate_id}:${next.job_id}`;
      const pick = rateTouched.current === key ? null : ratePrefill(next);
      const current = rateFromValues(methods.getValues());
      // Stawka z karty stoi w polu od wartości startowych — `ratePrefill` też ją
      // wybiera (R1, 17.10.2026: karta tej rekrutacji wygrywa z notatką).
      const fromCard = next.rate?.source === "card" && sameRate(current, next.rate);
      if (!pick || (current != null && !fromCard)) {
        setRatePrefilled(null);
        return;
      }
      if (!sameRate(current, pick.rate)) {
        methods.setValue("rate_amount", String(pick.rate.amount), SET);
        methods.setValue("rate_unit", pick.rate.unit, SET);
        methods.setValue("rate_currency", pick.rate.currency || "PLN", SET);
      }
      setRatePrefilled(pick);
    },
    [methods, setRatePrefilled],
  );
  const touchRate = useCallback(() => {
    if (state) rateTouched.current = `${state.candidate_id}:${state.job_id}`;
  }, [state]);

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

  // Pamięć rozmowy: zmiany idą do niej dopiero, gdy formularz pary wziął już
  // z niej swoje wpisy (`memoryReady` = klucz pary).
  const memoryRef = useRef(memory);
  memoryRef.current = memory;
  const memoryReady = useRef<string | null>(null);
  const noteRef = useRef<NoteState | null>(note);
  noteRef.current = note;
  const persist = useCallback(() => {
    const link = memoryRef.current;
    const base = hydrated.current?.state;
    if (!link || !base) return;
    const key = `${base.candidate_id}:${base.job_id}`;
    if (memoryReady.current !== key) return;
    const values = methods.getValues();
    // Bieżący stan, nie migawka z renderu (`formState`): zapis do pamięci idzie
    // zaraz po `setValue` (przywrócenie, wpis), zanim formularz się przerysuje.
    const dirtyFields = methods.control._formState.dirtyFields;
    // Stawka wpisana na start (D2) to podpowiedź, nie wpis rekrutera.
    const prefilled = ratePrefilledRef.current;
    const rateDirty = Boolean(dirtyFields.rate_amount || dirtyFields.rate_unit || dirtyFields.rate_currency);
    const rateByRecruiter =
      rateTouched.current === key || (rateDirty && !(prefilled && sameRate(rateFromValues(values), prefilled.rate)));
    const current = noteRef.current;
    link.write((prev) =>
      memoryFromSingle(prev, {
        anchorJobId: base.job_id,
        state: base,
        values,
        dirty: withoutCarried(dirtyFields as SingleDirty, values.card, carriedPrefilledRef.current),
        rateTouched: rateByRecruiter,
        note: current ? { source: current.source, filled: current.filled } : null,
        now: Date.now(),
      }),
    );
  }, [methods]);

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
    const fresh = !prev || prev.key !== key;
    if (fresh) memoryReady.current = null;
    methods.reset(formDefaultsFromState(state));
    if (fresh) {
      clearNote();
      setNotice(null);
      rateTouched.current = null;
      carriedTouched.current = null;
    }
    prefillRate(state);
    prefillCarried(state);
    if (!fresh) return;
    // Wpisy tej pary z rozmowy (także z formularza wspólnego) — jako zmiany rekrutera.
    const link = memoryRef.current;
    if (link) {
      const restore = singleRestore(link.read(), state, link.clientId);
      for (const [path, value] of restore.patches) {
        methods.setValue(path as Path<ScreeningFullFormValues>, value as never, SET);
      }
      if (restore.rateTouched) {
        rateTouched.current = key;
        setRatePrefilled(null);
      }
      if (restore.note) {
        const restored: NoteState = { source: restore.note.source, filled: restore.note.filled, undo: [] };
        noteRef.current = restored;
        setNote(restored);
      }
    }
    memoryReady.current = key;
    persist();
  }, [state, methods, clearNote, prefillRate, prefillCarried, setRatePrefilled, persist]);

  useEffect(() => {
    const subscription = methods.watch(() => persist());
    return () => subscription.unsubscribe();
  }, [methods, persist]);
  useEffect(() => {
    persist();
  }, [note, persist]);

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
      prefillRate(result);
      prefillCarried(result);
    },
    [methods, clearNote, prefillRate, prefillCarried],
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
        const base = hydrated.current?.state;
        if (base && carriedPrefilledRef.current[key]) {
          const pair = `${base.candidate_id}:${base.job_id}`;
          if (carriedTouched.current?.key !== pair) carriedTouched.current = { key: pair, fields: new Set() };
          carriedTouched.current.fields.add(key);
        }
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
      const values = methods.getValues();
      // Stawka wpisana na start (D2) to podpowiedź — stawka z notatki z rozmowy
      // ją zastępuje, zamiast czekać na „Użyj”.
      const prefilled = ratePrefilledRef.current;
      const prefilledUntouched = prefilled != null && sameRate(rateFromValues(values), prefilled.rate);
      const result = applyNoteProposal(prefilledUntouched ? { ...values, rate_amount: "" } : values, proposal, {
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

  // `watch` subskrybuje pola stawki — inna kwota wpisana ręcznie zmienia wynik,
  // choć `dirtyFields` zostaje to samo.
  const watchedRate = methods.watch(["rate_amount", "rate_unit", "rate_currency"]);
  const watchedCard = methods.watch("card");
  const dirtyFields = methods.formState.dirtyFields;
  const rateDirty = Boolean(dirtyFields.rate_amount || dirtyFields.rate_unit || dirtyFields.rate_currency);
  const onlyPrefilledRate =
    !rateDirty ||
    (ratePrefilled != null &&
      sameRate(
        rateFromValues({ rate_amount: watchedRate[0], rate_unit: watchedRate[1], rate_currency: watchedRate[2] }),
        ratePrefilled.rate,
      ));
  // Pola wpisane z innej rekrutacji (D2) też nie zapalają „Niezapisanych zmian”.
  const onlyCarriedCard = Object.entries(dirtyFields.card ?? {}).every(
    ([key, isDirty]) => !isDirty || (watchedCard?.[key] ?? "") === carriedPrefilled[key]?.raw,
  );
  const otherDirty = Object.keys(dirtyFields).some((k) => !k.startsWith("rate_") && k !== "card");
  const unsaved = (dirty && (otherDirty || !onlyPrefilledRate || !onlyCarriedCard)) || note != null;

  return {
    methods,
    questions,
    note,
    offers,
    hints,
    rateFromNote,
    ratePrefilled,
    touchRate,
    carriedPrefilled,
    unsaved,
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
  /** Tryb pracy z profilu kandydata („Do 2 dni w biurze”) — podpowiedź pod polem. */
  profileWorkMode?: string | null;
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
  profileWorkMode = null,
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
    model.touchRate();
    methods.setValue("rate_amount", String(rate.amount), SET);
    methods.setValue("rate_unit", rate.unit, SET);
    methods.setValue("rate_currency", rate.currency || "PLN", SET);
  };
  const rateOffer = offerById.get("rate");
  const rateHint = hints.find((h) => h.id === "rate");
  // D2 (14.10.2026): stawka wpisana na start mówi pod polem, skąd jest;
  // podpowiedź z tą samą wartością co w polu znika (zostają inne).
  const fieldRate = rateFromValues(values);
  const prefilled =
    model.ratePrefilled && sameRate(fieldRate, model.ratePrefilled.rate) ? model.ratePrefilled : null;
  const inField = (rate: FormRate | null | undefined) => rate != null && sameRate(fieldRate, rate);
  const noteRate = (state.suggestions_from_notes as ScreeningSuggestions | undefined)?.rate;
  const noteRateFill = noteRate ? rateSuggestionFill(noteRate) : null;
  const noteRateInField =
    noteRateFill != null &&
    inField({ amount: Number(noteRateFill.rate), unit: noteRateFill.unit, currency: "PLN" });
  // R2 (17.10.2026): ponad budżetem, a kandydat podał też niższą w budżecie.
  const lowerRate = lowerKnownRate(state, fieldRate, jobBudgetHourly);
  const contractRate = state.rate_hints?.rate_from_source === "contract";
  const declared = contractRate ? (state.rate_hints?.declared_from ?? null) : null;
  const declaredDate = notedAtDateLabel(state.rate_hints?.declared_from_at);
  const rateBlockRef = useRef<HTMLDivElement | null>(null);
  const focusRate = () => {
    const input = rateBlockRef.current?.querySelector<HTMLInputElement>("#screening-form-rate-value");
    input?.focus();
    input?.select();
  };

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
                label="Z notatki"
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
    const carried = model.carriedPrefilled[key];
    const caption = origin
      ? `${ORIGIN_CAPTION[origin.origin] ?? "z notatki"} — zapisz formularz`
      : carried && value === carried.raw
        ? `${carriedCaption(carried)} — sprawdź i zapisz`
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
        <FormField
          name={name}
          label={label}
          // 12.10.2026: to, co już wiemy, stoi pod polem, którego dotyczy.
          description={
            key === "work_mode" && profileWorkMode
              ? `W profilu: ${profileWorkMode}`
              : requiredByClient(state, key)
          }
        >
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
        {key === "availability" ? (
          // Dostępność z notatek: „Użyj” zapisuje ją w PROFILU kandydata (nie
          // w tym polu). Do 12.10.2026 stała w bloku stawki, daleko od pola.
          <ScreeningSuggestionChips
            only="availability"
            suggestions={state.suggestions_from_notes as ScreeningSuggestions | undefined}
            disabled={!state.can_edit_rate}
            onSaveAvailability={onSaveAvailability}
            savingAvailability={savingAvailability}
            profileHref={`/candidates/${state.candidate_id}`}
          />
        ) : null}
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

        {/* Kolejność (09.10.2026, prośba rekruterów): najpierw warunki — stawka,
            dostępność, tryb — potem pytania. Do tej daty warunki stały pod
            pytaniami i przy długim arkuszu trzeba było do nich przewijać. */}
        {/* ── Warunki ─────────────────────────────────────────────────── */}
        <section aria-label="Warunki" className="space-y-3">
          <SectionTitle hint="Te pola widzi Delivery Lead przed wysłaniem CV.">
            Warunki
          </SectionTitle>
          <div
            ref={rateBlockRef}
            className="space-y-2 rounded-lg border border-border bg-background/40 p-3"
            data-testid="screening-form-rate"
          >
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
                model.touchRate();
                methods.setValue("rate_amount", next, SET);
              }}
              unit={values.rate_unit ?? "hourly"}
              onUnitChange={(next: RateUnit) => {
                model.touchRate();
                methods.setValue("rate_unit", next, SET);
              }}
              gate={gate}
              disabled={!state.can_edit_rate}
              idPrefix="screening-form-rate"
              overBudgetNote={
                lowerRate
                  ? {
                      text: lowerKnownRateText(lowerRate),
                      useLabel: `Użyj ${formatFormRate(lowerRate.rate)}`,
                      onUse: () => setRate(lowerRate.rate),
                    }
                  : null
              }
            />
            {prefilled ? (
              <p className="text-[11px] text-muted-foreground [overflow-wrap:anywhere]" data-testid="rate-prefill-origin">
                {ratePrefillCaption(prefilled.origin)} ·{" "}
                <button
                  type="button"
                  onClick={focusRate}
                  className="font-medium text-primary hover:underline"
                  aria-label="Zmień stawkę kandydata"
                >
                  zmień
                </button>
              </p>
            ) : null}
            {!state.can_edit_rate ? (
              <p className="text-[11px] text-muted-foreground">
                Nie możesz zmieniać stawki kandydata w tej rekrutacji — pole jest tylko do odczytu.
              </p>
            ) : null}
            {state.can_edit_rate ? (
              <div className="flex flex-wrap gap-1.5">
                {state.rate_hints?.card && !inField(state.rate_hints.card) ? (
                  // Stawka z karty rekomendacji (14.10.2026: „Z karty”, nie „Z notatki” —
                  // pod polem „z notatki” znaczy stawkę z notatek rekrutera).
                  <HintChip
                    label="Z karty"
                    text={formatFormRate(state.rate_hints.card)}
                    onUse={() => setRate(state.rate_hints.card as FormRate)}
                  />
                ) : null}
                {state.rate_hints?.rate_from && !inField(state.rate_hints.rate_from) ? (
                  <HintChip
                    label={contractRate ? "Stawka u nas" : "Stawka od"}
                    text={formatFormRate(state.rate_hints.rate_from)}
                    onUse={() => setRate(state.rate_hints.rate_from as FormRate)}
                  />
                ) : null}
                {declared && !inField(declared) ? (
                  // R4 (17.10.2026): przy żywej umowie — najniższa zadeklarowana stawka.
                  <HintChip
                    label="Zadeklarowana od"
                    text={`${formatFormRate(declared)}${declaredDate ? ` · ${declaredDate}` : ""}`}
                    onUse={() => setRate(declared)}
                  />
                ) : null}
              </div>
            ) : null}
            {!noteRateInField ? (
              <ScreeningSuggestionChips
                only="rate"
                suggestions={state.suggestions_from_notes as ScreeningSuggestions | undefined}
                disabled={!state.can_edit_rate}
                onUseRate={(fill) => {
                  model.touchRate();
                  methods.setValue("rate_amount", fill.rate, SET);
                  methods.setValue("rate_unit", fill.unit, SET);
                  methods.setValue("rate_currency", "PLN", SET);
                }}
              />
            ) : null}
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
              {/* grid-cols-1 (minmax(0,1fr)), nie niejawna kolumna `auto`: ta rosła
                  do pełnej długości podpowiedzi „Z notatek” i przesuwała panel w bok. */}
              <div className="grid grid-cols-1 gap-3 @lg:grid-cols-2">{termsKeys.map((key) => cardField(key, false))}</div>
            </div>
          ) : null}
        </section>

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
  reject?:
    | (ScreeningFormMoveTarget & {
        previousStage: string;
        previousCategory: "internal" | "external";
        /** Osoba od systemu (23.10.2026) — okno pyta o powód dla systemu. */
        autofill?: { rateKnown: boolean; several: boolean } | null;
      })
    | null;
  /** Panel osoby (13.10.2026): po udanym „Odrzuć” panel pokazuje następną
   *  osobę. Woła się przy kliknięciu — migawka kolejności Tablicy. */
  rejectFollowUp?: () => RejectFollowUp | undefined;
  /** Ruch zablokowany (np. tryb odczytu) — przyciski ruchu znikają. */
  readOnly?: boolean;
  banner?: ReactNode;
  onMoved?: () => void;
  /**
   * P3 (14.10.2026): „Zapisz i przekaż dalej” przeszło. Tylko po udanym ruchu —
   * `onMoved` woła się też po konflikcie wersji i po odrzuceniu.
   */
  onForwarded?: () => void;
  /** D3 (14.10.2026): notatka zapisana w doku osoby wypełnia ten formularz. */
  noteFill?: NoteFillChannel;
  onSaved?: (result: ScreeningFormSaveResult) => void;
  onOpenChampion?: () => void;
  /** Okno z formularzem: „Anuluj” i zamknięcie po zapisie. */
  onCancel?: () => void;
  closeOnSave?: boolean;
  /** Historia zmian pod formularzem (panel osoby). */
  showHistory?: boolean;
  /** Pamięć rozmowy osoby (panel osoby w Nowych/Screeningu, 16.10.2026). */
  memory?: ScreeningMemoryLink;
  /** Odznaczone rekrutacje „Screening dla” z wpisami — zapis ich nie obejmie (D2 A). */
  pendingMemory?: readonly PendingMemoryItem[];
  onReselect?: (jobId: number) => void;
}

export function ScreeningFullForm({
  candidateId,
  jobId,
  candidateName,
  jobBudgetHourly,
  forward = null,
  reject = null,
  rejectFollowUp,
  readOnly = false,
  banner,
  onMoved,
  onForwarded,
  noteFill,
  onSaved,
  onOpenChampion,
  onCancel,
  closeOnSave = false,
  showHistory = true,
  memory,
  pendingMemory = [],
  onReselect,
}: ScreeningFullFormProps) {
  const { showSuccess, showError, showInfo, showActionToast } = useToast();
  const queryClient = useQueryClient();
  // 22.10.2026: Delivery Lead przekazuje dalej bez kompletu pól — serwer też
  // go przepuszcza (`pipeline_move_rules.skips_fill_gates`, flaga z
  // `/api/auth/me` — zna też wyłącznik `DL_SKIPS_FILL_GATES`; F109).
  const skipsFillGates = useAuthStore((s) => s.user?.skips_fill_gates === true);
  const query = useScreeningFormState(candidateId, jobId);
  const state = query.data;
  const model = useScreeningFormModel(state, memory);
  const { methods } = model;
  const editable = Boolean(state?.editable) && !readOnly;
  const [error, setError] = useState<string | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [rejectOpen, setRejectOpen] = useState(false);
  const [rejectSnapshot, setRejectSnapshot] = useState<RejectFollowUp | undefined>(undefined);
  const [forwarding, setForwarding] = useState(false);
  const [handingBack, setHandingBack] = useState(false);
  const dirty = model.unsaved;

  // Błąd „wpisz, dlaczego ten kandydat” (rekrutacja bez pytań) znika, gdy pole
  // dostaje treść — formularz nie ma walidacji przy zmianie, więc sam by został.
  const recommendation = methods.watch("card.recommendation");
  useEffect(() => {
    if ((recommendation ?? "").trim()) methods.clearErrors("card.recommendation");
  }, [recommendation, methods]);

  const phraseController = usePhraseSuggestions({
    candidateId,
    jobId,
    defaultLanguage: state?.phrase_language,
  });
  const phrase = state?.assist_enabled && editable ? phraseController : undefined;

  const save = useSaveScreeningForm({ onSaved: (result) => model.markSaved(result) });
  const moveCore = usePipelineMoveCore({ jobId });

  // D3 (14.10.2026): „Zapisz notatkę i wypełnij formularz” w doku osoby. Ten
  // sam warunek co pasek „Uzupełnij z notatki”, ta sama trasa odczytu; zapis
  // formularza odsyła `note_id`, więc notatka nie powstaje drugi raz.
  const canReceiveNote = Boolean(state?.assist_enabled) && editable;
  const scopeRef = useRef("");
  scopeRef.current = `${candidateId}:${jobId}`;
  const modelRef = useRef(model);
  modelRef.current = model;
  const [readingDockNote, setReadingDockNote] = useState(false);
  const readingRef = useRef(false);
  const receiveNote = useRef<NoteFillReceiver | null>(null);
  receiveNote.current = async ({ noteId, text }) => {
    const scope = `${candidateId}:${jobId}`;
    if (modelRef.current.note || readingRef.current) {
      const message = "Formularz ma już wypełnienie z innej notatki — zapisz go albo cofnij wypełnienie.";
      showError(message);
      throw new Error(message);
    }
    let proposal: NoteProposal;
    readingRef.current = true;
    setReadingDockNote(true);
    try {
      proposal = await recommendationCardsApi.readNote(candidateId, jobId, text);
    } catch (err) {
      showError(apiErrorMessage(err, "Nie udało się odczytać notatki. Spróbuj ponownie."));
      throw err;
    } finally {
      readingRef.current = false;
      setReadingDockNote(false);
    }
    // Odczyt trwa do minuty — wynik liczy się tylko dla osoby, dla której ruszył.
    if (scopeRef.current !== scope) throw new Error("Formularz pokazuje już inną osobę.");
    if (proposal.message && !proposal.available) showError(proposal.message);
    const applied = modelRef.current.applyNote(proposal, {
      text: proposal.text || text,
      source_name: null,
      note_id: noteId,
    });
    if (applied.filled === 0 && applied.offers === 0) {
      showInfo("Notatka nie wniosła nic nowego — formularz ma już te wartości.");
    }
  };
  useEffect(() => {
    if (!noteFill || !canReceiveNote) return;
    return noteFill.register(candidateId, (note) =>
      receiveNote.current ? receiveNote.current(note) : Promise.reject(new Error("Formularz nie jest gotowy.")),
    );
  }, [noteFill, canReceiveNote, candidateId]);

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

  // Tryb pracy z profilu jako podpowiedź pod polem — ten sam klucz i trasa co
  // dok osoby i profil przed telefonem, więc w panelu bez dodatkowego żądania.
  const profileQuery = useQuery<{ max_onsite_days_per_week?: number | null }>({
    queryKey: candidateQueryKeys.detail(candidateId),
    queryFn: () => candidatesApi.get(candidateId).then((r) => r.data),
    staleTime: 60_000,
  });
  const profileWorkMode = onsiteText(profileQuery.data?.max_onsite_days_per_week);
  // Okno odrzucenia: pytanie o dni w biurze przy „Nie akceptuje trybu pracy”.
  const rejectWorkModeJob = useRejectionWorkModeJob(jobId, rejectOpen);
  const rejectProfileWorkMode = useRejectionProfileWorkMode(candidateId, rejectOpen);
  const rejectProfileRate = useRejectionProfileRate(candidateId, rejectOpen);

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
    if (!plan.hasChanges) {
      // D2 A: zapis zamyka rozmowę — wpisy odznaczonych rekrutacji znikają.
      memory?.write(() => null);
      return "unchanged";
    }
    const usedNote = plan.payload.note_import != null;
    try {
      const result = await save.mutateAsync(plan.payload);
      memory?.write(() => null);
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

  const markMinimumGaps = (keys: readonly string[], announce = true) => {
    for (const key of keys) {
      methods.setError(`card.${key}`, { type: "required", message: "Delivery Lead potrzebuje tego pola" });
    }
    methods.setFocus(`card.${keys[0]}`);
    setError(null);
    if (announce && state) {
      showError(
        `Przed przekazaniem dalej uzupełnij: ${keys.map((key) => formFieldLabel(state, key)).join(", ")}.`,
      );
    }
  };

  const onForward = async () => {
    if (!state || !forward) return;
    const values = methods.getValues();
    const missing = skipsFillGates ? [] : missingAnswersForForward(model.questions, values);
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
    // Rekrutacja bez pytań: zapisem rozmowy jest „Dlaczego ten kandydat”
    // (12.10.2026) — bez tego serwer i tak odmówi ruchu.
    if (!skipsFillGates && assessmentMissingForForward(state, model.questions, values)) {
      methods.setError("card.recommendation", { type: "required", message: "Wpisz, dlaczego ten kandydat" });
      methods.setFocus("card.recommendation");
      setError(null);
      showError(
        "Ta rekrutacja nie ma pytań screeningowych — przed przekazaniem dalej wpisz „Dlaczego ten kandydat”.",
      );
      return;
    }
    // Minimum dla DL (21.10.2026) — ta sama reguła co bramka serwera.
    const minimum = skipsFillGates ? [] : minimumMissingForForward(state, model.questions, values);
    if (minimum.length > 0) {
      markMinimumGaps(minimum);
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
        {
          candidateName,
          // Serwer wie więcej (np. pola dołożone przez klienta) — podświetl je.
          onVerifiedMissing: (info) => {
            if (info.cardFields.length > 0) markMinimumGaps(info.cardFields, false);
          },
        },
      );
      void queryClient.invalidateQueries({ queryKey: screeningFormQueryKey(jobId, candidateId) });
      if (outcome.ok) {
        showSuccess(`${candidateName} — przekazano dalej: ${forward.label}.`);
        onMoved?.();
        onForwarded?.();
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
      followUp?: RejectFollowUp;
      emailText?: RejectionEmailText | null;
      workMode?: RejectionWorkModeChoice | null;
      autofill?: AutofillFeedbackChoice | null;
      rate?: RejectionRateChoice | null;
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
          rejection_email_subject: vars.emailText?.subject,
          rejection_email_body: vars.emailText?.body,
          work_mode_max_onsite_days: vars.workMode?.maxOnsiteDays,
          work_mode_save_to_profile: vars.workMode?.saveToProfile,
          ...autofillMoveFields(vars.autofill),
          ...rejectionRateMoveFields(vars.rate),
          candidate_offer_response: vars.offerResponse ?? undefined,
          expected_state_version: state.process_state_version,
        },
        { candidateName, fallbackMessage: "Nie udało się zapisać decyzji." },
      );
    },
    onSuccess: (outcome, vars) => {
      if (!outcome.ok) {
        if (outcome.refusal.kind === "version_conflict") {
          setRejectOpen(false);
          onMoved?.();
        }
        return;
      }
      setRejectOpen(false);
      showSuccess("Zapisano decyzję.");
      vars.followUp?.onMoved({
        reasonLabel:
          reasonsQuery.data?.find((r) => r.id === vars.reasonId)?.label ?? (vars.freeReason?.trim() || null),
      });
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
        <section aria-label="Formularz screeningu — tylko do odczytu">
          <ScreeningSummaryView
            state={state}
            showLockNote
            legacy={<ScreeningLegacyText candidateId={candidateId} jobId={jobId} />}
          />
        </section>
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
  // Minimum dla DL (21.10.2026) — przy „Zapisz i przekaż dalej” widać, czego brakuje.
  const minimumGaps = forward
    ? minimumMissingForForward(state, model.questions, { card: methods.watch("card") ?? {} })
    : [];
  const minimumRequired = forward ? (state.card?.required ?? []).length > 0 : false;

  const footer = (
    <div
      className="sticky bottom-0 z-10 -mx-1 flex flex-wrap items-center justify-end gap-2 border-t border-border bg-background/95 px-1 py-2.5 backdrop-blur supports-[backdrop-filter]:bg-background/80"
      data-testid="screening-form-footer"
    >
      {pendingMemory.length > 0 ? (
        <div className="basis-full">
          <MemoryPendingNote scope="tylko tę rekrutację" items={pendingMemory} onReselect={onReselect} />
        </div>
      ) : null}
      {minimumRequired ? (
        <p
          className={cn(
            "basis-full text-[11px]",
            minimumGaps.length > 0 ? "text-warning-muted-foreground" : "text-muted-foreground",
          )}
          data-testid="screening-form-minimum"
        >
          {minimumGaps.length > 0
            ? `Minimum dla Delivery Leada — brakuje: ${minimumGaps.map((key) => formFieldLabel(state, key)).join(", ")}`
            : "Minimum dla Delivery Leada: komplet"}
        </p>
      ) : null}
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
          onClick={() => {
            setRejectSnapshot(rejectFollowUp?.());
            setRejectOpen(true);
          }}
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
                      noteSaved: model.note.source.note_id != null,
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
              readingDockNote={readingDockNote}
            />
          ) : null
        }
        error={error}
        footer={footer}
        history={history}
        onOpenChampion={onOpenChampion}
        onSaveAvailability={canEditCandidate ? (patch) => availabilityMut.mutate(patch) : undefined}
        savingAvailability={availabilityMut.isPending}
        profileWorkMode={profileWorkMode}
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
          subject={{ name: candidateName, stageLabel: rejectSnapshot?.stageLabel ?? null }}
          nextPerson={rejectSnapshot ? rejectSnapshot.next : undefined}
          emailPreview={{ jobId, people: [{ candidateId, name: candidateName }] }}
          pending={rejectMut.isPending}
          workModeJob={rejectWorkModeJob}
          profileWorkMode={rejectProfileWorkMode}
          profileRate={rejectProfileRate}
          autofill={reject.autofill ?? null}
          onConfirm={(
            reasonId,
            notes,
            sendRejectionEmail,
            offerResponse,
            freeReason,
            _endedBy,
            _cancelAgreementId,
            emailText,
            workMode,
            autofill,
            rate,
          ) =>
            rejectMut.mutate({
              reasonId,
              notes,
              sendRejectionEmail,
              offerResponse: offerResponse ?? null,
              freeReason,
              followUp: rejectSnapshot,
              emailText,
              workMode,
              autofill,
              rate,
            })
          }
        />
      ) : null}
    </>
  );
}
