"use client";

import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { AppModal } from "@/components/ds/AppModal";
import { useToast } from "@/components/Toast";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";
import { candidatesApi, type RateUnit } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import {
  clientRateHistoryQueryKey,
  shortDate,
  useClientRateHistory,
  type ClientRateChangeReason,
} from "@/lib/api/clientRateHistory";
import { blurNumberInputOnWheel } from "@/lib/number-input";
import { cn } from "@/lib/utils";

const INPUT =
  "w-full rounded-md border border-border bg-card px-3 py-2 text-sm focus:outline-hidden focus-visible:ring-2 focus-visible:ring-ring";

const UNITS: { value: RateUnit; label: string }[] = [
  { value: "hourly", label: "zł/h" },
  { value: "daily", label: "zł/dzień" },
  { value: "monthly", label: "zł/mies." },
];

function unitLabel(unit: RateUnit | null | undefined): string {
  return UNITS.find((u) => u.value === unit)?.label ?? "";
}

function parseAmount(raw: string): number | null {
  const value = Number(raw.replace(",", ".").trim());
  return raw.trim() && Number.isFinite(value) && value > 0 ? value : null;
}

/**
 * „Zmień stawkę do klienta” po wysyłce CV (20.10.2026, wariant A). Panel osoby
 * i profil kandydata (Rekrutacje). Powód jest wymagany, słowa DL-a trafiają do
 * notatki ze stawką do klienta (rekruter jej nie czyta). Po zamówieniu na tę
 * parę okno nie zapisuje — stawkę zmienia się w zamówieniu.
 */
