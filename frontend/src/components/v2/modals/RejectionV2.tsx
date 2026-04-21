"use client";

import * as React from "react";
import { useState } from "react";
import { AlertTriangle } from "lucide-react";
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

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  terminalType: "rejected" | "withdrawn";
  reasons: RejectionReason[];
  onConfirm: (reasonId: string, notes: string) => void;
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
  onConfirm,
}: Props) {
  const [reasonId, setReasonId] = useState("");
  const [notes, setNotes] = useState("");

  const filtered = reasons.filter((r) => r.applies_to.includes(terminalType));

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
          </div>
        </DialogBody>

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Anuluj
          </Button>
          <Button
            variant="destructive"
            disabled={!reasonId}
            onClick={() => onConfirm(reasonId, notes)}
          >
            Potwierdź
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
