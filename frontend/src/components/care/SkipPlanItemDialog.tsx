"use client";

import { useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import {
  SKIP_REASON_LABELS,
  useUpdatePlanItem,
  type CarePlanItem,
  type SkipReason,
} from "@/lib/api/care";
import { formatIsoDatePl } from "@/lib/date-pl";

const REASONS = Object.keys(SKIP_REASON_LABELS) as SkipReason[];

/** „Pomiń” punkt planu — z powodem z listy (zostaje w śladzie opieki). */
export function SkipPlanItemDialog({
  contractId,
  item,
  onOpenChange,
}: {
  contractId: number;
  item: Pick<CarePlanItem, "id" | "label" | "due_on">;
  onOpenChange: (open: boolean) => void;
}) {
  const update = useUpdatePlanItem(contractId);
  const [reason, setReason] = useState<SkipReason | "">("");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const submit = () => {
    if (!reason) {
      setError("Wybierz powód pominięcia.");
      return;
    }
    setError(null);
    update.mutate(
      { itemId: item.id, status: "skipped", reason, note: note.trim() || null },
      {
        onSuccess: () => onOpenChange(false),
        onError: (err) => setError(apiErrorMessage(err, "Nie udało się pominąć kontaktu.")),
      },
    );
  };
  return (
    <AppModal
      open
      onOpenChange={onOpenChange}
      title="Pomiń kontakt"
      description={`${item.label} · ${formatIsoDatePl(item.due_on)}. Pominięcie zostaje w historii opieki.`}
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Anuluj
          </Button>
          <Button onClick={submit} disabled={update.isPending}>
            {update.isPending ? "Zapisywanie…" : "Pomiń"}
          </Button>
        </>
      }
    >
      <div className="grid gap-3">
        <FormField label="Powód" htmlFor="care-skip-reason" required>
          <Select value={reason} onValueChange={(value) => setReason(value as SkipReason)}>
            <SelectTrigger id="care-skip-reason">
              <SelectValue placeholder="Wybierz powód" />
            </SelectTrigger>
            <SelectContent>
              {REASONS.map((key) => (
                <SelectItem key={key} value={key}>
                  {SKIP_REASON_LABELS[key]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
        <FormField label="Notatka (opcjonalnie)" htmlFor="care-skip-note" description="Bez danych o zdrowiu.">
          <Textarea
            id="care-skip-note"
            rows={2}
            maxLength={500}
            value={note}
            onChange={(event) => setNote(event.target.value)}
          />
        </FormField>
        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : null}
      </div>
    </AppModal>
  );
}
