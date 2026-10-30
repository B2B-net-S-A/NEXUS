"use client";

import { useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { apiErrorMessage } from "@/lib/api-error";
import { useCancelBonus, type BonusRow } from "@/lib/api/hr-payroll";
import { formatMoney } from "@/lib/money";

const REASONS = [
  "Osoba już nie pracuje",
  "Premia się nie należy",
  "Premia należy się innej osobie",
  "Inny powód",
] as const;

/** Usunięcie premii z powodem: wiersz zostaje w historii, automat go nie przywróci. */
export function BonusDeleteDialog({
  row,
  onClose,
}: {
  row: BonusRow;
  onClose: () => void;
}) {
  const { showToast } = useToast();
  const cancel = useCancelBonus();
  const inactive = row.flags?.some((flag) => flag.code === "inactive");
  const [reason, setReason] = useState<string>(inactive ? REASONS[0] : REASONS[1]);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);

  const submit = () => {
    setError(null);
    cancel.mutate(
      { id: row.id, note: note.trim() ? `${reason}: ${note.trim()}` : reason },
      {
        onSuccess: () => {
          showToast("Premia usunięta", "success");
          onClose();
        },
        onError: (err) => setError(apiErrorMessage(err, "Nie udało się usunąć premii.")),
      },
    );
  };

  return (
    <AppModal
      open
      onOpenChange={(value) => {
        if (!value) onClose();
      }}
      title="Usunąć premię?"
      description={`${row.description ?? "Premia"} · ${row.recipient_name ?? "Osoba"} · ${formatMoney(row.amount, row.currency)}`}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Wróć
          </Button>
          <Button variant="destructive" onClick={submit} disabled={cancel.isPending}>
            {cancel.isPending ? "Usuwanie…" : "Usuń premię"}
          </Button>
        </>
      }
    >
      <div className="grid gap-4">
        <FormField label="Powód" htmlFor="bonus-delete-reason">
          <Select value={reason} onValueChange={setReason}>
            <SelectTrigger id="bonus-delete-reason">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {REASONS.map((item) => (
                <SelectItem key={item} value={item}>
                  {item}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
        <FormField label="Uwaga (opcjonalnie)" htmlFor="bonus-delete-note">
          <Input id="bonus-delete-note" value={note} maxLength={500} onChange={(event) => setNote(event.target.value)} />
        </FormField>
        <p className="text-sm text-muted-foreground">
          {row.status === "assigned"
            ? "Osoba dostanie powiadomienie o anulowaniu, bez kwoty."
            : "Premia zniknie z listy, a automat jej nie przywróci. Ślad zostaje w historii."}
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
