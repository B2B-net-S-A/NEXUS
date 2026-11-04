"use client";

/**
 * Okno powodu „Pomiń" propozycji (0405, decyzja Artura 30.09.2026).
 *
 * Do 30.09 żadna z 57 nocnych propozycji nie miała decyzji — bez powodu nie
 * wiadomo, czy propozycje są złe, czy niewidziane. Sześć powodów, przy „Inne"
 * wymagany opis. Jeden powód dla całej zaznaczonej grupy.
 */

import { useCallback, useId, useState, type ReactNode } from "react";
import { AppModal } from "@/components/ds/AppModal";
import { Button } from "@/components/ui/button";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Textarea } from "@/components/ui/textarea";
import {
  DISMISS_NOTE_MAX,
  DISMISS_REASON_LABEL,
  DISMISS_REASONS,
  dismissFeedbackError,
  type DismissFeedback,
  type DismissReason,
} from "@/lib/proposal-dismiss";

export interface DismissReasonDialogProps {
  open: boolean;
  /** Ile osób pomijamy — tytuł mówi to wprost przy zaznaczeniu grupy. */
  count: number;
  onOpenChange: (open: boolean) => void;
  onConfirm: (feedback: DismissFeedback) => void;
}

export function dismissDialogTitle(count: number): string {
  if (count <= 1) return "Dlaczego pomijasz tę osobę?";
  const few = count % 10 >= 2 && count % 10 <= 4 && (count % 100 < 12 || count % 100 > 14);
  return `Pomiń ${count} ${few ? "osoby" : "osób"} — dlaczego?`;
}

export function DismissReasonDialog({ open, count, onOpenChange, onConfirm }: DismissReasonDialogProps) {
  const [reason, setReason] = useState<DismissReason | null>(null);
  const [note, setNote] = useState("");
  const [touched, setTouched] = useState(false);
  const noteId = useId();
  const errorId = useId();

  const error = dismissFeedbackError(reason, note);
  const close = (next: boolean) => {
    if (!next) {
      setReason(null);
      setNote("");
      setTouched(false);
    }
    onOpenChange(next);
  };
  const submit = () => {
    setTouched(true);
    if (error || !reason) return;
    const clean = note.trim();
    onConfirm(clean ? { reason, note: clean } : { reason });
    close(false);
  };

  return (
    <AppModal
      open={open}
      onOpenChange={close}
      size="sm"
      title={dismissDialogTitle(count)}
      description="Powód pomaga poprawić propozycje. Osoba wróci z nową wersją CV."
      footer={
        <>
          <Button variant="outline" onClick={() => close(false)}>
            Anuluj
          </Button>
          <Button onClick={submit} disabled={touched && !!error}>
            Pomiń
          </Button>
        </>
      }
    >
      <form
        className="space-y-3"
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <RadioGroup
          value={reason ?? ""}
          onValueChange={(value) => setReason(value as DismissReason)}
          aria-label="Powód pominięcia"
          aria-describedby={touched && error ? errorId : undefined}
        >
          {DISMISS_REASONS.map((value) => {
            const id = `${noteId}-${value}`;
            return (
              <label key={value} htmlFor={id} className="flex cursor-pointer items-center gap-2 text-sm">
                <RadioGroupItem id={id} value={value} />
                {DISMISS_REASON_LABEL[value]}
              </label>
            );
          })}
        </RadioGroup>
        <div className="space-y-1">
          <label htmlFor={noteId} className="text-xs font-medium text-muted-foreground">
            {reason === "other" ? "Opis (wymagany)" : "Opis (opcjonalnie)"}
          </label>
          <Textarea
            id={noteId}
            rows={2}
            value={note}
            maxLength={DISMISS_NOTE_MAX}
            invalid={touched && reason === "other" && !note.trim()}
            onChange={(event) => setNote(event.target.value)}
            placeholder={reason === "other" ? "Np. klient nie przyjmuje osób z tej firmy" : undefined}
          />
        </div>
        {touched && error ? (
          <p id={errorId} role="alert" className="text-xs text-destructive">
            {error}
          </p>
        ) : null}
      </form>
    </AppModal>
  );
}

/**
 * „Pomiń" z pytaniem o powód: `ask(ids)` otwiera okno, a po wyborze woła
 * `onDismiss(ids, feedback)`. `dialog` renderuje się raz w komponencie.
 */
export function useDismissReasonPrompt(onDismiss: (candidateIds: number[], feedback: DismissFeedback) => void): {
  ask: (candidateIds: number[]) => void;
  dialog: ReactNode;
} {
  const [pending, setPending] = useState<number[] | null>(null);
  const ask = useCallback((candidateIds: number[]) => {
    if (candidateIds.length > 0) setPending(candidateIds);
  }, []);
  const dialog = (
    <DismissReasonDialog
      open={pending !== null}
      count={pending?.length ?? 0}
      onOpenChange={(open) => {
        if (!open) setPending(null);
      }}
      onConfirm={(feedback) => {
        if (pending) onDismiss(pending, feedback);
      }}
    />
  );
  return { ask, dialog };
}
