"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Phone } from "lucide-react";

import { AppModal } from "@/components/ds/AppModal";
import { useToast } from "@/components/Toast";
import { apiErrorMessage } from "@/lib/api-error";
import { prep2SkipApi } from "@/lib/api/prepMeetings";
import {
  PREP2_SKIP_REASON_OPTIONS,
  candidateLabel,
  defaultPrecallAt,
  formatDayLabel,
  formatTime,
  pairContext,
  prep2SkipHint,
  prep2SkipReasonText,
  type PairInfo,
  type Prep2Skip,
  type Prep2SkipReason,
  type Prep2SkipStatus,
} from "@/lib/interview-cycle";
import { cn } from "@/lib/utils";

const INPUT =
  "w-full rounded-md border border-border bg-card px-3 py-2 text-sm focus:outline-hidden focus-visible:ring-2 focus-visible:ring-ring";

const REASONS = Object.keys(PREP2_SKIP_REASON_OPTIONS) as Prep2SkipReason[];

function useRefreshCycle() {
  const qc = useQueryClient();
  return () => {
    qc.invalidateQueries({ queryKey: ["interview-cycle"] });
    qc.invalidateQueries({ queryKey: ["kanban"] });
  };
}

/**
 * Prep 2 pod krokiem w panelu osoby i w kalendarzu (0480, decyzja Artura
 * 20.10.2026): przycisk „Rozmowa bez Prepu 2…” tylko tuż przed rozmową,
 * po odbytym Prepie 1, a po zapisie — powód, kto i telefon przed rozmową.
 * Poza wyjątkiem jedno zdanie, dlaczego przycisku nie ma.
 */
export function Prep2SkipControls({
  pair,
  status,
  skip,
  remaining = [],
  interviewAt,
  readOnly = false,
}: {
  pair: PairInfo;
  status: Prep2SkipStatus | undefined;
  skip: Prep2Skip | null | undefined;
  remaining?: string[];
  interviewAt: string | null;
  readOnly?: boolean;
}) {
  const [dialog, setDialog] = useState<"skip" | "call" | null>(null);

  if (status === "skipped" && skip) {
    return (
      <div
        className="space-y-1.5 rounded-lg border border-border bg-muted/40 px-3 py-2.5 text-xs"
        data-testid="prep2-skip-summary"
      >
        <div className="text-foreground">
          <span className="font-semibold">Bez Prepu 2:</span> {prep2SkipReasonText(skip)}
          {skip.created_by_name ? (
            <span className="text-muted-foreground"> · {skip.created_by_name}</span>
          ) : null}
        </div>
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <Phone className="h-3.5 w-3.5 text-muted-foreground" aria-hidden />
          {skip.call_done_at ? (
            <span className="text-foreground">
              Telefon przed rozmową zrobiony · {formatDayLabel(skip.call_done_at)}{" "}
              {formatTime(skip.call_done_at)}
            </span>
          ) : (
            <>
              <span className="font-semibold text-warning-muted-foreground">
                Telefon przed rozmową · {formatDayLabel(skip.call_at)} {formatTime(skip.call_at)}
              </span>
              {!readOnly ? (
                <button
                  type="button"
                  onClick={() => setDialog("call")}
                  className="ml-auto h-7 rounded-md border border-border bg-card px-2.5 font-semibold hover:bg-muted"
                >
                  Zrobione
                </button>
              ) : null}
            </>
          )}
        </div>
        {skip.call_note ? (
          <p className="whitespace-pre-line break-words text-muted-foreground">{skip.call_note}</p>
        ) : null}
        {dialog === "call" ? (
          <PrecallDoneDialog
            open
            onOpenChange={(o) => !o && setDialog(null)}
            pair={pair}
            skip={skip}
          />
        ) : null}
      </div>
    );
  }

  const hint = prep2SkipHint(status);
  if (!hint) return null;
  return (
    <div
      className={cn(
        "space-y-2 rounded-lg px-3 py-2.5 text-xs",
        status === "prep1_weak" ? "bg-destructive/10 text-destructive" : "bg-muted/40 text-muted-foreground",
      )}
      data-testid="prep2-skip-hint"
      data-status={status}
    >
      <p>{hint}</p>
      {status === "allowed" && !readOnly ? (
        <button
          type="button"
          onClick={() => setDialog("skip")}
          className="h-8 rounded-md border border-border bg-card px-3 font-semibold text-foreground hover:bg-muted"
        >
          Rozmowa bez Prepu 2…
        </button>
      ) : null}
      {dialog === "skip" ? (
        <SkipPrep2Dialog
          open
          onOpenChange={(o) => !o && setDialog(null)}
          pair={pair}
          interviewAt={interviewAt}
          remaining={remaining}
        />
      ) : null}
    </div>
  );
}

