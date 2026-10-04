"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { AppModal } from "@/components/ds/AppModal";
import { useToast } from "@/components/Toast";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";
import { apiErrorMessage } from "@/lib/api-error";
import { blurNumberInputOnWheel } from "@/lib/number-input";
import {
  openCaseLine,
  openRateChange,
  rateChangesApi,
  rateChangesQueryKey,
  suggestedClientRate,
  useRateChanges,
  type RateChange,
  type RateChangesView,
  type RateOutcome,
} from "@/lib/rate-change";
import { cn } from "@/lib/utils";

const INPUT =
  "w-full rounded-md border border-border bg-card px-3 py-2 text-sm focus:outline-hidden focus-visible:ring-2 focus-visible:ring-ring";
const PILL =
  "cursor-pointer rounded-full border px-3 py-1 text-xs font-medium";
const ACTION =
  "rounded-md border border-border bg-card px-2.5 py-1 text-xs font-medium hover:bg-muted disabled:opacity-50";

type Mode = "negotiate" | "outcome" | "raise" | null;

/**
 * Otwarta sprawa zmiany stawki w panelu osoby (0418): stan i przyciski
 * zależne od uprawnień z serwera (`can_manage`, `can_decide`,
 * `can_record_outcome`). Negocjację zleca DL albo Head of Recruitment,
 * o stawce do klienta decyduje DL (D6).
 */
export function RateChangeBanner({
  candidateId,
  jobId,
  onWithdraw,
}: {
  candidateId: number;
  jobId: number;
  /** „Wycofujemy kandydata” — po zapisie decyzji otwiera odrzucenie karty. */
  onWithdraw?: () => void;
}) {
  const view = useRateChanges(candidateId, jobId);
  const change = openRateChange(view.data);
  const [mode, setMode] = useState<Mode>(null);
  const toast = useToast();
  const qc = useQueryClient();
  const refresh = () => {
    qc.invalidateQueries({ queryKey: rateChangesQueryKey(candidateId, jobId) });
    qc.invalidateQueries({ queryKey: ["kanban"] });
    qc.invalidateQueries({ queryKey: ["board-tasks"] });
    qc.invalidateQueries({ queryKey: candidateQueryKeys.historyRoot(candidateId) });
    qc.invalidateQueries({ queryKey: candidateQueryKeys.rateOverview(candidateId) });
  };
  const decide = useMutation({
    mutationFn: (decision: "keep_client" | "withdraw") =>
      rateChangesApi.decide((change as RateChange).id, { decision }),
    onSuccess: (_res, decision) => {
      refresh();
      if (decision === "withdraw") {
        toast.showSuccess("Zapisano. Odrzuć teraz kartę kandydata z powodem.");
        onWithdraw?.();
      } else {
        toast.showSuccess("Stawka do klienta zostaje bez zmian. Rekruter dostał informację.");
      }
    },
    onError: (err) => toast.showError(apiErrorMessage(err, "Nie udało się zapisać decyzji.")),
  });

  if (!change || !view.data) return null;
  const data = view.data;
  const canNegotiate = data.can_manage && change.status === "requested";
  const canDecide =
    data.can_decide && change.requires_decision && ["requested", "agreed"].includes(change.status);
  return (
    <div
      className="mt-2 rounded-lg border border-warning/40 bg-warning-muted/40 px-3 py-2 text-xs"
      data-testid="rate-change-banner"
    >
      <p className="font-medium text-foreground">{openCaseLine(change)}</p>
      {change.note ? <p className="mt-0.5 break-words text-muted-foreground">„{change.note}”</p> : null}
      {canNegotiate || change.can_record_outcome || canDecide ? (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {canNegotiate ? (
            <button type="button" className={ACTION} onClick={() => setMode("negotiate")}>
              Zleć negocjację
            </button>
          ) : null}
          {change.can_record_outcome ? (
            <button type="button" className={ACTION} onClick={() => setMode("outcome")}>
              Zapisz wynik rozmowy
            </button>
          ) : null}
          {canDecide ? (
            <>
              <button type="button" className={ACTION} onClick={() => setMode("raise")}>
                Podnoszę stawkę do klienta
              </button>
              <button
                type="button"
                className={ACTION}
                disabled={decide.isPending}
                onClick={() => decide.mutate("keep_client")}
              >
                Zostawiam stawkę do klienta
              </button>
              <button
                type="button"
                className={cn(ACTION, "text-destructive")}
                disabled={decide.isPending}
                onClick={() => decide.mutate("withdraw")}
              >
                Wycofujemy kandydata
              </button>
            </>
          ) : null}
        </div>
      ) : null}
      {mode === "negotiate" ? (
        <NegotiationDialog change={change} view={data} onClose={() => setMode(null)} onDone={refresh} />
      ) : null}
      {mode === "outcome" ? (
        <OutcomeDialog change={change} onClose={() => setMode(null)} onDone={refresh} />
      ) : null}
      {mode === "raise" ? (
        <RaiseClientDialog change={change} view={data} onClose={() => setMode(null)} onDone={refresh} />
      ) : null}
    </div>
  );
}

