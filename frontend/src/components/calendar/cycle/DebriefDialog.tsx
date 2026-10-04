"use client";

import * as React from "react";
import { useEffect, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, X } from "lucide-react";

import { AppModal } from "@/components/ds/AppModal";
import { useToast } from "@/components/Toast";
import { apiErrorMessage } from "@/lib/api-error";
import { interviewCycleApi, useDebrief, useInterviewEvent } from "@/lib/api/interviewCycle";
import {
  debriefAvailable,
  debriefAvailableFromLabel,
  MAX_DEBRIEF_QUESTIONS,
  mergeQuestions,
  OFFER_LABELS,
  OUTCOME_LABELS,
  splitPastedQuestions,
  type Debrief,
  type DebriefOutcome,
  type OfferAcceptance,
} from "@/lib/interview-cycle";
import { blurNumberInputOnWheel } from "@/lib/number-input";
import {
  NEGOTIABLE_OPTIONS,
  notifyLine,
  toHourly,
  useRateChanges,
  type RateNegotiable,
} from "@/lib/rate-change";
import { cn } from "@/lib/utils";

const OUTCOMES: DebriefOutcome[] = ["good", "medium", "bad"];
const OFFERS: OfferAcceptance[] = ["yes", "likely", "no", "unknown"];
const INPUT =
  "w-full rounded-md border border-border bg-card px-3 py-2 text-sm focus:outline-hidden focus-visible:ring-2 focus-visible:ring-ring";

const OUTCOME_TONE: Record<DebriefOutcome, string> = {
  good: "border-success bg-success-muted text-success-muted-foreground",
  medium: "border-warning bg-warning-muted text-warning-muted-foreground",
  bad: "border-destructive bg-destructive/10 text-destructive",
};

export const DEBRIEF_QUESTIONS_REQUIRED =
  "Wpisz pytania klienta albo zaznacz, że klient ich nie zadawał.";

/**
 * Formularz debriefu po telefonie do kandydata (≤30 min po rozmowie u klienta).
 * Trzy rzeczy, o które prosił zespół: jak poszło, jakie były pytania (trafiają
 * do karty klienta, prepu następnych kandydatów i profilu Championa), czy
 * przyjmie ofertę. Pusta lista pytań wymaga jawnego „Klient nie zadawał pytań”
 * — to bramka przed „Umową” (`services/debrief_gate.py`), więc brak informacji
 * nie może udawać odpowiedzi.
 *
 * Wspólny dla kalendarza (`DebriefModal`) i bramki na tablicy
 * (`DebriefRequiredDialog`) — różnią się tylko tytułem, opisem i tym, co
 * dzieje się po zapisie.
 *
 * Debrief da się zapisać dopiero od rozpoczęcia rozmowy (serwer: 422). Przed
 * nią okno mówi, od kiedy będzie dostępny, i nie pozwala zapisać. Termin
 * podaje wołający (`interviewStart`); bez niego okno pyta serwer o wydarzenie
 * (bramka na tablicy zna tylko jego id).
 */
