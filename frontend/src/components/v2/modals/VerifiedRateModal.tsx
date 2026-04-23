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
  onOpenChange: (open: boolean) => void;
  candidateName: string;
  jobBudgetMax: number | null;
  onConfirm: (payload: {
    rate: number;
    unit: RateUnit;
    currency: string;
  }) => void;
}

const UNIT_LABELS: Record<RateUnit, string> = {
  hourly: "PLN / h",
  daily: "PLN / dzień",
  monthly: "PLN / miesiąc",
};

export function VerifiedRateModal({
  open,
  onOpenChange,
  candidateName,
  jobBudgetMax,
  onConfirm,
}: Props) {
  const [rate, setRate] = useState<string>("");
  const [unit, setUnit] = useState<RateUnit>("monthly");
  const [currency] = useState<string>("PLN");

  const numericRate = Number.parseFloat(rate.replace(",", "."));
  const isAboveBudget =
    Number.isFinite(numericRate) &&
    jobBudgetMax !== null &&
    numericRate > jobBudgetMax;
  const isValid = Number.isFinite(numericRate) && numericRate > 0;

  const handleSubmit = () => {
    if (!isValid) return;
    onConfirm({ rate: numericRate, unit, currency });
    setRate("");
    setUnit("monthly");
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Przesuń na "Zweryfikowany"</DialogTitle>
          <DialogDescription>
            Podaj stawkę kandydata{" "}
            <span className="font-semibold">{candidateName}</span>.
            {jobBudgetMax !== null && (
              <>
                {" "}
                Budżet projektu: <strong>{jobBudgetMax.toLocaleString("pl-PL")} PLN</strong>.
              </>
            )}
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-4">
          <FormField label="Stawka">
            <input
              type="number"
              inputMode="decimal"
              step="0.01"
              min="0"
              value={rate}
              onChange={(e) => setRate(e.target.value)}
              placeholder="np. 18000"
              className="w-full h-10 px-3 rounded-v2-s border border-[hsl(var(--border-subtle))] bg-[hsl(var(--bg-surface))] focus:outline-none focus:ring-2 focus:ring-[hsl(var(--accent))]"
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
          {isAboveBudget && (
            <div className="rounded-v2-s p-3 bg-amber-50 border border-amber-200 text-amber-900 text-xs">
              Stawka <strong>{numericRate.toLocaleString("pl-PL")} {currency}</strong> przekracza
              budżet projektu (<strong>{jobBudgetMax!.toLocaleString("pl-PL")} {currency}</strong>).
              Kandydat trafi w stan <strong>"Pending verification"</strong> — delivery lead
              dostanie powiadomienie i zaakceptuje lub odrzuci.
            </div>
          )}
        </DialogBody>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Anuluj
          </Button>
          <Button onClick={handleSubmit} disabled={!isValid}>
            {isAboveBudget ? "Wyślij do akceptacji" : "Przesuń"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
