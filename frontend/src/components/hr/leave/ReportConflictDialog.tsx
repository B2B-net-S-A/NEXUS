"use client";

import { useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import { useReportConflict, type LeaveRequestRow } from "@/lib/api/hr-leave";

import { formatRange } from "./leave-format";

/** Najdłuższa notatka kolizji — lustro `leave_service.CONFLICT_NOTE_MAX`. */
export const CONFLICT_NOTE_MAX = 1000;

interface ReportConflictDialogProps {
  request: LeaveRequestRow | null;
  onClose: (reported: boolean) => void;
}

/**
 * „Zgłoś kolizję” (D5): koordynator pisze, z czym termin koliduje. Zgłoszenie
 * osoby zostaje — to informacja, nie odrzucenie; osoba sama decyduje, czy
 * anulować i zgłosić inny termin.
 */
export function ReportConflictDialog({ request, onClose }: ReportConflictDialogProps) {
  const report = useReportConflict();
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);

  const close = (reported: boolean) => {
    setNote("");
    setError(null);
    onClose(reported);
  };

  const submit = () => {
    if (!request) return;
    if (note.trim().length < 3) {
      setError("Napisz, z czym koliduje termin — osoba zobaczy to w powiadomieniu.");
      return;
    }
    report.mutate(
      { id: request.id, note: note.trim() },
      {
        onSuccess: () => close(true),
        onError: (err) => setError(apiErrorMessage(err, "Nie udało się zgłosić kolizji.")),
      },
    );
  };

  return (
    <AppModal
      open={request !== null}
      onOpenChange={(open) => (open ? undefined : close(false))}
      title="Zgłoś kolizję z terminem"
      description={
        request
          ? `${request.user_name ?? "Osoba"} · ${formatRange(request.start_date, request.end_date)}. Termin zostaje — osoba dostanie Twoją notatkę i sama zdecyduje o zmianie.`
          : undefined
      }
      footer={
        <>
          <Button variant="ghost" onClick={() => close(false)}>
            Anuluj
          </Button>
          <Button onClick={submit} disabled={report.isPending}>
            {report.isPending ? "Wysyłanie…" : "Zgłoś kolizję"}
          </Button>
        </>
      }
    >
      <FormField
        label="Z czym koliduje termin"
        htmlFor="leave-conflict-note"
        description="Np. wdrożenie u klienta, termin projektu, rozmowa z kandydatem."
        error={error ?? undefined}
        required
      >
        <Textarea
          id="leave-conflict-note"
          rows={3}
          maxLength={CONFLICT_NOTE_MAX}
          value={note}
          onChange={(event) => setNote(event.target.value)}
        />
      </FormField>
    </AppModal>
  );
}
