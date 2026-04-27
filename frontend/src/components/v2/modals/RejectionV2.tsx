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

/** Lustro POST_ACCEPT_STAGES z `app/services/candidate_risk.py`. */
const POST_ACCEPT_STAGES = new Set<string>([
  "acceptance",
  "negotiation",
  "onboarding",
]);

export type CandidateOfferResponse = "pending" | "accepted" | "declined";

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
  // Phase 17 (migracja 0068): konkretny stage z którego kandydat wychodzi.
  // Gdy ∈ {acceptance, negotiation, onboarding} ORAZ terminalType='withdrawn',
  // pokazujemy radio `candidate_offer_response` żeby odróżnić post-accept
  // dropout od zwykłego wycofania.
  previousStage?: string | null;
  onConfirm: (
    reasonId: string,
    notes: string,
    sendRejectionEmail: boolean | null,
    candidateOfferResponse?: CandidateOfferResponse | null
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
  previousStage = null,
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

  // Phase 17 — show offer response radio only for withdrawn FROM post-accept.
  const offerResponseRequired =
    terminalType === "withdrawn" &&
    !!previousStage &&
    POST_ACCEPT_STAGES.has(previousStage);
  const [offerResponse, setOfferResponse] =
    useState<CandidateOfferResponse | "">("");

  // Reset defaults when modal re-opens (e.g. user bails, opens again).
  useEffect(() => {
    if (open) {
      setReasonId("");
      setNotes("");
      setSendEmail(emailAvailable);
      setOfferResponse("");
    }
  }, [open, emailAvailable]);

  const filtered = reasons.filter((r) => r.applies_to.includes(terminalType));

  const handleConfirm = () => {
    // Pass explicit boolean only when the checkbox is user-controlled; else
    // defer to backend auto-decision with `null`.
    const emailFlag: boolean | null = emailAvailable ? sendEmail : null;
    const offerResponseValue: CandidateOfferResponse | null =
      offerResponseRequired && offerResponse ? offerResponse : null;
    onConfirm(reasonId, notes, emailFlag, offerResponseValue);
  };

  const submitDisabled =
    !reasonId || (offerResponseRequired && !offerResponse);

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
            {offerResponseRequired && (
              <FormField
                label="Reakcja kandydata na ofertę"
                description="Pomaga w analizie ryzyka — wycofanie po akceptacji to mocny sygnał."
                required
              >
                <RadioGroup
                  value={offerResponse}
                  onValueChange={(v) =>
                    setOfferResponse(v as CandidateOfferResponse)
                  }
                >
                  {(
                    [
                      { v: "declined", label: "Wycofał się PO akceptacji oferty" },
                      { v: "accepted", label: "Zaakceptował, potem się wycofał z innego powodu" },
                      { v: "pending", label: "Jeszcze nie odpowiedział na ofertę" },
                    ] as const
                  ).map(({ v, label }) => (
                    <label
                      key={v}
                      className="flex items-center gap-2 text-sm cursor-pointer rounded-v2-s p-1.5 hover:bg-[hsl(var(--accent-soft))]"
                    >
                      <RadioGroupItem value={v} />
                      <span>{label}</span>
                    </label>
                  ))}
                </RadioGroup>
              </FormField>
            )}
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
            disabled={submitDisabled}
            onClick={handleConfirm}
          >
            Potwierdź
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
