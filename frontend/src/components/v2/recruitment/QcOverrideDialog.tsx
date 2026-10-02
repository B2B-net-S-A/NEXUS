"use client";

/**
 * „Przepuść mimo QC” (decyzja Artura 02.10.2026): cztery gotowe powody, opis
 * wymagany tylko przy „Inny powód”, bez minimum znaków. Do 02.10 pole
 * wymagało 10 znaków i zbierało wpisy bez treści. Okno mówi wprost, z czym
 * CV pójdzie dalej. Tylko osoby z uprawnieniem „Rekrutacje: zakładanie,
 * zamykanie, wysyłka CV do klienta” (serwer odmawia reszcie).
 */

import { useId, useState } from "react";
import { Loader2 } from "lucide-react";

import { AppModal } from "@/components/ds/AppModal";
import { Button } from "@/components/ui/button";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/Toast";
import { apiErrorMessage } from "@/lib/api-error";
import { useQcOverride } from "@/lib/api/cvQc";
import {
  QC_OVERRIDE_NOTE_MAX,
  QC_OVERRIDE_REASONS,
  countForm,
  qcOverrideError,
  type QcOverrideReason,
} from "@/lib/cv-qc";

/** Ile niepoprawionych rzeczy wymieniamy z nazwy — reszta jako „i N innych”. */
const PENDING_SHOWN = 4;

export interface QcOverrideDialogProps {
  stageId: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Tytuły rzeczy, które zostają niepoprawione. */
  pending: string[];
  onChanged?: () => void;
}

export function overrideSummary(count: number): string {
  if (count <= 0) return "CV pójdzie dalej mimo wyniku QC.";
  return count === 1
    ? "CV pójdzie dalej z 1 niepoprawioną rzeczą:"
    : `CV pójdzie dalej z ${count} niepoprawionymi rzeczami:`;
}

export function QcOverrideDialog({ stageId, open, onOpenChange, pending, onChanged }: QcOverrideDialogProps) {
  const [reason, setReason] = useState<QcOverrideReason | null>(null);
  const [note, setNote] = useState("");
  const [touched, setTouched] = useState(false);
  const { showSuccess, showError } = useToast();
  const override = useQcOverride(stageId, onChanged);
  const noteId = useId();
  const errorId = useId();

  const error = qcOverrideError(reason, note);
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
    if (error || !reason || override.isPending) return;
    const clean = note.trim();
    override.mutate(clean ? { reason_code: reason, reason: clean } : { reason_code: reason }, {
      onSuccess: () => {
        showSuccess("Przepuszczono mimo QC — powód zapisany w historii.");
        close(false);
      },
      onError: (err) => showError(apiErrorMessage(err, "Nie udało się przepuścić. Spróbuj ponownie.")),
    });
  };
  const rest = pending.length - PENDING_SHOWN;

  return (
    <AppModal
      open={open}
      onOpenChange={close}
      size="md"
      title="Przepuść mimo QC"
      description="Powód zobaczy każdy w historii kandydata."
      footer={
        <>
          <Button variant="outline" onClick={() => close(false)}>
            Anuluj
          </Button>
          <Button onClick={submit} disabled={override.isPending || (touched && !!error)}>
            {override.isPending ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : null}
            Przepuść CV
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
        <div className="rounded-md border border-warning/40 bg-warning-muted px-3 py-2 text-sm text-warning-muted-foreground">
          <p>{overrideSummary(pending.length)}</p>
          {pending.length > 0 ? (
            <ul className="mt-1 list-disc space-y-0.5 pl-5">
              {pending.slice(0, PENDING_SHOWN).map((title, i) => (
                <li key={i}>{title}</li>
              ))}
              {rest > 0 ? <li>i {countForm(rest, ["inna", "inne", "innych"])}</li> : null}
            </ul>
          ) : null}
        </div>
        <RadioGroup
          value={reason ?? ""}
          onValueChange={(value) => setReason(value as QcOverrideReason)}
          aria-label="Dlaczego przepuszczasz?"
          aria-describedby={touched && error ? errorId : undefined}
        >
          {QC_OVERRIDE_REASONS.map(({ code, label }) => {
            const id = `${noteId}-${code}`;
            return (
              <label key={code} htmlFor={id} className="flex cursor-pointer items-center gap-2 text-sm">
                <RadioGroupItem id={id} value={code} />
                {code === "other" ? `${label} — napiszę niżej` : label}
              </label>
            );
          })}
        </RadioGroup>
        <div className="space-y-1">
          <label htmlFor={noteId} className="text-xs font-medium text-muted-foreground">
            {reason === "other" ? "Szczegóły (wymagane)" : "Szczegóły (nie musisz nic wpisywać)"}
          </label>
          <Textarea
            id={noteId}
            rows={2}
            value={note}
            maxLength={QC_OVERRIDE_NOTE_MAX}
            invalid={touched && reason === "other" && !note.trim()}
            onChange={(event) => setNote(event.target.value)}
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
