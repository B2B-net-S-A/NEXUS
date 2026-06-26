"use client";

import * as React from "react";
import { useState } from "react";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import type { RateUnit } from "@/lib/api";

interface Props {
  open: boolean;
  // false (X / Escape / overlay) = anuluj ruch — karta zostaje w kolumnie źródłowej.
  onOpenChange: (open: boolean) => void;
  candidateName: string;
  // Przesuń + zapisz stawkę do klienta.
  onConfirm: (payload: { rate: number; unit: RateUnit; currency: string }) => void;
  // Przesuń bez stawki — stawkę można uzupełnić później z profilu kandydata.
  onSkip: () => void;
}

const UNIT_LABELS: Record<RateUnit, string> = {
  hourly: "PLN / godzinę",
  daily: "PLN / dzień",
  monthly: "PLN / miesiąc",
};

/**
 * Pyta o „Stawkę do klienta" (sell rate) przy ruchu kandydata na etap
 * „CV Wysłane". Bliźniaczy do {@link VerifiedRateModal} (stawka kandydata przy
 * „Zweryfikowany"), ale bez bramki budżetowej — to cena dla klienta, nie
 * oczekiwania kandydata. Domyślna jednostka `monthly` (spójna z budżetem
 * oferty i endpointem `/client-rate`).
 */
export function ClientRateModal({
  open,
  onOpenChange,
  candidateName,
  onConfirm,
  onSkip,
}: Props) {
  const [rate, setRate] = useState<string>("");
  const [unit, setUnit] = useState<RateUnit>("monthly");
  const currency = "PLN";

  const numericRate = Number.parseFloat(rate.replace(",", "."));
  const isValid = Number.isFinite(numericRate) && numericRate > 0;

  const reset = () => {
    setRate("");
    setUnit("monthly");
  };

  const handleConfirm = () => {
    if (!isValid) return;
    onConfirm({ rate: numericRate, unit, currency });
    reset();
  };

  const handleSkip = () => {
    onSkip();
    reset();
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Przesuń na „CV Wysłane"</DialogTitle>
          <DialogDescription>
            Podaj stawkę do klienta dla kandydata{" "}
            <span className="font-semibold">{candidateName}</span> — cena, za jaką
            proponujesz go klientowi na tej rekrutacji.
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-4">
          <FormField label="Stawka do klienta">
            <input
              type="number"
              inputMode="decimal"
              step="0.01"
              min="0"
              value={rate}
              onChange={(e) => setRate(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && isValid) handleConfirm();
              }}
              placeholder="np. 25000"
              className="w-full h-10 px-3 rounded-md border border-border bg-card focus:outline-none focus:ring-2 focus:ring-primary"
              autoFocus
            />
          </FormField>
          <FormField label="Jednostka">
            <Select value={unit} onValueChange={(v) => setUnit(v as RateUnit)}>
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {(Object.keys(UNIT_LABELS) as RateUnit[]).map((u) => (
                  <SelectItem key={u} value={u}>
                    {UNIT_LABELS[u]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
          <p className="text-xs text-muted-foreground">
            Możesz pominąć i uzupełnić stawkę później z profilu kandydata
            (zakładka „Rekrutacje").
          </p>
        </DialogBody>
        <DialogFooter>
          <Button variant="ghost" onClick={handleSkip}>
            Przesuń bez stawki
          </Button>
          <Button onClick={handleConfirm} disabled={!isValid}>
            Przesuń i zapisz
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
