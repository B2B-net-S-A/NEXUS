"use client";

/**
 * „Przesuń na Zweryfikowany" — okno stawki oczekiwanej kandydata.
 *
 * Pola i porównanie z budżetem renderuje wspólny `VerifiedRateFields`, a samą
 * regułę liczy `evaluateRateGate` — ten sam komponent i ta sama funkcja
 * obsługują dok „Weryfikacja" na stanowisku screeningu.
 *
 * Od 17.09.2026 (decyzja właściciela „żadna bramka nie blokuje przepływu"):
 * stawka jest OPCJONALNA („Pomiń stawkę"), okno podpowiada stawkę z profilu
 * kandydata, a „ponad budżet" to ostrzeżenie w oknie i odznaka na karcie —
 * nic nie trafia na „Oczekuje". Budżet jest godzinowy
 * (`effective_budget_hourly`), ten sam co w nagłówku rekrutacji.
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
  /** Budżet PLN/h rekrutacji (`effective_budget_hourly`); `null` = brak. */
  jobBudgetHourly: number | null;
  /** Stawka z profilu kandydata (PLN/h) — podpowiedź w polu. */
  initialRateHourly?: number | string | null;
  onConfirm: (payload: {
    rate: number;
    unit: RateUnit;
    currency: string;
  }) => void;
  /** Przesuń bez stawki — stawka jest opcjonalna od 17.09.2026. */
  onSkip: () => void;
}

function initialRateText(value: number | string | null | undefined): string {
  if (value == null || value === "") return "";
  const numeric = Number(value);
  // Serwer wysyła Decimal jako tekst („120.00") — w polu pokazujemy „120".
  return Number.isFinite(numeric) && numeric > 0 ? String(numeric) : "";
}

export function VerifiedRateModal({
  open,
  onOpenChange,
  candidateName,
  jobBudgetHourly,
  initialRateHourly = null,
  onConfirm,
  onSkip,
}: Props) {
  // Okno jest montowane z `key` karty, więc inicjalizator liczy się per kandydat.
  const [rate, setRate] = useState<string>(() =>
    initialRateText(initialRateHourly),
  );
  const [unit, setUnit] = useState<RateUnit>("hourly");
  const currency = "PLN";

  const gate = evaluateRateGate({
    rawRate: rate,
    unit,
    currency,
    jobBudgetHourly,
  });

  const handleSubmit = () => {
    if (!gate.isValid) return;
    onConfirm({ rate: gate.numericRate, unit, currency });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Przesuń na „Zweryfikowany”</DialogTitle>
          <DialogDescription>
            Stawka kandydata{" "}
            <span className="font-semibold">{candidateName}</span> (opcjonalnie).
            {jobBudgetHourly !== null && (
              <>
                {" "}
                Budżet rekrutacji:{" "}
                <strong>{jobBudgetHourly.toLocaleString("pl-PL")} PLN/h</strong>.
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
          <Button variant="outline" onClick={onSkip}>
            Pomiń stawkę
          </Button>
          <Button onClick={handleSubmit} disabled={!gate.isValid}>
            Przesuń
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