export function DebriefDialog({
  open,
  onOpenChange,
  eventId,
  title,
  description,
  intro,
  submitLabel = "Zapisz debrief",
  onSaved,
  interviewStart,
  now: nowOverride,
  readOnly = false,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  eventId: number | null;
  title: string;
  description?: string;
  intro?: React.ReactNode;
  submitLabel?: string;
  /** Po udanym zapisie, PRZED zamknięciem okna. */
  onSaved?: (debrief: Debrief) => void;
  /** Początek rozmowy (ISO); `undefined` = okno odczyta go z serwera. */
  interviewStart?: string;
  /** Zegar dla testów i harnessu. */
  now?: Date;
  /** Podgląd zapisanego debriefu dla roli bez prawa zapisu. */
  readOnly?: boolean;
}) {
  const toast = useToast();
  const qc = useQueryClient();
  const existing = useDebrief(open ? eventId : null);
  // Wydarzenie zawsze — debrief potrzebuje pary (kandydat, rekrutacja), żeby
  // pokazać bieżącą stawkę i kto dostanie informację o jej zmianie (0418).
  const eventInfo = useInterviewEvent(open ? eventId : null);
  const pairCandidateId = existing.data?.candidate_id ?? eventInfo.data?.candidate_id ?? null;
  const pairJobId = existing.data?.job_id ?? eventInfo.data?.job_id ?? null;
  const rateView = useRateChanges(
    open && !readOnly ? pairCandidateId : null,
    open && !readOnly ? pairJobId : null,
  );
  const start = interviewStart ?? eventInfo.data?.start ?? null;
  // Okno może stać otwarte do rozpoczęcia rozmowy — przelicz co 30 s.
  const [tick, setTick] = useState(() => Date.now());
  useEffect(() => {
    if (!open || nowOverride) return;
    // Okno jest zamontowane cały czas — zegar z chwili montowania byłby stary.
    setTick(Date.now());
    const id = window.setInterval(() => setTick(Date.now()), 30_000);
    return () => window.clearInterval(id);
  }, [open, nowOverride]);
  const now = nowOverride ?? new Date(tick);
  const notStarted = start != null && !debriefAvailable(start, now);
  const [outcome, setOutcome] = useState<DebriefOutcome | null>(null);
  const [comment, setComment] = useState("");
  const [questions, setQuestions] = useState<string[]>([""]);
  const [offer, setOffer] = useState<OfferAcceptance | null>(null);
  const [condition, setCondition] = useState("");
  const [notifyDl, setNotifyDl] = useState(true);
  const [noQuestions, setNoQuestions] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [rateChanged, setRateChanged] = useState(false);
  const [rateAmount, setRateAmount] = useState("");
  const [rateNegotiable, setRateNegotiable] = useState<RateNegotiable | null>(null);
  const [rateNote, setRateNote] = useState("");
  const [bulkOpen, setBulkOpen] = useState(false);
  const [bulkText, setBulkText] = useState("");
  const [questionsNote, setQuestionsNote] = useState<string | null>(null);
  const questionRefs = useRef<(HTMLInputElement | null)[]>([]);
  const [focusQuestion, setFocusQuestion] = useState<number | null>(null);
  useEffect(() => {
    if (focusQuestion == null) return;
    questionRefs.current[focusQuestion]?.focus();
    setFocusQuestion(null);
  }, [focusQuestion, questions.length]);

  // Ostatnie pole zawsze puste (dopóki jest miejsce) — pisanie w nim dokłada
  // kolejne. Lista ma wtedy co najwyżej MAX_DEBRIEF_QUESTIONS wypełnionych.
  const withTrailing = (list: string[]) =>
    list.length < MAX_DEBRIEF_QUESTIONS ? [...list, ""] : list;

  const addQuestions = (lines: string[]) => {
    const filled = questions.map((q) => q.trim()).filter(Boolean);
    const { questions: merged, dropped } = mergeQuestions(filled, lines);
    setQuestions(withTrailing(merged));
    setQuestionsNote(
      dropped > 0
        ? `Pominięto ${dropped} — najwyżej ${MAX_DEBRIEF_QUESTIONS} pytań w jednym debriefie.`
        : null,
    );
    return merged.length;
  };

  // Formularz startuje od zapisanego debriefu (poprawka), inaczej pusty —
  // RAZ na otwarcie, dopiero gdy odczyt się rozstrzygnął. Inicjalizacja przy
  // każdej zmianie `existing.data` czyściła zaznaczenia zrobione, zanim
  // odpowiedź zdążyła wrócić.
  const initializedFor = useRef<number | null>(null);
  useEffect(() => {
    if (!open) {
      initializedFor.current = null;
      return;
    }
    if (eventId == null || existing.isPending || initializedFor.current === eventId) return;
    initializedFor.current = eventId;
    const d = existing.isSuccess ? existing.data : null;
    setOutcome(d?.outcome ?? null);
    setComment(d?.candidate_comment ?? "");
    setQuestions(d?.questions?.length ? [...d.questions, ""] : [""]);
    setOffer(d?.offer_acceptance ?? null);
    setCondition(d?.acceptance_condition ?? "");
    setNotifyDl(true);
    setNoQuestions(Boolean(d?.no_client_questions) && !d?.questions?.length);
    setError(null);
    setBulkOpen(false);
    setBulkText("");
    setQuestionsNote(null);
    setRateChanged(Boolean(d?.rate_change));
    setRateAmount(d?.rate_change?.requested_amount ?? "");
    setRateNegotiable(d?.rate_change?.negotiable ?? null);
    setRateNote(d?.rate_change?.note ?? "");
  }, [open, eventId, existing.isPending, existing.isSuccess, existing.data]);

  const typedQuestions = questions.map((q) => q.trim()).filter(Boolean);

  const mutation = useMutation({
    mutationFn: () =>
      interviewCycleApi.saveDebrief(eventId as number, {
        outcome: outcome as DebriefOutcome,
        candidate_comment: comment.trim() || null,
        // „Nie pytał” zaznaczone = pola pytań są wyłączone i nic z nich nie jedzie.
        questions: noQuestions ? [] : typedQuestions,
        offer_acceptance: offer as OfferAcceptance,
        acceptance_condition: condition.trim() || null,
        notify_dl: notifyDl,
        no_client_questions: noQuestions,
        rate_change: rateChanged
          ? {
              amount: rateAmount.replace(",", "."),
              unit: "hourly",
              negotiable: rateNegotiable,
              note: rateNote.trim() || null,
            }
          : null,
      }),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ["interview-cycle"] });
      qc.invalidateQueries({ queryKey: ["calendar-events"] });
      qc.invalidateQueries({ queryKey: ["interview-feedback"] });
      // Skrót debriefu stoi na odznace karty (dok osoby na Tablicy).
      qc.invalidateQueries({ queryKey: ["kanban"] });
      qc.invalidateQueries({ queryKey: ["rate-changes"] });
      toast.showSuccess(
        res.questions_saved > 0
          ? `Debrief zapisany. Nowe pytania klienta: ${res.questions_saved} — zobaczą je następni kandydaci na prepie.`
          : "Debrief zapisany.",
      );
      onSaved?.(res);
      onOpenChange(false);
    },
    onError: (err) => setError(apiErrorMessage(err, "Nie udało się zapisać debriefu.")),
  });

  const submit = () => {
    setError(null);
    if (notStarted) return;
    if (!outcome) {
      setError("Zaznacz, jak poszła rozmowa.");
      return;
    }
    if (!offer) {
      setError("Zaznacz, czy kandydat przyjmie ofertę.");
      return;
    }
    if (!noQuestions && typedQuestions.length === 0) {
      setError(DEBRIEF_QUESTIONS_REQUIRED);
      return;
    }
    if (rateChanged && toHourly(rateAmount, "hourly") == null) {
      setError("Wpisz nową stawkę kandydata albo zaznacz „Bez zmian”.");
      return;
    }
    mutation.mutate();
  };

  const loading =
    open &&
    (existing.isPending ||
      (interviewStart === undefined && eventId != null && eventInfo.isPending));

  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      size="lg"
      title={title}
      description={description}
      footer={
        readOnly ? (
          <div className="flex w-full justify-end">
            <button
              type="button"
              onClick={() => onOpenChange(false)}
              className="h-9 rounded-md border border-border px-4 text-sm font-semibold hover:bg-muted"
            >
              Zamknij
            </button>
          </div>
        ) : (
        <div className="flex w-full flex-wrap items-center justify-between gap-3">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={notifyDl}
              onChange={(e) => setNotifyDl(e.target.checked)}
              className="h-4 w-4"
            />
            Powiadom DL
          </label>
          <div className="flex gap-2">
            <button type="button" onClick={() => onOpenChange(false)} className="h-9 px-4 text-sm text-muted-foreground hover:text-foreground">
              Anuluj
            </button>
            <button
              type="button"
              onClick={submit}
              disabled={mutation.isPending || loading || eventId == null || notStarted}
              title={notStarted && start ? debriefAvailableFromLabel(start, now) : undefined}
              className="h-9 rounded-md bg-primary px-4 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            >
              {submitLabel}
            </button>
          </div>
        </div>
        )
      }
    >
      {notStarted && start && !readOnly ? (
        <div
          role="status"
          data-testid="debrief-not-started"
          className="mb-4 rounded-md border border-warning/40 bg-warning-muted px-3 py-2 text-sm text-warning-muted-foreground"
        >
          <p className="font-semibold">{debriefAvailableFromLabel(start, now)}</p>
          <p>
            Rozmowa u klienta jeszcze się nie odbyła. Po rozmowie zadzwoń do kandydata i zapisz
            pytania klienta — dopiero wtedy kandydat przejdzie dalej.
          </p>
        </div>
      ) : intro ? (
        <div className="mb-4 text-sm text-muted-foreground">{intro}</div>
      ) : null}
      {existing.isError ? (
        <p role="alert" className="mb-3 rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
          Nie udało się wczytać zapisanego debriefu — zapis nadpisze go w całości.
        </p>
      ) : null}
      {readOnly && existing.isSuccess && existing.data == null ? (
        <p className="mb-3 text-sm text-muted-foreground">Debrief tej rozmowy nie został jeszcze zapisany.</p>
      ) : null}
      <fieldset
        disabled={loading || notStarted || readOnly}
        className="space-y-5"
        aria-busy={loading}
      >
        <fieldset>
          <legend className="mb-2 text-sm font-semibold">Jak poszło?</legend>
          <div className="grid grid-cols-3 gap-2">
            {OUTCOMES.map((o) => (
              <label
                key={o}
                className={cn(
                  "flex h-11 cursor-pointer items-center justify-center rounded-lg border text-sm font-semibold",
                  outcome === o ? OUTCOME_TONE[o] : "border-border hover:bg-muted",
                )}
              >
                <input
                  type="radio"
                  name="debrief-outcome"
                  className="sr-only"
                  checked={outcome === o}
                  onChange={() => setOutcome(o)}
                />
                {OUTCOME_LABELS[o]}
              </label>
            ))}
          </div>
          <label htmlFor="debrief-comment" className="mt-3 mb-1 block text-xs font-semibold text-muted-foreground">
            Komentarz kandydata
          </label>
          <textarea
            id="debrief-comment"
            rows={2}
            maxLength={4000}
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            className={cn(INPUT, "resize-none")}
          />
        </fieldset>

        <fieldset>
          <legend className="text-sm font-semibold">Jakie były pytania?</legend>
          <p className="mb-2 text-xs text-muted-foreground">
            Trafiają do karty klienta i tej rekrutacji — następny kandydat zobaczy je w prepie.
          </p>
          <fieldset disabled={noQuestions} className="space-y-2">
            <ol className="space-y-2">
              {(readOnly ? questions.filter((q) => q.trim()) : questions).map((q, i) => (
                <li key={i} className="flex items-center gap-2">
                  <span
                    aria-hidden
                    className="w-6 shrink-0 text-right text-xs tabular-nums text-muted-foreground"
                  >
                    {i + 1}.
                  </span>
                  <input
                    ref={(el) => {
                      questionRefs.current[i] = el;
                    }}
                    aria-label={`Pytanie ${i + 1}`}
                    value={q}
                    maxLength={500}
                    placeholder={
                      i === questions.length - 1 && !q
                        ? "Dopisz pytanie klienta… (Enter dodaje kolejne)"
                        : undefined
                    }
                    onChange={(e) => {
                      const value = e.target.value;
                      setQuestions((list) => {
                        const next = list.map((v, j) => (j === i ? value : v));
                        // Ostatnie pole zawsze puste — pisanie w nim dokłada nowe.
                        if (
                          i === list.length - 1 &&
                          value.trim() &&
                          next.length < MAX_DEBRIEF_QUESTIONS
                        )
                          next.push("");
                        return next;
                      });
                    }}
                    onKeyDown={(e) => {
                      if (e.key !== "Enter" || e.nativeEvent.isComposing) return;
                      e.preventDefault();
                      if (!q.trim()) return;
                      setFocusQuestion(Math.min(i + 1, questions.length - 1));
                    }}
                    onPaste={(e) => {
                      const text = e.clipboardData.getData("text");
                      if (!/\r?\n/.test(text.trim())) return;
                      // Wklejona lista = osobne pytania, nie jedno długie pole.
                      e.preventDefault();
                      const count = addQuestions(splitPastedQuestions(text));
                      setFocusQuestion(Math.min(count, MAX_DEBRIEF_QUESTIONS - 1));
                    }}
                    className={INPUT}
                  />
                  {q && questions.length > 1 && !readOnly ? (
                    <button
                      type="button"
                      aria-label={`Usuń pytanie ${i + 1}`}
                      onClick={() =>
                        setQuestions((list) => {
                          const next = list.filter((_, j) => j !== i);
                          return next.length && next[next.length - 1] === "" ? next : [...next, ""];
                        })
                      }
                      className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-destructive"
                    >
                      <X className="h-4 w-4" />
                    </button>
                  ) : null}
                </li>
              ))}
            </ol>
            {readOnly ? null : (
              <div className="flex flex-wrap items-center gap-2 pl-8">
                <button
                  type="button"
                  disabled={typedQuestions.length >= MAX_DEBRIEF_QUESTIONS}
                  onClick={() => setFocusQuestion(questions.length - 1)}
                  className="inline-flex h-8 items-center gap-1 rounded-md border border-border px-2.5 text-xs font-semibold hover:bg-muted disabled:opacity-50"
                >
                  <Plus className="h-3.5 w-3.5" aria-hidden /> Dodaj pytanie
                </button>
                <button
                  type="button"
                  aria-expanded={bulkOpen}
                  onClick={() => setBulkOpen((v) => !v)}
                  className="h-8 rounded-md border border-border px-2.5 text-xs font-semibold hover:bg-muted"
                >
                  Wklej listę pytań
                </button>
                <span className="text-xs text-muted-foreground">
                  {typedQuestions.length} z {MAX_DEBRIEF_QUESTIONS}
                </span>
              </div>
            )}
            {bulkOpen && !readOnly ? (
              <div className="space-y-2 pl-8">
                <label htmlFor="debrief-bulk" className="block text-xs text-muted-foreground">
                  Każda linia to osobne pytanie. Numery i punktory („1.”, „-”, „•”) zostaną usunięte, a
                  powtórzenia połączone.
                </label>
                <textarea
                  id="debrief-bulk"
                  rows={4}
                  value={bulkText}
                  onChange={(e) => setBulkText(e.target.value)}
                  className={cn(INPUT, "resize-y")}
                />
                <button
                  type="button"
                  disabled={!bulkText.trim()}
                  onClick={() => {
                    addQuestions(splitPastedQuestions(bulkText));
                    setBulkText("");
                    setBulkOpen(false);
                  }}
                  className="h-8 rounded-md bg-primary px-3 text-xs font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
                >
                  Dodaj do listy
                </button>
              </div>
            ) : null}
            {questionsNote ? (
              <p role="status" className="pl-8 text-xs text-warning-muted-foreground">
                {questionsNote}
              </p>
            ) : null}
          </fieldset>
          {readOnly && typedQuestions.length > 0 ? null : (
          <label className="mt-3 flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={noQuestions}
              onChange={(e) => setNoQuestions(e.target.checked)}
              className="h-4 w-4"
            />
            Klient nie zadawał pytań
          </label>
          )}
        </fieldset>

        <fieldset>
          <legend className="mb-2 text-sm font-semibold">Czy przyjmie ofertę?</legend>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {OFFERS.map((o) => (
              <label
                key={o}
                className={cn(
                  "flex h-11 cursor-pointer items-center justify-center rounded-lg border text-sm font-semibold",
                  offer === o
                    ? o === "no"
                      ? "border-destructive bg-destructive/10 text-destructive"
                      : "border-primary bg-primary/10 text-primary"
                    : "border-border hover:bg-muted",
                )}
              >
                <input
                  type="radio"
                  name="debrief-offer"
                  className="sr-only"
                  checked={offer === o}
                  onChange={() => setOffer(o)}
                />
                {OFFER_LABELS[o]}
              </label>
            ))}
          </div>
          <DebriefRateSection
            readOnly={readOnly}
            currentLabel={
              existing.data?.rate_change?.previous ??
              rateView.data?.current?.label ??
              existing.data?.current_rate_label ??
              null
            }
            savedChange={existing.data?.rate_change ?? null}
            changed={rateChanged}
            onChanged={setRateChanged}
            amount={rateAmount}
            onAmount={setRateAmount}
            negotiable={rateNegotiable}
            onNegotiable={setRateNegotiable}
            note={rateNote}
            onNote={setRateNote}
            notice={
              rateView.data
                ? notifyLine(rateView.data, {
                    rising: (() => {
                      const next = toHourly(rateAmount, "hourly");
                      const now =
                        rateView.data.current?.hourly != null
                          ? Number(rateView.data.current.hourly)
                          : null;
                      return next != null && now != null ? next > now : null;
                    })(),
                    reason: "conversation",
                  })
                : null
            }
          />
          <label htmlFor="debrief-condition" className="mt-3 mb-1 block text-xs font-semibold text-muted-foreground">
            {readOnly ? "Warunek / zastrzeżenie" : "Inne warunki"}
          </label>
          <input
            id="debrief-condition"
            maxLength={2000}
            value={condition}
            onChange={(e) => setCondition(e.target.value)}
            placeholder="np. ma drugą ofertę do piątku, urlop w listopadzie"
            className={INPUT}
          />
        </fieldset>

        {error ? (
          <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {error}
          </p>
        ) : null}
      </fieldset>
    </AppModal>
  );
}