export function ClientRateChangeDialog({
  open,
  onOpenChange,
  candidateId,
  jobId,
  description,
  candidateRate = null,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  candidateId: number;
  jobId: number;
  description?: string;
  /** Stawka kandydata w tej rekrutacji — do podglądu marży. */
  candidateRate?: { value: number; unit: RateUnit } | null;
}) {
  const toast = useToast();
  const qc = useQueryClient();
  const view = useClientRateHistory(candidateId, jobId, open);
  const [amount, setAmount] = useState("");
  const [unit, setUnit] = useState<RateUnit>("hourly");
  const [reason, setReason] = useState<ClientRateChangeReason | null>(null);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);

  const current = view.data?.current ?? null;
  useEffect(() => {
    if (!open) return;
    setAmount("");
    setReason(null);
    setNote("");
    setError(null);
  }, [open]);
  useEffect(() => {
    if (open && current?.unit) setUnit(current.unit);
  }, [open, current?.unit]);

  const lock = view.data?.order_lock ?? null;
  const newValue = parseAmount(amount);
  const sameUnit = candidateRate != null && candidateRate.unit === unit;
  const marginNow =
    candidateRate && current && current.unit === candidateRate.unit
      ? current.value - candidateRate.value
      : null;
  const marginNew = sameUnit && newValue != null ? newValue - candidateRate.value : null;

  const mutation = useMutation({
    mutationFn: () =>
      candidatesApi.setRecruitmentClientRate(candidateId, jobId, {
        rate_value: newValue,
        rate_unit: unit,
        rate_currency: "PLN",
        reason: reason ?? undefined,
        note: note.trim() || null,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["kanban"] });
      qc.invalidateQueries({ queryKey: clientRateHistoryQueryKey(candidateId, jobId) });
      qc.invalidateQueries({ queryKey: candidateQueryKeys.historyRoot(candidateId) });
      qc.invalidateQueries({ queryKey: candidateQueryKeys.notes(candidateId) });
      toast.showSuccess("Zapisano stawkę do klienta");
      onOpenChange(false);
    },
    onError: (err) =>
      setError(apiErrorMessage(err, "Nie udało się zapisać stawki do klienta.")),
  });

  const submit = () => {
    setError(null);
    if (newValue == null) {
      setError("Wpisz nową stawkę większą od zera.");
      return;
    }
    if (reason == null) {
      setError("Wybierz, dlaczego zmieniasz stawkę.");
      return;
    }
    mutation.mutate();
  };

  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      title="Zmień stawkę do klienta"
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
            disabled={mutation.isPending || view.isPending || lock != null}
            className="h-9 rounded-md bg-primary px-4 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            Zapisz stawkę
          </button>
        </>
      }
    >
      <div className="space-y-4">
        {view.isError && !view.data ? (
          <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {apiErrorMessage(view.error, "Nie udało się wczytać stawki do klienta.")}
          </p>
        ) : null}

        {view.data?.sent?.label ? (
          <p
            data-testid="client-rate-sent"
            className="rounded-md bg-muted/60 px-3 py-2 text-sm text-muted-foreground"
          >
            Wysłane do klienta:{" "}
            <span className="font-semibold tabular-nums text-foreground">
              {view.data.sent.label}
            </span>{" "}
            · {shortDate(view.data.sent.at)}
            {view.data.sent.by_name ? ` · ${view.data.sent.by_name}` : ""}
            {view.data.changes.length > 0 && view.data.current_label ? (
              <>
                {" "}
                · teraz{" "}
                <span className="font-semibold tabular-nums text-foreground">
                  {view.data.current_label}
                </span>
              </>
            ) : null}
          </p>
        ) : null}

        {view.data && view.data.changes.length > 0 ? (
          <ul data-testid="client-rate-history" className="space-y-1.5 text-xs">
            {view.data.changes.map((c) => (
              <li key={c.at} className="flex flex-wrap gap-x-2">
                <span className="text-muted-foreground">{shortDate(c.at)}</span>
                <span className="tabular-nums">
                  {c.old_label} → <span className="font-semibold">{c.new_label}</span>
                </span>
                <span className="text-muted-foreground">
                  {[c.by_name, c.reason_label].filter(Boolean).join(" · ")}
                </span>
                {c.note ? <span className="basis-full text-muted-foreground">„{c.note}”</span> : null}
              </li>
            ))}
          </ul>
        ) : null}

        {lock ? (
          <p
            role="alert"
            data-testid="client-rate-order-lock"
            className="rounded-md bg-warning-muted px-3 py-2 text-sm text-warning-muted-foreground"
          >
            Ta osoba ma już zamówienie „{lock.title}”. Stawkę do klienta zmień w zamówieniu.{" "}
            <a href={`/contracts/${lock.contract_id}`} className="font-medium underline">
              Otwórz kontrakt z zamówieniem
            </a>
          </p>
        ) : (
          <>
            <div>
              <label
                htmlFor="client-rate-change-amount"
                className="mb-1 block text-xs font-semibold text-muted-foreground"
              >
                Nowa stawka do klienta
              </label>
              <div className="flex gap-2">
                <input
                  id="client-rate-change-amount"
                  inputMode="decimal"
                  value={amount}
                  onChange={(e) => setAmount(e.target.value)}
                  onWheel={blurNumberInputOnWheel}
                  className={cn(INPUT, "w-32 tabular-nums")}
                />
                <select
                  aria-label="Jednostka stawki"
                  value={unit}
                  onChange={(e) => setUnit(e.target.value as RateUnit)}
                  className={cn(INPUT, "w-auto")}
                >
                  {UNITS.map((u) => (
                    <option key={u.value} value={u.value}>
                      {u.label}
                    </option>
                  ))}
                </select>
              </div>
              {candidateRate && marginNew != null ? (
                <p data-testid="client-rate-margin" className="mt-1.5 text-xs text-muted-foreground">
                  Stawka kandydata {candidateRate.value} {unitLabel(candidateRate.unit)} → marża po
                  zmianie{" "}
                  <span
                    className={cn(
                      "font-semibold tabular-nums",
                      marginNew >= 0 ? "text-success" : "text-destructive",
                    )}
                  >
                    {marginNew} {unitLabel(unit)}
                  </span>
                  {marginNow != null ? ` (było ${marginNow} ${unitLabel(unit)})` : ""}
                </p>
              ) : null}
            </div>

            <fieldset>
              <legend className="mb-1.5 text-xs font-semibold text-muted-foreground">
                Dlaczego zmieniasz?
              </legend>
              <div className="flex flex-wrap gap-2">
                {(view.data?.reasons ?? []).map((o) => (
                  <label
                    key={o.value}
                    className={cn(
                      "cursor-pointer rounded-full border px-3 py-1 text-xs font-medium",
                      reason === o.value
                        ? "border-primary bg-primary/10 text-primary"
                        : "border-border hover:bg-muted",
                    )}
                  >
                    <input
                      type="radio"
                      name="client-rate-change-reason"
                      className="sr-only"
                      checked={reason === o.value}
                      onChange={() => setReason(o.value)}
                    />
                    {o.label}
                  </label>
                ))}
              </div>
            </fieldset>

            <div>
              <label
                htmlFor="client-rate-change-note"
                className="mb-1 block text-xs font-semibold text-muted-foreground"
              >
                Notatka (opcjonalnie)
              </label>
              <textarea
                id="client-rate-change-note"
                rows={2}
                maxLength={500}
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="np. klient zszedł do 145 po drugiej rozmowie"
                className={cn(INPUT, "resize-none")}
              />
            </div>

            <p className="text-xs text-muted-foreground">
              Kandydat chce więcej? To nie tutaj — użyj „Zmień” przy stawce kandydata, a sprawa
              trafi do Delivery Leada do decyzji.
            </p>
          </>
        )}

        {error ? (
          <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {error}
          </p>
        ) : null}
      </div>
    </AppModal>
  );
}
