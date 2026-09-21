"use client";

import { useEffect, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, X } from "lucide-react";

import { AppModal } from "@/components/ds/AppModal";
import { useToast } from "@/components/Toast";
import { apiErrorMessage } from "@/lib/api-error";
import { interviewCycleApi, useDebrief } from "@/lib/api/interviewCycle";
import {
  OFFER_LABELS,
  OUTCOME_LABELS,
  candidateLabel,
  pairContext,
  type DebriefOutcome,
  type OfferAcceptance,
  type PairInfo,
} from "@/lib/interview-cycle";
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

/**
 * Debrief po telefonie do kandydata (≤30 min po rozmowie u klienta).
 * Trzy rzeczy, o które prosił zespół: jak poszło, jakie były pytania (trafiają
 * do karty klienta i prepu następnych kandydatów), czy przyjmie ofertę.
 */
export function DebriefModal({
  open,
  onOpenChange,
  eventId,
  pair,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  eventId: number | null;
  pair: PairInfo | null;
}) {
  const toast = useToast();
  const qc = useQueryClient();
  const existing = useDebrief(open ? eventId : null);
  const [outcome, setOutcome] = useState<DebriefOutcome | null>(null);
  const [comment, setComment] = useState("");
  const [questions, setQuestions] = useState<string[]>([""]);
  const [offer, setOffer] = useState<OfferAcceptance | null>(null);
  const [condition, setCondition] = useState("");
  const [notifyDl, setNotifyDl] = useState(true);
  const [error, setError] = useState<string | null>(null);

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
    setError(null);
  }, [open, eventId, existing.isPending, existing.isSuccess, existing.data]);

  const mutation = useMutation({
    mutationFn: () =>
      interviewCycleApi.saveDebrief(eventId as number, {
        outcome: outcome as DebriefOutcome,
        candidate_comment: comment.trim() || null,
        questions: questions.map((q) => q.trim()).filter(Boolean),
        offer_acceptance: offer as OfferAcceptance,
        acceptance_condition: condition.trim() || null,
        notify_dl: notifyDl,
      }),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ["interview-cycle"] });
      qc.invalidateQueries({ queryKey: ["calendar-events"] });
      qc.invalidateQueries({ queryKey: ["interview-feedback"] });
      toast.showSuccess(
        res.questions_saved > 0
          ? `Debrief zapisany. Nowe pytania klienta: ${res.questions_saved} — zobaczą je następni kandydaci na prepie.`
          : "Debrief zapisany.",
      );
      onOpenChange(false);
    },
    onError: (err) => setError(apiErrorMessage(err, "Nie udało się zapisać debriefu.")),
  });

  const submit = () => {
    setError(null);
    if (!outcome) {
      setError("Zaznacz, jak poszła rozmowa.");
      return;
    }
    if (!offer) {
      setError("Zaznacz, czy kandydat przyjmie ofertę.");
      return;
    }
    mutation.mutate();
  };

  const loading = open && existing.isPending;

  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      size="lg"
      title="Debrief po rozmowie u klienta"
      description={pair ? `${candidateLabel(pair)} · ${pairContext(pair)}` : undefined}
      footer={
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
              disabled={mutation.isPending || loading || eventId == null}
              className="h-9 rounded-md bg-primary px-4 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            >
              Zapisz debrief
            </button>
          </div>
        </div>
      }
    >
      {existing.isError ? (
        <p role="alert" className="mb-3 rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
          Nie udało się wczytać zapisanego debriefu — zapis nadpisze go w całości.
        </p>
      ) : null}
      <fieldset disabled={loading} className="space-y-5" aria-busy={loading}>
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
          <div className="space-y-2">
            {questions.map((q, i) => (
              <div key={i} className="flex items-center gap-2">
                <input
                  aria-label={`Pytanie ${i + 1}`}
                  value={q}
                  maxLength={500}
                  placeholder={i === questions.length - 1 ? "Dopisz pytanie klienta…" : undefined}
                  onChange={(e) => {
                    const value = e.target.value;
                    setQuestions((list) => {
                      const next = list.map((v, j) => (j === i ? value : v));
                      // Ostatnie pole zawsze puste — pisanie w nim dokłada nowe.
                      if (i === list.length - 1 && value.trim() && next.length < 20) next.push("");
                      return next;
                    });
                  }}
                  className={INPUT}
                />
                {q && questions.length > 1 ? (
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
              </div>
            ))}
            {questions.length >= 20 ? (
              <p className="text-xs text-muted-foreground">Najwyżej 20 pytań w jednym debriefie.</p>
            ) : (
              <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
                <Plus className="h-3 w-3" aria-hidden /> Kolejne pole pojawi się samo
              </span>
            )}
          </div>
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
          <label htmlFor="debrief-condition" className="mt-3 mb-1 block text-xs font-semibold text-muted-foreground">
            Warunek / zastrzeżenie
          </label>
          <input
            id="debrief-condition"
            maxLength={2000}
            value={condition}
            onChange={(e) => setCondition(e.target.value)}
            placeholder="np. oczekuje min. 190 zł/h, ma drugą ofertę do piątku"
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
