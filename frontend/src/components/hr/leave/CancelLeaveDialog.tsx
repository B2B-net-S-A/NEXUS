"use client";

import { useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import { useCancelTeamLeave, type LeaveRequestRow } from "@/lib/api/hr-leave";

import { pastCancelText } from "./leave-format";

interface CancelLeaveDialogProps {
  /** Wiersz historii, którego termin już trwa albo minął (`cancelNeedsReason`). */
  request: LeaveRequestRow | null;
  /** „Dziś” kalendarza firmy (`warsawToday()`). */
  today: string;
  /** Zapisany wiersz po cofnięciu, `null` — okno zamknięte bez zmian. */
  onClose: (saved: LeaveRequestRow | null) => void;
}

const REASON_MIN = 3;
const REASON_MAX = 500;

/**
 * Przełożony albo Kadry cofają nieobecność, która już trwa albo minęła
 * (decyzja Artura 28.10.2026). Osoba faktycznie była nieobecna, więc cofnięcie
 * wymaga powodu: idzie do śladu HR i do powiadomienia osoby (w mailu go nie
 * ma). Termin w przyszłości anuluje się zwykłym potwierdzeniem, bez powodu.
 */
export function CancelLeaveDialog({ request, today, onClose }: CancelLeaveDialogProps) {
  const cancel = useCancelTeamLeave();
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);

  const close = (saved: LeaveRequestRow | null) => {
    setReason("");
    setError(null);
    onClose(saved);
  };

  const submit = () => {
    if (!request) return;
    const text = reason.trim();
    if (text.length < REASON_MIN) {
      setError("Podaj powód — osoba zobaczy go w powiadomieniu.");
      return;
    }
    cancel.mutate(
      { id: request.id, reason: text },
      {
        onSuccess: (saved) => close(saved),
        onError: (err) => setError(apiErrorMessage(err, "Nie udało się cofnąć nieobecności.")),
      },
    );
  };

  const copy = request ? pastCancelText(request, today) : null;
  const confirmLabel = request?.status === "pending" ? "Anuluj wniosek" : "Cofnij nieobecność";

  return (
    <AppModal
      open={request !== null}
      onOpenChange={(open) => (open ? undefined : close(null))}
      title={copy?.title ?? ""}
      description={copy?.text}
      footer={
        <>
          <Button variant="ghost" onClick={() => close(null)} disabled={cancel.isPending}>
            Zostaw
          </Button>
          <Button variant="destructive" onClick={submit} disabled={cancel.isPending}>
            {cancel.isPending ? "Cofanie…" : confirmLabel}
          </Button>
        </>
      }
    >
      <FormField
        label="Powód (wymagany, widzi go osoba)"
        htmlFor="leave-cancel-reason"
        error={error ?? undefined}
      >
        <Textarea
          id="leave-cancel-reason"
          rows={3}
          maxLength={REASON_MAX}
          value={reason}
          onChange={(event) => setReason(event.target.value)}
        />
      </FormField>
    </AppModal>
  );
}
