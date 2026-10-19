"use client";

import { useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import { useDecideLeave, type LeaveRequestRow } from "@/lib/api/hr-leave";

import { formatRange } from "./leave-format";

/** Wystarczą pola z nagłówka okna — „Mój zespół” podaje wiersz z `to_decide`. */
export type RejectTarget = Pick<LeaveRequestRow, "id" | "user_name" | "start_date" | "end_date">;

interface RejectLeaveDialogProps {
  request: RejectTarget | null;
  onClose: (rejected: boolean) => void;
}

/** Odrzucenie wniosku — powód jest wymagany, osoba zobaczy go w „Mój czas”. */
export function RejectLeaveDialog({ request, onClose }: RejectLeaveDialogProps) {
  const decide = useDecideLeave();
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);

  const close = (rejected: boolean) => {
    setNote("");
    setError(null);
    onClose(rejected);
  };

  const submit = () => {
    if (!request) return;
    if (note.trim().length < 3) {
      setError("Podaj powód — osoba zobaczy go przy wniosku.");
      return;
    }
    decide.mutate(
      { id: request.id, decision: "reject", note: note.trim() },
      {
        onSuccess: () => close(true),
        onError: (err) => setError(apiErrorMessage(err, "Nie udało się odrzucić wniosku.")),
      },
    );
  };

  return (
    <AppModal
      open={request !== null}
      onOpenChange={(open) => (open ? undefined : close(false))}
      title="Odrzucić wniosek?"
      description={
        request
          ? `${request.user_name ?? "Osoba"} · ${formatRange(request.start_date, request.end_date)}`
          : undefined
      }
      footer={
        <>
          <Button variant="ghost" onClick={() => close(false)}>
            Zostaw
          </Button>
          <Button variant="destructive" onClick={submit} disabled={decide.isPending}>
            {decide.isPending ? "Odrzucanie…" : "Odrzuć wniosek"}
          </Button>
        </>
      }
    >
      <FormField label="Powód" htmlFor="leave-reject-note" error={error ?? undefined} required>
        <Textarea
          id="leave-reject-note"
          rows={3}
          maxLength={2000}
          value={note}
          onChange={(event) => setNote(event.target.value)}
        />
      </FormField>
    </AppModal>
  );
}