/**
 * Stawka kandydata po rozmowie (0418). „Zmieniła się” zapisuje nową stawkę
 * tą samą regułą co panel osoby: ślad w historii stawek, dzwonek DL i Head of
 * Recruitment, zadanie DL przy wzroście po wysłaniu CV. Do 04.10.2026 stawka
 * trafiała do wolnego tekstu „Warunek”, którego nikt nie czytał.
 */
function DebriefRateSection({
  readOnly,
  currentLabel,
  savedChange,
  changed,
  onChanged,
  amount,
  onAmount,
  negotiable,
  onNegotiable,
  note,
  onNote,
  notice,
}: {
  readOnly: boolean;
  currentLabel: string | null;
  savedChange: Debrief["rate_change"] | null;
  changed: boolean;
  onChanged: (v: boolean) => void;
  amount: string;
  onAmount: (v: string) => void;
  negotiable: RateNegotiable | null;
  onNegotiable: (v: RateNegotiable | null) => void;
  note: string;
  onNote: (v: string) => void;
  notice: string | null;
}) {
  if (readOnly) {
    if (!savedChange) return null;
    return (
      <p className="mt-3 text-sm" data-testid="debrief-rate-readonly">
        <span className="font-semibold">Stawka kandydata:</span>{" "}
        {savedChange.previous ? `${savedChange.previous} → ` : ""}
        {savedChange.requested}
      </p>
    );
  }
  return (
    <fieldset
      className="mt-4 space-y-3 rounded-lg border border-warning/40 bg-warning-muted/40 p-3"
      data-testid="debrief-rate"
    >
      <legend className="px-1 text-sm font-semibold">Stawka kandydata</legend>
      <div className="flex flex-wrap gap-2">
        {[
          { v: false, label: `Bez zmian${currentLabel ? ` (${currentLabel})` : ""}` },
          { v: true, label: "Zmieniła się" },
        ].map((o) => (
          <label
            key={String(o.v)}
            className={cn(
              "cursor-pointer rounded-full border px-3 py-1 text-xs font-medium",
              changed === o.v ? "border-primary bg-primary/10 text-primary" : "border-border bg-card hover:bg-muted",
            )}
          >
            <input
              type="radio"
              name="debrief-rate-changed"
              className="sr-only"
              checked={changed === o.v}
              onChange={() => onChanged(o.v)}
            />
            {o.label}
          </label>
        ))}
      </div>
      {changed ? (
        <>
          <div>
            <label htmlFor="debrief-rate-amount" className="mb-1 block text-xs font-semibold text-muted-foreground">
              Nowa stawka B2B netto (zł/h)
            </label>
            <input
              id="debrief-rate-amount"
              inputMode="decimal"
              value={amount}
              onChange={(e) => onAmount(e.target.value)}
              onWheel={blurNumberInputOnWheel}
              className={cn(INPUT, "w-32 tabular-nums")}
            />
          </div>
          <fieldset>
            <legend className="mb-1.5 text-xs font-semibold text-muted-foreground">
              Czy kandydat zejdzie ze stawki?
            </legend>
            <div className="flex flex-wrap gap-2">
              {NEGOTIABLE_OPTIONS.map((o) => (
                <label
                  key={o.value}
                  className={cn(
                    "cursor-pointer rounded-full border px-3 py-1 text-xs font-medium",
                    negotiable === o.value
                      ? "border-primary bg-primary/10 text-primary"
                      : "border-border bg-card hover:bg-muted",
                  )}
                >
                  <input
                    type="radio"
                    name="debrief-rate-negotiable"
                    className="sr-only"
                    checked={negotiable === o.value}
                    onChange={() => onNegotiable(o.value)}
                  />
                  {o.label}
                </label>
              ))}
            </div>
          </fieldset>
          <div>
            <label htmlFor="debrief-rate-note" className="mb-1 block text-xs font-semibold text-muted-foreground">
              Dlaczego więcej (opcjonalnie)
            </label>
            <input
              id="debrief-rate-note"
              maxLength={1000}
              value={note}
              onChange={(e) => onNote(e.target.value)}
              placeholder="np. ma drugą ofertę za 120 zł/h, decyzja do piątku"
              className={INPUT}
            />
          </div>
          {notice ? (
            <p className="text-xs text-muted-foreground" data-testid="debrief-rate-notice">
              {notice}
            </p>
          ) : null}
        </>
      ) : null}
    </fieldset>
  );
}
