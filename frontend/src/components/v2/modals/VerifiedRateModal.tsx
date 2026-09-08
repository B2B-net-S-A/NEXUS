"use client";

/**
 * „Przesuń na Zweryfikowany" — modal stawki oczekiwanej z bramką budżetową.
 *
 * Pola i werdykt bramki renderuje wspólny `VerifiedRateFields`, a samą regułę
 * liczy `evaluateRateGate` — ten sam komponent i ta sama funkcja obsługują dok
 * „Weryfikacja" na stanowisku screeningu (krok 05 programu „flow w języku C2",
 * PR 6/7), który pokazuje stawkę inline zamiast w modalu.
 *
 * Zmiana wobec stanu sprzed PR 6/7: porównanie z budżetem idzie po jednostce
 * MIESIĘCZNEJ (godzina × 168, dzień × 21), tak jak liczy je backend
 * (`normalize_rate_to_monthly`). Wcześniej modal porównywał surowe liczby, więc
 * dla stawki godzinowej obiecywał „mieści się w budżecie" także wtedy, gdy
 * serwer zaraz stawiał kartę na „Pending".
 */

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
import { VerifiedRateFields } from "@/components/v2/screening/VerifiedRateFields";
import { evaluateRateGate } from "@/lib/verified-rate-gate";
import type { RateUnit } from "@/lib/api";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  candidateName: string;
  jobBudgetMax: number | null;
  onConfirm: (payload: {
    rate: number;
    unit: RateUnit;
    currency: string;
  }) => void;
}

export function VerifiedRateModal({
  open,
  onOpenChange,
  candidateName,
  jobBudgetMax,
  onConfirm,
}: Props) {
  const [rate, setRate] = useState<string>("");
  const [unit, setUnit] = useState<RateUnit>("hourly");
  const currency = "PLN";

  const gate = evaluateRateGate({ rawRate: rate, unit, currency, jobBudgetMax });

  const handleSubmit = () => {
    if (!gate.isValid) return;
    onConfirm({ rate: gate.numericRate, unit, currency });
    setRate("");
    setUnit("hourly");
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Przesuń na „Zweryfikowany”</DialogTitle>
          <DialogDescription>
            Podaj stawkę kandydata{" "}
            <span className="font-semibold">{candidateName}</span>.
            {jobBudgetMax !== null && (
              <>
                {" "}
                Budżet rekrutacji:{" "}
                <strong>{jobBudgetMax.toLocaleString("pl-PL")} PLN/mc</strong>.
              </>
            )}
          </DialogDescription>
        </DialogHeader>
        <DialogBody>
          <VerifiedRateFields
            rate={rate}
            onRateChange={setRate}
            unit={unit}
            onUnitChange={setUnit}
            gate={gate}
            autoFocus
            onSubmit={handleSubmit}
            idPrefix="verified-rate-modal"
          />
        </DialogBody>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Anuluj
          </Button>
          <Button onClick={handleSubmit} disabled={!gate.isValid}>
            {gate.verdict === "needs_approval" && gate.isValid
              ? "Wyślij do akceptacji"
              : "Przesuń"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
