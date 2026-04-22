"use client";

import * as React from "react";
import { useState, useEffect } from "react";
import { AlertTriangle, Mail } from "lucide-react";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import { Textarea } from "@/components/ui/textarea";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";

interface RejectionReason {
  id: string;
  label: string;
  applies_to: ("rejected" | "withdrawn")[];
}

type PreviousStageCategory = "internal" | "external" | null;

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  terminalType: "rejected" | "withdrawn";
  reasons: RejectionReason[];
  // Stage the candidate is coming FROM. Drives the default state of the
  // "send email" checkbox: pre-checked for external (= client-visible)
  // rejections, off for early-internal ones. Null when unknown (e.g.
  // quick-action path) — defaults to off to avoid surprise emails.
  previousStageCategory?: PreviousStageCategory;
  onConfirm: (
    reasonId: string,
    notes: string,
    sendRejectionEmail: boolean | null
  ) => void;
}

const TYPE_LABEL: Record<string, string> = {
  rejected: "Odrzuć kandydata",
  withdrawn: "Kandydat wycofany",
};

export function RejectionV2({
  open,
  onOpenChange,
  terminalType,
  reasons,
  previousStageCategory = null,
  onConfirm,
}: Props) {
  const [reasonId, setReasonId] = useState("");
  const [notes, setNotes] = useState("");

  // Only `rejected` triggers the auto-email — withdrawals are initiated by
  // the candidate, no notification needed from our side. For `rejected`,
  // we pre-check when the previous stage was external (client-visible).
  const emailAvailable =
    terminalType === "rejected" && previousStageCategory === "external";
  const [sendEmail, setSendEmail] = useState<boolean>(emailAvailable);

  // Reset defaults when modal re-opens (e.g. user bails, opens again).
  useEffect(() => {
    if (open) {
      setReasonId("");
      setNotes("");
      setSendEmail(emailAvailable);
    }
  }, [open, emailAvailable]);

  const filtered = reasons.filter((r) => r.applies_to.includes(terminalType));

  const handleConfirm = () => {
    // Pass explicit boolean only when the checkbox is user-controlled; else
    // defer to backend auto-decision with `null`.
    const emailFlag: boolean | null = emailAvailable ? sendEmail : null;
    onConfirm(reasonId, notes, emailFlag);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="md">
        <DialogHeader>
          <div className="flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-[hsl(var(--accent))]" />
            <DialogTitle>{TYPE_LABEL[terminalType]}</DialogTitle>
          </div>
          <DialogDescription>
            Podaj powód — pomoże to raportom o lejku rekrutacyjnym.
          </DialogDescription>
        </DialogHeader>

        <DialogBody>
          <div className="space-y-3">
            <FormField label="Powód" required>
              <RadioGroup value={reasonId} onValueChange={setReasonId}>
                {filtered.map((r) => (
                  <label
                    key={r.id}
                    className="flex items-center gap-2 text-sm cursor-pointer rounded-v2-s p-1.5 hover:bg-[hsl(var(--accent-soft))]"
                  >
                    <RadioGroupItem value={r.id} />
                    <span>{r.label}</span>
                  </label>
                ))}
              </RadioGroup>
            </FormField>
            <FormField
              label="Notatka (opcjonalnie)"
              description="Np. kontekst decyzji, follow-up."
            >
              <Textarea
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                rows={3}
                placeholder="Kandydat dostał lepszą ofertę finansową gdzie indziej."
              />
            </FormField>

            {emailAvailable && (
              <FormField label="Powiadomienie e-mail do kandydata">
                <label className="flex items-start gap-2 text-sm cursor-pointer rounded-v2-s p-1.5 hover:bg-[hsl(var(--accent-soft))]">
                  <input
                    type="checkbox"
                    className="mt-0.5 h-4 w-4 rounded border-[hsl(var(--border))] text-[hsl(var(--accent))] focus:ring-[hsl(var(--accent))]"
                    checked={sendEmail}
                    onChange={(e) => setSendEmail(e.target.checked)}
                  />
                  <span className="flex items-start gap-1.5">
                    <Mail className="mt-0.5 h-3.5 w-3.5 text-[hsl(var(--muted-foreground))] flex-shrink-0" />
                    <span>
                      Wyślij e-mail z informacją zwrotną do kandydata — za 15
                      minut. Do tego czasu można anulować wysyłkę.
                    </span>
                  </span>
                </label>
              </FormField>
            )}
          </div>
        </DialogBody>

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Anuluj
          </Button>
          <Button
            variant="destructive"
            disabled={!reasonId}
            onClick={handleConfirm}
          >
            Potwierdź
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
