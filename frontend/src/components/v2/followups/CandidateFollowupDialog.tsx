"use client";

/**
 * Okno „Follow-up: <kandydat>” (0372) — zapis wyniku telefonu, gdy klient
 * milczy. Po lewej ściąga na rozmowę: WSZYSTKIE procesy, w których czekamy na
 * klienta, z ostatnią wiadomością od właściciela każdego z nich (żeby
 * dzwoniący nie obiecał czegoś, czego tamten proces już nie obejmuje). Po
 * prawej wynik — kolejną rundę liczy serwer.
 *
 * Makieta: https://claude.ai/artifact/E3rjEeFPRqp2RFTo3cQunj (B).
 */

import { useEffect, useState } from "react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useCandidateFollowup,
  useRecordFollowupOutcome,
  type FollowupDetail,
  type FollowupOutcome,
  type FollowupProcessFlag,
  type FollowupRow,
} from "@/lib/api/candidateFollowups";
import {
  HISTORY_OUTCOME_LABEL,
  OUTCOME_OPTIONS,
  addDaysIso,
  callerReasonSentence,
  columnLabel,
  followupDueLabel,
  followupTone,
  lastContactLabel,
  nextStepSentence,
  shortDate,
  shortPersonName,
  todayInBusinessTz,
} from "@/lib/candidate-followup";
import { cn } from "@/lib/utils";

const TONE_CLASS = {
  danger: "bg-destructive/10 text-destructive",
  warning: "bg-warning-muted text-warning-muted-foreground",
  neutral: "bg-muted text-muted-foreground",
} as const;

const MAX_CALLBACK_DAYS = 60;

export function FollowupDuePill({ row }: { row: Pick<FollowupRow, "state" | "overdue_days" | "due_on"> }) {
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center rounded-full px-2 py-0.5 text-xs font-medium",
        TONE_CLASS[followupTone(row.state)],
      )}
    >
      {followupDueLabel(row)}
    </span>
  );
}

function ProcessList({ row }: { row: FollowupRow }) {
  return (
    <ul className="space-y-2">
      {row.processes.map((p) => (
        <li key={p.job_id} className="rounded-lg border border-border px-3 py-2">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <p className="min-w-0 text-sm font-medium">
              {p.client_name ? `${p.client_name} · ` : ""}
              {p.job_title}
            </p>
            <span className="rounded-full bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">
              {columnLabel(p.column)}
            </span>
          </div>
          <p className="mt-0.5 text-xs text-muted-foreground">
            CV wysłane {shortDate(p.sent_at)}
            {p.owner_name ? ` · prowadzi ${p.owner_name}` : ""} · klient milczy {p.silent_days}{" "}
            {p.silent_days === 1 ? "dzień" : "dni"}
          </p>
          <p className="mt-1.5 rounded-md bg-muted px-2 py-1.5 text-xs text-muted-foreground">
            {p.last_note ? (
              <>
                <span className="font-medium text-foreground">
                  {p.last_note_by ? shortPersonName(p.last_note_by) : "Notatka"}
                  {p.last_note_at ? `, ${shortDate(p.last_note_at)}` : ""}:
                </span>{" "}
                „{p.last_note}”
              </>
            ) : (
              "Brak notatek w tym procesie."
            )}
          </p>
        </li>
      ))}
    </ul>
  );
}

function History({ detail }: { detail: FollowupDetail }) {
  if (detail.history.length === 0) return null;
  return (
    <div className="mt-4">
      <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        Ostatnie follow-upy
      </h4>
      <ul className="space-y-1 text-xs text-muted-foreground">
        {detail.history.map((h) => (
          <li key={`${h.created_at}-${h.outcome}`}>
            <span className="tabular-nums">{shortDate(h.created_at)}</span> ·{" "}
            {shortPersonName(h.user_name) || "ktoś z zespołu"} ·{" "}
            {HISTORY_OUTCOME_LABEL[h.outcome] ?? h.outcome}
            {h.callback_on ? ` (${shortDate(h.callback_on)})` : ""}
          </li>
        ))}
      </ul>
    </div>
  );
}