/** Okno „Rozmowa bez Prepu 2”: powód z listy i telefon do kandydata przed rozmową. */
export function SkipPrep2Dialog({
  open,
  onOpenChange,
  pair,
  interviewAt,
  remaining = [],
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  pair: PairInfo;
  interviewAt: string | null;
  remaining?: string[];
}) {
  const toast = useToast();
  const refresh = useRefreshCycle();
  const [reason, setReason] = useState<Prep2SkipReason | null>(null);
  const [note, setNote] = useState("");
  const [willCall, setWillCall] = useState(true);
  const [callAt, setCallAt] = useState(() => defaultPrecallAt(interviewAt));
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      prep2SkipApi.create({
        candidate_id: pair.candidate_id,
        job_id: pair.job_id,
        reason: reason as Prep2SkipReason,
        reason_note: note.trim() || null,
        call_at: new Date(callAt).toISOString(),
      }),
    onSuccess: () => {
      refresh();
      toast.showSuccess(
        "Zapisane: rozmowa bez Prepu 2. Delivery Lead dostał informację, a telefon do kandydata jest na liście „Do zrobienia”.",
      );
      onOpenChange(false);
    },
    onError: (err) => setError(apiErrorMessage(err, "Nie udało się zapisać rozmowy bez Prepu 2.")),
  });

  const submit = () => {
    setError(null);
    if (!reason) {
      setError("Wybierz, dlaczego nie będzie Prepu 2.");
      return;
    }
    if (reason === "other" && !note.trim()) {
      setError("Opisz powód w kilku słowach.");
      return;
    }
    if (!willCall) {
      setError("Bez Prepu 2 trzeba zadzwonić do kandydata przed rozmową.");
      return;
    }
    if (!callAt) {
      setError("Podaj, kiedy zadzwonisz do kandydata.");
      return;
    }
    if (interviewAt && new Date(callAt) >= new Date(interviewAt)) {
      setError("Telefon musi być przed rozmową u klienta.");
      return;
    }
    mutation.mutate();
  };

  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      title="Rozmowa bez Prepu 2"
      description={`${candidateLabel(pair)} · ${pairContext(pair)}${
        interviewAt
          ? ` · rozmowa u klienta: ${formatDayLabel(interviewAt)} ${formatTime(interviewAt)}`
          : ""
      }`}
      footer={
        <>
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            className="h-9 px-4 text-sm text-muted-foreground hover:text-foreground"
          >
            Wróć — zaplanuję Prep 2
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={mutation.isPending}
            className="h-9 rounded-md bg-primary px-4 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            Zapisz — rozmowa bez Prepu 2
          </button>
        </>
      }
    >
      <div className="space-y-4">
        {error ? (
          // Na górze okna — na laptopie 1280 × 720 dół treści jest pod zgięciem.
          <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {error}
          </p>
        ) : null}
        <fieldset className="space-y-1.5">
          <legend className="mb-1 text-xs font-semibold text-muted-foreground">
            Dlaczego nie będzie Prepu 2?
          </legend>
          {REASONS.map((r) => (
            <label
              key={r}
              className={cn(
                "flex cursor-pointer items-start gap-2.5 rounded-md border px-3 py-2 text-sm",
                reason === r ? "border-primary bg-primary/10" : "border-border",
              )}
            >
              <input
                type="radio"
                name="prep2-skip-reason"
                value={r}
                checked={reason === r}
                onChange={() => setReason(r)}
                className="mt-0.5 accent-primary"
              />
              {PREP2_SKIP_REASON_OPTIONS[r]}
            </label>
          ))}
          {reason === "other" ? (
            <textarea
              aria-label="Opis powodu"
              rows={2}
              maxLength={500}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              className={cn(INPUT, "resize-none")}
            />
          ) : null}
        </fieldset>

        <div className="space-y-2 rounded-lg border border-border bg-muted/40 p-3">
          <label className="flex cursor-pointer items-start gap-2.5 text-sm">
            <input
              type="checkbox"
              checked={willCall}
              onChange={(e) => setWillCall(e.target.checked)}
              className="mt-0.5 accent-primary"
            />
            <span>
              <span className="font-semibold">Zadzwonię do kandydata przed rozmową</span> — 10–15
              minut o tym, czego nie było na Prepie 1.
            </span>
          </label>
          <div className="flex flex-wrap items-center gap-2 pl-6 text-sm">
            <label htmlFor="prep2-skip-call-at" className="text-xs font-semibold text-muted-foreground">
              Kiedy
            </label>
            <input
              id="prep2-skip-call-at"
              type="datetime-local"
              value={callAt}
              onChange={(e) => setCallAt(e.target.value)}
              className={cn(INPUT, "w-auto")}
            />
          </div>
          {remaining.length > 0 ? (
            <div className="pl-6 text-xs text-muted-foreground">
              Do omówienia (nie było na Prepie 1):
              <ul className="mt-0.5 list-disc pl-4 text-foreground">
                {remaining.map((point) => (
                  <li key={point}>{point}</li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>

        <p className="text-xs text-muted-foreground">
          Zobaczy to Delivery Lead rekrutacji. Pominięcie liczy się w raporcie „Jakość prepów”.
        </p>
      </div>
    </AppModal>
  );
}

/** Telefon przed rozmową (zamiast Prepu 2) odbyty — z krótką notatką. */
export function PrecallDoneDialog({
  open,
  onOpenChange,
  pair,
  skip,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  pair: PairInfo;
  skip: Prep2Skip;
}) {
  const toast = useToast();
  const refresh = useRefreshCycle();
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const mutation = useMutation({
    mutationFn: () => prep2SkipApi.callDone(skip.id, note.trim() || null),
    onSuccess: () => {
      refresh();
      toast.showSuccess("Telefon przed rozmową odhaczony.");
      onOpenChange(false);
    },
    onError: (err) => setError(apiErrorMessage(err, "Nie udało się odhaczyć telefonu.")),
  });
  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      title="Telefon przed rozmową"
      description={`${candidateLabel(pair)} · ${pairContext(pair)}`}
      footer={
        <>
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            className="h-9 px-4 text-sm text-muted-foreground hover:text-foreground"
          >
            Anuluj
          </button>
          <button
            type="button"
            onClick={() => {
              setError(null);
              mutation.mutate();
            }}
            disabled={mutation.isPending}
            className="h-9 rounded-md bg-primary px-4 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            Zrobione
          </button>
        </>
      }
    >
      <div className="space-y-3">
        <p className="text-sm text-foreground">
          Rozmowa bez Prepu 2: {prep2SkipReasonText(skip)}.
        </p>
        <div>
          <label htmlFor="precall-note" className="mb-1 block text-xs font-semibold text-muted-foreground">
            Co omówiliście (opcjonalnie)
          </label>
          <textarea
            id="precall-note"
            rows={3}
            maxLength={2000}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            className={cn(INPUT, "resize-none")}
          />
        </div>
        {error ? (
          <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {error}
          </p>
        ) : null}
      </div>
    </AppModal>
  );
}
