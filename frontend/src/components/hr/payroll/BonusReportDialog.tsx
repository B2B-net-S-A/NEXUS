"use client";

import { useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { apiErrorMessage } from "@/lib/api-error";
import { useReportBonus, type BonusRow } from "@/lib/api/hr-payroll";
import { formatMoney } from "@/lib/money";

/** „Zgłoś”: premia się nie zgadza, więc admin zmienia zasady albo dane (09.11.2026). */
export function BonusReportDialog({ row, onClose }: { row: BonusRow; onClose: () => void }) {
  const { showToast } = useToast();
  const report = useReportBonus();
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);

  const submit = () => {
    if (note.trim().length < 3) {
      setError("Napisz, co się nie zgadza.");
      return;
    }
    setError(null);
    report.mutate(
      { id: row.id, note: note.trim() },
      {
        onSuccess: () => {
          showToast("Zgłoszone do admina", "success");
          onClose();
        },
        onError: (err) => setError(apiErrorMessage(err, "Nie udało się wysłać zgłoszenia.")),
      },
    );
  };

  return (
    <AppModal
      open
      onOpenChange={(value) => {
        if (!value) onClose();
      }}
      title="Zgłoś premię do admina"
      description={`${row.description ?? "Premia"} · ${row.recipient_name ?? "Osoba"} · ${formatMoney(row.amount, row.currency)}`}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Wróć
          </Button>
          <Button onClick={submit} disabled={report.isPending}>
            {report.isPending ? "Wysyłanie…" : "Zgłoś"}
          </Button>
        </>
      }
    >
      <div className="grid gap-3">
        <FormField label="Co się nie zgadza" htmlFor="bonus-report-note">
          <Input
            id="bonus-report-note"
            value={note}
            maxLength={500}
            onChange={(event) => setNote(event.target.value)}
          />
        </FormField>
        <p className="text-sm text-muted-foreground">
          Admin dostanie powiadomienie i zmieni zasadę albo dane kontraktu. Premia przeliczy się sama.
        </p>
        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : null}
      </div>
    </AppModal>
  );
}