export interface CandidateFollowupDialogProps {
  candidateId: number | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function CandidateFollowupDialog({
  candidateId,
  open,
  onOpenChange,
}: CandidateFollowupDialogProps) {
  const { showSuccess, showError } = useToast();
  const detail = useCandidateFollowup(candidateId, open);
  const record = useRecordFollowupOutcome(candidateId ?? 0);
  const [outcome, setOutcome] = useState<FollowupOutcome>("connected");
  const [note, setNote] = useState("");
  const [callbackOn, setCallbackOn] = useState("");
  const [flags, setFlags] = useState<Record<number, FollowupProcessFlag>>({});

  useEffect(() => {
    if (!open) {
      setOutcome("connected");
      setNote("");
      setCallbackOn("");
      setFlags({});
    }
  }, [open]);

  const row = detail.data?.followup ?? null;
  const today = todayInBusinessTz();
  const noteRequired = outcome === "changed";
  const invalid =
    (noteRequired && note.trim() === "") || (outcome === "callback" && callbackOn === "");

  const submit = () => {
    if (!row || invalid) return;
    record.mutate(
      {
        outcome,
        note: note.trim() || null,
        callback_on: outcome === "callback" ? callbackOn : null,
        processes: outcome === "changed" ? flags : {},
      },
      {
        onSuccess: (data) => {
          const next = data.followup?.due_on;
          showSuccess(
            next
              ? `Zapisano. Następny follow-up: ${shortDate(next)}.`
              : "Zapisano. Kandydat nie czeka już na odpowiedź klienta.",
          );
          onOpenChange(false);
        },
        onError: (error) => showError(apiErrorMessage(error, "Nie udało się zapisać wyniku telefonu.")),
      },
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="2xl" className="flex max-h-[92dvh] flex-col p-0" aria-describedby="followup-desc">
        <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border px-5 py-3 pr-14">
          <div className="min-w-0 space-y-0.5">
            <DialogTitle className="text-base font-semibold">
              Follow-up: {row?.candidate_name ?? "kandydat"}
            </DialogTitle>
            <DialogDescription id="followup-desc" className="text-xs text-muted-foreground">
              {row ? (
                <>
                  {row.phone ? (
                    <span className="select-all font-mono text-foreground">{row.phone}</span>
                  ) : (
                    "Brak telefonu w profilu"
                  )}{" "}
                  · {lastContactLabel(row)}
                </>
              ) : (
                "Telefon do kandydata, gdy klient milczy."
              )}
            </DialogDescription>
          </div>
          {row && <FollowupDuePill row={row} />}
        </div>

        {detail.isError ? (
          <div className="px-5 py-6 text-sm">
            <p>{apiErrorMessage(detail.error, "Nie udało się wczytać follow-upu.")}</p>
            <Button size="sm" variant="outline" className="mt-3" onClick={() => detail.refetch()}>
              Ponów
            </Button>
          </div>
        ) : !detail.isSuccess ? (
          <p className="px-5 py-6 text-sm text-muted-foreground">Wczytywanie…</p>
        ) : !row ? (
          <p className="px-5 py-6 text-sm">
            Ten kandydat nie czeka już na odpowiedź klienta — follow-up nie jest potrzebny.
          </p>
        ) : (
          <div className="grid min-h-0 flex-1 overflow-y-auto md:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
            <div className="border-b border-border px-5 py-4 md:border-b-0 md:border-r">
              <h3 className="mb-2 text-sm font-semibold">
                Czeka na klienta w {row.processes.length}{" "}
                {row.processes.length === 1 ? "procesie" : "procesach"}
              </h3>
              <ProcessList row={row} />
              <p className="mt-3 border-l-2 border-primary/30 pl-2.5 text-xs text-muted-foreground">
                Powiedz, że kandydat dalej jest w procesach i czekamy na odpowiedź klientów.
                Zapytaj, czy coś się zmieniło: dostępność, stawka, inne oferty.
              </p>
              <p className="mt-2 text-xs text-muted-foreground">
                Dzwoni {row.caller_name ?? "—"}: {callerReasonSentence(row)}.
              </p>
              {detail.data && <History detail={detail.data} />}
            </div>
            <div className="space-y-4 px-5 py-4">
              <fieldset>
                <legend className="mb-2 text-sm font-semibold">Jak poszło?</legend>
                <div className="space-y-1.5">
                  {OUTCOME_OPTIONS.map((opt) => (
                    <label
                      key={opt.value}
                      className={cn(
                        "flex cursor-pointer items-start gap-2.5 rounded-lg border px-3 py-2 text-sm",
                        outcome === opt.value ? "border-primary bg-primary/5" : "border-border",
                      )}
                    >
                      <input
                        type="radio"
                        name="followup-outcome"
                        value={opt.value}
                        checked={outcome === opt.value}
                        onChange={() => setOutcome(opt.value)}
                        className="mt-0.5 accent-primary"
                      />
                      <span>
                        {opt.label}
                        <span className="block text-xs text-muted-foreground">{opt.hint}</span>
                      </span>
                    </label>
                  ))}
                </div>
              </fieldset>

              {outcome === "changed" && row.processes.length > 0 && (
                <fieldset>
                  <legend className="mb-1.5 text-sm font-semibold">Co z każdym procesem?</legend>
                  <div className="space-y-1.5 text-sm">
                    {row.processes.map((p) => (
                      <label key={p.job_id} className="flex flex-wrap items-center justify-between gap-2">
                        <span className="min-w-0 truncate">{p.client_name ?? p.job_title}</span>
                        <select
                          value={flags[p.job_id] ?? "interested"}
                          onChange={(e) =>
                            setFlags((prev) => ({
                              ...prev,
                              [p.job_id]: e.target.value as FollowupProcessFlag,
                            }))
                          }
                          className="rounded-md border border-border bg-background px-2 py-1 text-sm"
                          aria-label={`Proces ${p.client_name ?? p.job_title}`}
                        >
                          <option value="interested">dalej zainteresowany</option>
                          <option value="withdrawing">rezygnuje</option>
                        </select>
                      </label>
                    ))}
                  </div>
                  <p className="mt-1.5 text-xs text-muted-foreground">
                    Właściciel procesu dostanie powiadomienie. Etap nie zmieni się sam.
                  </p>
                </fieldset>
              )}

              {outcome === "callback" && (
                <div>
                  <label htmlFor="followup-callback" className="mb-1 block text-sm font-semibold">
                    Kiedy oddzwonić?
                  </label>
                  <input
                    id="followup-callback"
                    type="date"
                    min={today}
                    max={addDaysIso(today, MAX_CALLBACK_DAYS)}
                    value={callbackOn}
                    onChange={(e) => setCallbackOn(e.target.value)}
                    className="rounded-md border border-border bg-background px-2 py-1.5 text-sm"
                  />
                </div>
              )}

              {(outcome === "connected" || outcome === "changed") && (
                <div>
                  <label htmlFor="followup-note" className="mb-1 block text-sm font-semibold">
                    {noteRequired ? "Co się zmieniło?" : "Notatka (opcjonalnie)"}
                  </label>
                  <Textarea
                    id="followup-note"
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                    rows={3}
                    maxLength={4000}
                    placeholder="np. Dostępny od 01.11, stawka bez zmian."
                  />
                </div>
              )}

              <p className="rounded-md bg-muted px-3 py-2 text-xs text-muted-foreground">
                {nextStepSentence(outcome, callbackOn || null)}
              </p>
            </div>
          </div>
        )}

        <div className="flex flex-wrap justify-end gap-2 border-t border-border px-5 py-3">
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Anuluj
          </Button>
          {row && (
            <Button onClick={submit} disabled={invalid || record.isPending}>
              {record.isPending ? "Zapisywanie…" : "Zapisz"}
            </Button>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
