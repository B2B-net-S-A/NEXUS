"use client";

import { useId, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Pause } from "lucide-react";

import { useOptionalToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import {
  HOLD_REASON_MAX,
  HOLD_REASON_PRESETS,
  addDaysIso,
  defaultReviewOn,
  hasHoldFormErrors,
  HOLD_REVIEW_MAX_DAYS,
  isOnHold,
  reviewDistanceText,
  shortName,
  validateHoldForm,
  type HoldPayload,
  type HoldRecipient,
  type JobHold,
} from "@/lib/job-hold";
import { invalidateAfterHoldChange, putJobHold, useJobHold } from "@/lib/job-hold-api";
import { cn } from "@/lib/utils";
import { warsawToday } from "@/lib/warsaw-date";

export interface JobHoldDialogProps {
  jobId: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Tytuł rekrutacji w opisie okna (panel DL na pulpicie). */
  jobTitle?: string | null;
  /**
   * Stan z `GET …/hold`, gdy wołający już go ma (harness, testy). Bez niego
   * okno czyta go samo — ten sam klucz cache'u co strona rekrutacji.
   */
  hold?: JobHold | null;
  onSaved?: (hold: JobHold) => void;
  /** Harness `/preview/job-hold` zapisuje lokalnie; domyślnie `PUT …/hold`. */
  save?: (jobId: number, payload: HoldPayload) => Promise<JobHold>;
  /** Tylko dla testów. */
  today?: string;
}

const OTHER = "other";

/**
 * Okno „Wstrzymaj rekrutację” (decyzje Artura 26.11.2026, makieta m4):
 * powód (trzy gotowe albo „Inny…”), „Sprawdzę z klientem” (domyślnie dziś
 * + 14 dni) i „Powiadom rekruterów” z listą z `GET …/hold`. Przy rekrutacji
 * już wstrzymanej to samo okno zmienia powód i termin — bez ponownej
 * wiadomości do rekruterów.
 */
export function JobHoldDialog({
  jobId,
  open,
  onOpenChange,
  jobTitle,
  hold,
  onSaved,
  save = putJobHold,
  today,
}: JobHoldDialogProps) {
  const query = useJobHold(jobId, open && hold === undefined);
  const data = hold === undefined ? query.data : hold;
  const editing = isOnHold(data?.state);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="md" data-testid="job-hold-dialog">
        <DialogHeader>
          <DialogTitle>{editing ? "Zmień powód lub termin" : "Wstrzymaj rekrutację"}</DialogTitle>
          <DialogDescription>
            {editing
              ? "Rekruterzy widzą pas nad Tablicą z nowym powodem i terminem. Wiadomości nie wysyłamy drugi raz."
              : `${jobTitle ? `„${jobTitle}”: ` : ""}rekruterzy zobaczą pas nad Tablicą i ostrzeżenie przy ruchu karty. Rekrutacja wypada z automatów i z daily, zespół zostaje.`}
          </DialogDescription>
        </DialogHeader>
        {open ? (
          hold === undefined && query.isLoading ? (
            <DialogBody>
              <p className="text-sm text-muted-foreground">Wczytywanie…</p>
            </DialogBody>
          ) : (
            <HoldForm
              key={`${jobId}-${data?.since ?? "new"}`}
              jobId={jobId}
              hold={data ?? null}
              loadError={
                hold === undefined && query.isError
                  ? apiErrorMessage(query.error, "Nie udało się wczytać listy rekruterów.")
                  : null
              }
              editing={editing}
              save={save}
              today={today ?? warsawToday()}
              onCancel={() => onOpenChange(false)}
              onSaved={(next) => {
                onOpenChange(false);
                onSaved?.(next);
              }}
            />
          )
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

function initialPreset(reason: string | null | undefined): string | null {
  if (!reason) return null;
  return (HOLD_REASON_PRESETS as readonly string[]).includes(reason) ? reason : OTHER;
}

function HoldForm({
  jobId,
  hold,
  loadError,
  editing,
  save: saveHold,
  today,
  onCancel,
  onSaved,
}: {
  jobId: number;
  hold: JobHold | null;
  loadError: string | null;
  editing: boolean;
  save: (jobId: number, payload: HoldPayload) => Promise<JobHold>;
  today: string;
  onCancel: () => void;
  onSaved: (hold: JobHold) => void;
}) {
  const ids = useId();
  const queryClient = useQueryClient();
  const toast = useOptionalToast();
  const startReason = editing ? hold?.reason : null;
  const [preset, setPreset] = useState<string | null>(initialPreset(startReason));
  const [otherText, setOtherText] = useState(
    initialPreset(startReason) === OTHER ? (startReason ?? "") : "",
  );
  const [reviewOn, setReviewOn] = useState<string>(
    editing ? (hold?.review_on ?? "") : defaultReviewOn(today),
  );
  const [notify, setNotify] = useState(true);
  const [touched, setTouched] = useState(false);

  const reason = preset === OTHER ? otherText : (preset ?? "");
  const errors = validateHoldForm({ reason, reviewOn: reviewOn || null }, today);
  const recipients: HoldRecipient[] = hold?.recipients ?? [];

  const save = useMutation({
    mutationFn: () =>
      saveHold(jobId, {
        reason: reason.trim(),
        review_on: reviewOn || null,
        notify: editing ? false : notify,
      }),
    onSuccess: (next) => {
      invalidateAfterHoldChange(queryClient, jobId, next);
      toast?.showSuccess(
        editing
          ? "Zapisano nowy powód i termin."
          : notify && recipients.length > 0
            ? `Rekrutacja wstrzymana. Wiadomość poszła do ${recipients.length} ${recipients.length === 1 ? "rekrutera" : "rekruterów"}.`
            : "Rekrutacja wstrzymana.",
      );
      onSaved(next);
    },
  });

  const submit = () => {
    setTouched(true);
    if (hasHoldFormErrors(errors)) return;
    save.mutate();
  };
  const distance = reviewOn && !errors.reviewOn ? reviewDistanceText(today, reviewOn) : null;

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
      noValidate
    >
      <DialogBody className="space-y-4">
        <fieldset className="space-y-2">
          <legend className="text-sm font-medium text-foreground">Powód</legend>
          <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label="Powód wstrzymania">
            {[...HOLD_REASON_PRESETS, OTHER].map((value) => {
              const on = preset === value;
              return (
                <button
                  key={value}
                  type="button"
                  role="radio"
                  aria-checked={on}
                  onClick={() => setPreset(value)}
                  className={cn(
                    "hit-area inline-flex h-8 items-center rounded-full border px-3 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                    on
                      ? "border-warning bg-warning-muted font-semibold text-warning-muted-foreground"
                      : "border-border text-foreground hover:bg-muted",
                  )}
                >
                  {value === OTHER ? "Inny…" : value}
                </button>
              );
            })}
          </div>
          {preset === OTHER ? (
            <Textarea
              aria-label="Powód wstrzymania"
              rows={2}
              autoFocus
              maxLength={HOLD_REASON_MAX}
              value={otherText}
              placeholder="np. Klient przesuwa start projektu na luty"
              onChange={(event) => setOtherText(event.target.value)}
            />
          ) : null}
          {touched && errors.reason ? (
            <p role="alert" className="text-sm text-destructive" data-testid="job-hold-reason-error">
              {errors.reason}
            </p>
          ) : null}
        </fieldset>

        <div className="space-y-1.5">
          <div className="flex flex-wrap items-center gap-2">
            <label htmlFor={`${ids}-review`} className="text-sm font-medium text-foreground">
              Sprawdzę z klientem
            </label>
            <Input
              id={`${ids}-review`}
              type="date"
              min={today}
              max={addDaysIso(today, HOLD_REVIEW_MAX_DAYS)}
              value={reviewOn}
              onChange={(event) => setReviewOn(event.target.value)}
              className="h-8 w-[160px]"
            />
            {distance ? <span className="text-sm text-muted-foreground">({distance})</span> : null}
          </div>
          <p className="text-xs text-muted-foreground">
            Tego dnia NEXUS zapyta DL-a „Wznawiamy?”. Po 30 dniach wstrzymania zaproponuje zamknięcie.
          </p>
          {errors.reviewOn ? (
            <p role="alert" className="text-sm text-destructive" data-testid="job-hold-review-error">
              {errors.reviewOn}
            </p>
          ) : null}
        </div>

        {editing ? null : (
          <div className="space-y-1.5">
            <label className="flex items-start gap-2 text-sm text-foreground">
              <Checkbox
                checked={notify}
                onCheckedChange={(value) => setNotify(value === true)}
                className="mt-0.5"
                aria-label="Powiadom rekruterów"
              />
              <span>
                {recipients.length > 0
                  ? `Powiadom ${recipients.length} ${recipients.length === 1 ? "rekrutera, który ma" : "rekruterów, którzy mają"} tu osoby w toku (dzwonek + mail)`
                  : "Powiadom rekruterów, którzy mają tu osoby w toku (dzwonek + mail)"}
              </span>
            </label>
            {recipients.length > 0 ? (
              <ul className="ml-6 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-muted-foreground" data-testid="job-hold-recipients">
                {recipients.map((person) => (
                  <li key={person.user_id}>
                    {shortName(person.name)} · {person.people} {person.people === 1 ? "osoba" : "os."}
                  </li>
                ))}
              </ul>
            ) : loadError ? (
              <p role="alert" className="ml-6 text-xs text-destructive">
                {loadError}
              </p>
            ) : hold ? (
              <p className="ml-6 text-xs text-muted-foreground">
                Nikt nie ma tu teraz osób w toku — wiadomość nie wyjdzie do nikogo.
              </p>
            ) : null}
          </div>
        )}

        {save.isError ? (
          <p role="alert" className="text-sm text-destructive" data-testid="job-hold-save-error">
            {apiErrorMessage(save.error, "Nie udało się wstrzymać rekrutacji.")}
          </p>
        ) : null}
      </DialogBody>
      <DialogFooter>
        <Button type="button" variant="ghost" onClick={onCancel} disabled={save.isPending}>
          Anuluj
        </Button>
        <Button type="submit" loading={save.isPending} data-tour="job.hold.submit" data-testid="job-hold-submit">
          {editing ? (
            "Zapisz"
          ) : (
            <>
              <Pause className="h-4 w-4" aria-hidden="true" />
              Wstrzymaj rekrutację
            </>
          )}
        </Button>
      </DialogFooter>
    </form>
  );
}
