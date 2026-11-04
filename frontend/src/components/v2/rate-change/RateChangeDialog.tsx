"use client";

import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { AppModal } from "@/components/ds/AppModal";
import { useToast } from "@/components/Toast";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";
import { screeningFormQueryKey } from "@/lib/api/screeningForm";
import { apiErrorMessage } from "@/lib/api-error";
import { blurNumberInputOnWheel } from "@/lib/number-input";
import {
  NEGOTIABLE_OPTIONS,
  REASON_OPTIONS,
  notifyLine,
  rateChangesApi,
  rateChangesQueryKey,
  toHourly,
  useRateChanges,
  type RateChangeReason,
  type RateChangeUnit,
  type RateNegotiable,
} from "@/lib/rate-change";
import { cn } from "@/lib/utils";

const INPUT =
  "w-full rounded-md border border-border bg-card px-3 py-2 text-sm focus:outline-hidden focus-visible:ring-2 focus-visible:ring-ring";

const UNITS: { value: RateChangeUnit; label: string }[] = [
  { value: "hourly", label: "zł/h" },
  { value: "daily", label: "zł/dzień" },
  { value: "monthly", label: "zł/mies." },
];

/**
 * „Zmień stawkę kandydata” w tej rekrutacji (0418). Panel osoby na Tablicy
 * i profil kandydata (Rekrutacje) — każda zmiana idzie jedną regułą serwera:
 * ślad w historii stawek, dzwonek DL i Head of Recruitment od „Zweryfikowany”,
 * zadanie DL przy wzroście po wysłaniu CV.
 */
export function RateChangeDialog({
  open,
  onOpenChange,
  candidateId,
  jobId,
  title = "Zmień stawkę kandydata",
  description,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  candidateId: number;
  jobId: number;
  title?: string;
  description?: string;
}) {
  const toast = useToast();
  const qc = useQueryClient();
  const view = useRateChanges(open ? candidateId : null, open ? jobId : null);
  const [amount, setAmount] = useState("");
  const [unit, setUnit] = useState<RateChangeUnit>("hourly");
  const [reason, setReason] = useState<RateChangeReason>("conversation");
  const [negotiable, setNegotiable] = useState<RateNegotiable | null>(null);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setAmount("");
    setUnit("hourly");
    setReason("conversation");
    setNegotiable(null);
    setNote("");
    setError(null);
  }, [open]);

  const current = view.data?.current ?? null;
  const newHourly = toHourly(amount, unit);
  const currentHourly = current?.hourly != null ? Number(current.hourly) : null;
  const rising = newHourly != null && currentHourly != null ? newHourly > currentHourly : null;

  const mutation = useMutation({
    mutationFn: () =>
      rateChangesApi.create({
        candidate_id: candidateId,
        job_id: jobId,
        amount: String(amount).replace(",", "."),
        unit,
        reason,
        note: note.trim() || null,
        negotiable,
      }),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ["kanban"] });
      qc.invalidateQueries({ queryKey: rateChangesQueryKey(candidateId, jobId) });
      // Widok „Screening” w doku pokazuje stawkę pary ze stanu formularza.
      qc.invalidateQueries({ queryKey: screeningFormQueryKey(jobId, candidateId) });
      qc.invalidateQueries({ queryKey: candidateQueryKeys.historyRoot(candidateId) });
      qc.invalidateQueries({ queryKey: candidateQueryKeys.rateOverview(candidateId) });
      qc.invalidateQueries({ queryKey: candidateQueryKeys.timelineRoot(candidateId) });
      if (res.unchanged) {
        toast.showInfo("Stawka bez zmian — taka sama jak dotąd.");
      } else {
        toast.showSuccess(
          view.data?.notifies
            ? "Stawka zapisana. Delivery Lead i Head of Recruitment dostali powiadomienie."
            : "Stawka zapisana w historii stawek.",
        );
      }
      onOpenChange(false);
    },
    onError: (err) => setError(apiErrorMessage(err, "Nie udało się zapisać stawki.")),
  });

  const submit = () => {
    setError(null);
    if (newHourly == null) {
      setError("Wpisz nową stawkę większą od zera.");
      return;
    }
    mutation.mutate();
  };

  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      title={title}
      description={description}
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
            onClick={submit}
            disabled={mutation.isPending || view.isPending}
            className="h-9 rounded-md bg-primary px-4 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            Zapisz stawkę
          </button>
        </>
      }
    >
      <div className="space-y-4">
        {view.isError ? (
          <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {apiErrorMessage(view.error, "Nie udało się wczytać bieżącej stawki.")}
          </p>
        ) : null}
        <div className="grid gap-3 sm:grid-cols-[auto_minmax(0,1fr)]">
          <div>
            <div className="mb-1 text-xs font-semibold text-muted-foreground">Teraz</div>
            <div className="flex h-9 items-center rounded-md border border-border bg-muted/40 px-3 text-sm tabular-nums text-muted-foreground">
              {view.isPending ? "…" : (current?.label ?? "brak stawki")}
            </div>
          </div>
          <div>
            <label htmlFor="rate-change-amount" className="mb-1 block text-xs font-semibold text-muted-foreground">
              Nowa stawka B2B netto
            </label>
            <div className="flex gap-2">
              <input
                id="rate-change-amount"
                inputMode="decimal"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                onWheel={blurNumberInputOnWheel}
                className={cn(INPUT, "w-32 tabular-nums")}
              />
              <select
                aria-label="Jednostka stawki"
                value={unit}
                onChange={(e) => setUnit(e.target.value as RateChangeUnit)}
                className={cn(INPUT, "w-auto")}
              >
                {UNITS.map((u) => (
                  <option key={u.value} value={u.value}>
                    {u.label}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </div>

        <fieldset>
          <legend className="mb-1.5 text-xs font-semibold text-muted-foreground">Skąd ta zmiana</legend>
          <div className="flex flex-wrap gap-2">
            {REASON_OPTIONS.map((o) => (
              <label
                key={o.value}
                className={cn(
                  "cursor-pointer rounded-full border px-3 py-1 text-xs font-medium",
                  reason === o.value ? "border-primary bg-primary/10 text-primary" : "border-border hover:bg-muted",
                )}
              >
                <input
                  type="radio"
                  name="rate-change-reason"
                  className="sr-only"
                  checked={reason === o.value}
                  onChange={() => setReason(o.value)}
                />
                {o.label}
              </label>
            ))}
          </div>
        </fieldset>

        {reason !== "typo" ? (
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
                      : "border-border hover:bg-muted",
                  )}
                >
                  <input
                    type="radio"
                    name="rate-change-negotiable"
                    className="sr-only"
                    checked={negotiable === o.value}
                    onChange={() => setNegotiable(o.value)}
                  />
                  {o.label}
                </label>
              ))}
            </div>
          </fieldset>
        ) : null}

        <div>
          <label htmlFor="rate-change-note" className="mb-1 block text-xs font-semibold text-muted-foreground">
            Notatka (opcjonalnie)
          </label>
          <textarea
            id="rate-change-note"
            rows={2}
            maxLength={1000}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="np. ma drugą ofertę za 120 zł/h, decyzja do piątku"
            className={cn(INPUT, "resize-none")}
          />
        </div>

        {view.data ? (
          <p
            data-testid="rate-change-notify"
            className="rounded-md bg-info-muted px-3 py-2 text-xs text-info-muted-foreground"
          >
            {notifyLine(view.data, { rising, reason })}
          </p>
        ) : null}

        {error ? (
          <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {error}
          </p>
        ) : null}
      </div>
    </AppModal>
  );
}
