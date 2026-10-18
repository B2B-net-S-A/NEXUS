"use client";

import { useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import { useForwardOff } from "@/lib/api/hr-leave";

import { formatRange } from "./leave-format";

/** Wniosek, którego przekierowanie Kadry wyłączają (wiersz historii albo karty M365). */
export interface ForwardOffTarget {
  id: string;
  user_name: string | null;
  start_date: string;
  end_date: string;
  substitute_name: string | null;
}

interface ForwardOffDialogProps {
  target: ForwardOffTarget | null;
  onClose: (done: boolean) => void;
}

const REASON_MIN = 3;

/**
 * Kadry wyłączają przekierowanie poczty cudzego wniosku. Powód zostaje
 * w historii wniosku; regułę w skrzynce zamyka kolejka Microsoft 365.
 * Włączyć przekierowanie może z powrotem tylko sama osoba.
 */
export function ForwardOffDialog({ target, onClose }: ForwardOffDialogProps) {
  const forwardOff = useForwardOff();
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);

  const close = (done: boolean) => {
    setReason("");
    setError(null);
    onClose(done);
  };

  const submit = () => {
    if (!target) return;
    if (reason.trim().length < REASON_MIN) {
      setError("Podaj powód — zostanie w historii wniosku.");
      return;
    }
    forwardOff.mutate(
      { id: target.id, reason: reason.trim() },
      {
        onSuccess: () => close(true),
        onError: (err) =>
          setError(apiErrorMessage(err, "Nie udało się wyłączyć przekierowania.")),
      },
    );
  };

  return (
    <AppModal
      open={target !== null}
      onOpenChange={(open) => (open ? undefined : close(false))}
      title="Wyłączyć przekierowanie poczty?"
      description={
        target
          ? `${target.user_name ?? "Osoba"} · ${formatRange(target.start_date, target.end_date)}${
              target.substitute_name ? ` · do ${target.substitute_name}` : ""
            }. Reguła w skrzynce zostanie zamknięta, osoba dostanie powiadomienie.`
          : undefined
      }
      footer={
        <>
          <Button variant="ghost" onClick={() => close(false)}>
            Zostaw
          </Button>
          <Button variant="destructive" onClick={submit} disabled={forwardOff.isPending}>
            {forwardOff.isPending ? "Wyłączanie…" : "Wyłącz przekierowanie"}
          </Button>
        </>
      }
    >
      <FormField label="Powód" htmlFor="leave-forward-off-reason" error={error ?? undefined} required>
        <Textarea
          id="leave-forward-off-reason"
          rows={3}
          maxLength={500}
          value={reason}
          onChange={(event) => setReason(event.target.value)}
        />
      </FormField>
    </AppModal>
  );
}