function ModalFooter({
  onCancel,
  onSubmit,
  pending,
  label,
}: {
  onCancel: () => void;
  onSubmit: () => void;
  pending: boolean;
  label: string;
}) {
  return (
    <>
      <button
        type="button"
        onClick={onCancel}
        className="h-9 px-4 text-sm text-muted-foreground hover:text-foreground"
      >
        Anuluj
      </button>
      <button
        type="button"
        onClick={onSubmit}
        disabled={pending}
        className="h-9 rounded-md bg-primary px-4 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
      >
        {label}
      </button>
    </>
  );
}

function ErrorLine({ text }: { text: string | null }) {
  return text ? (
    <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
      {text}
    </p>
  ) : null;
}

export function NegotiationDialog({
  change,
  view,
  onClose,
  onDone,
}: {
  change: RateChange;
  view: RateChangesView;
  onClose: () => void;
  onDone: () => void;
}) {
  const toast = useToast();
  const options = view.negotiator_options ?? [];
  const [negotiator, setNegotiator] = useState<number | null>(options[0]?.id ?? null);
  const [target, setTarget] = useState("");
  const [due, setDue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const mutation = useMutation({
    mutationFn: () =>
      rateChangesApi.negotiate(change.id, {
        negotiator_id: negotiator as number,
        target_hourly: target.trim() ? target.replace(",", ".") : null,
        due: due || null,
      }),
    onSuccess: () => {
      onDone();
      toast.showSuccess("Negocjacja zlecona. Osoba dostała zadanie.");
      onClose();
    },
    onError: (err) => setError(apiErrorMessage(err, "Nie udało się zlecić negocjacji.")),
  });
  return (
    <AppModal
      open
      onOpenChange={(o) => !o && onClose()}
      title="Zleć negocjację stawki"
      description={`Kandydat chce ${change.requested.label}${change.previous ? `, było ${change.previous.label}` : ""}.`}
      footer={
        <ModalFooter
          onCancel={onClose}
          onSubmit={() => (negotiator == null ? setError("Wybierz osobę.") : mutation.mutate())}
          pending={mutation.isPending}
          label="Zleć"
        />
      }
    >
      <div className="space-y-3">
        <div>
          <label htmlFor="rate-negotiator" className="mb-1 block text-xs font-semibold text-muted-foreground">
            Kto porozmawia z kandydatem
          </label>
          <select
            id="rate-negotiator"
            value={negotiator ?? ""}
            onChange={(e) => setNegotiator(e.target.value ? Number(e.target.value) : null)}
            className={INPUT}
          >
            {options.map((o) => (
              <option key={o.id} value={o.id}>
                {o.name} — {o.role_label}
              </option>
            ))}
          </select>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label htmlFor="rate-target" className="mb-1 block text-xs font-semibold text-muted-foreground">
              Cel (zł/h, opcjonalnie)
            </label>
            <input
              id="rate-target"
              inputMode="decimal"
              value={target}
              onChange={(e) => setTarget(e.target.value)}
              onWheel={blurNumberInputOnWheel}
              className={cn(INPUT, "tabular-nums")}
            />
          </div>
          <div>
            <label htmlFor="rate-due" className="mb-1 block text-xs font-semibold text-muted-foreground">
              Do kiedy (opcjonalnie)
            </label>
            <input id="rate-due" type="date" value={due} onChange={(e) => setDue(e.target.value)} className={INPUT} />
          </div>
        </div>
        <ErrorLine text={error} />
      </div>
    </AppModal>
  );
}

const OUTCOMES: { value: RateOutcome; label: string }[] = [
  { value: "lower", label: "Zszedł ze stawki" },
  { value: "kept", label: "Nie ustąpił" },
  { value: "withdrew", label: "Rezygnuje" },
];

export function OutcomeDialog({
  change,
  onClose,
  onDone,
}: {
  change: RateChange;
  onClose: () => void;
  onDone: () => void;
}) {
  const toast = useToast();
  const [outcome, setOutcome] = useState<RateOutcome>("lower");
  const [agreed, setAgreed] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const mutation = useMutation({
    mutationFn: () =>
      rateChangesApi.outcome(change.id, {
        outcome,
        agreed_amount: outcome === "lower" ? agreed.replace(",", ".") : null,
        note: note.trim() || null,
      }),
    onSuccess: (res) => {
      onDone();
      toast.showSuccess(
        res.status === "agreed"
          ? "Wynik zapisany. Delivery Lead zdecyduje o stawce do klienta."
          : "Wynik zapisany. Zespół dostał informację.",
      );
      onClose();
    },
    onError: (err) => setError(apiErrorMessage(err, "Nie udało się zapisać wyniku.")),
  });
  const submit = () => {
    setError(null);
    if (outcome === "lower") {
      const n = Number(agreed.replace(",", "."));
      if (!Number.isFinite(n) || n <= 0) {
        setError("Wpisz ustaloną stawkę.");
        return;
      }
    }
    mutation.mutate();
  };
  return (
    <AppModal
      open
      onOpenChange={(o) => !o && onClose()}
      title="Wynik rozmowy o stawce"
      description={`Kandydat chciał ${change.requested.label}${change.previous ? `, było ${change.previous.label}` : ""}.`}
      footer={<ModalFooter onCancel={onClose} onSubmit={submit} pending={mutation.isPending} label="Zapisz wynik" />}
    >
      <div className="space-y-3">
        <fieldset>
          <legend className="mb-1.5 text-xs font-semibold text-muted-foreground">Jak się skończyło</legend>
          <div className="flex flex-wrap gap-2">
            {OUTCOMES.map((o) => (
              <label
                key={o.value}
                className={cn(
                  PILL,
                  outcome === o.value ? "border-primary bg-primary/10 text-primary" : "border-border hover:bg-muted",
                )}
              >
                <input
                  type="radio"
                  name="rate-outcome"
                  className="sr-only"
                  checked={outcome === o.value}
                  onChange={() => setOutcome(o.value)}
                />
                {o.label}
              </label>
            ))}
          </div>
        </fieldset>
        {outcome === "lower" ? (
          <div>
            <label htmlFor="rate-agreed" className="mb-1 block text-xs font-semibold text-muted-foreground">
              Ustalona stawka B2B netto (zł/h)
            </label>
            <input
              id="rate-agreed"
              inputMode="decimal"
              value={agreed}
              onChange={(e) => setAgreed(e.target.value)}
              onWheel={blurNumberInputOnWheel}
              className={cn(INPUT, "w-32 tabular-nums")}
            />
          </div>
        ) : null}
        <div>
          <label htmlFor="rate-outcome-note" className="mb-1 block text-xs font-semibold text-muted-foreground">
            Notatka (opcjonalnie)
          </label>
          <input
            id="rate-outcome-note"
            maxLength={1000}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            className={INPUT}
          />
        </div>
        <ErrorLine text={error} />
      </div>
    </AppModal>
  );
}

export function RaiseClientDialog({
  change,
  view,
  onClose,
  onDone,
}: {
  change: RateChange;
  view: RateChangesView;
  onClose: () => void;
  onDone: () => void;
}) {
  const toast = useToast();
  const [amount, setAmount] = useState(() => suggestedClientRate(view.client_rate, change));
  const [error, setError] = useState<string | null>(null);
  const mutation = useMutation({
    mutationFn: () =>
      rateChangesApi.decide(change.id, {
        decision: "raise_client",
        client_rate: { amount: amount.replace(",", "."), unit: "hourly" },
      }),
    onSuccess: () => {
      onDone();
      toast.showSuccess("Nowa stawka do klienta zapisana.");
      onClose();
    },
    onError: (err) => setError(apiErrorMessage(err, "Nie udało się zapisać stawki do klienta.")),
  });
  const submit = () => {
    const n = Number(amount.replace(",", "."));
    if (!Number.isFinite(n) || n <= 0) {
      setError("Wpisz nową stawkę do klienta.");
      return;
    }
    mutation.mutate();
  };
  return (
    <AppModal
      open
      onOpenChange={(o) => !o && onClose()}
      title="Nowa stawka do klienta"
      description={`Kandydat: ${(change.agreed ?? change.requested).label}${
        view.client_rate ? ` · do klienta teraz ${view.client_rate.label}` : ""
      }.`}
      footer={<ModalFooter onCancel={onClose} onSubmit={submit} pending={mutation.isPending} label="Zapisz" />}
    >
      <div className="space-y-3">
        <div>
          <label htmlFor="rate-client" className="mb-1 block text-xs font-semibold text-muted-foreground">
            Stawka do klienta (zł/h)
          </label>
          <input
            id="rate-client"
            inputMode="decimal"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            onWheel={blurNumberInputOnWheel}
            className={cn(INPUT, "w-32 tabular-nums")}
          />
          <p className="mt-1 text-xs text-muted-foreground">
            Podpowiedź: obecna stawka do klienta powiększona o różnicę stawki kandydata.
          </p>
        </div>
        <ErrorLine text={error} />
      </div>
    </AppModal>
  );
}
