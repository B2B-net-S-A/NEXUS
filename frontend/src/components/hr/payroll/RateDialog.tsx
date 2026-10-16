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
import { useSetRate, type Currency } from "@/lib/api/hr-payroll";

import { CURRENCIES, parseAmount, warsawMonth } from "./payroll-format";

interface RateDialogProps {
  userId: number;
  name: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  defaultCurrency?: Currency;
}

/**
 * Płace: „Nowa stawka od…” — zawsze od 1. dnia miesiąca. Poprzednia stawka
 * kończy się dzień wcześniej; zamknięty miesiąc płac odpowiada 409.
 */
export function RateDialog({ userId, name, open, onOpenChange, defaultCurrency }: RateDialogProps) {
  const { showToast } = useToast();
  const save = useSetRate(userId);
  const [rate, setRate] = useState("");
  const [currency, setCurrency] = useState<Currency>(defaultCurrency ?? "PLN");
  const [month, setMonth] = useState(warsawMonth());
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);

  const submit = () => {
    setError(null);
    const value = parseAmount(rate);
    if (value == null) {
      setError("Podaj stawkę za godzinę, np. 120 albo 95,50.");
      return;
    }
    if (!/^\d{4}-\d{2}$/.test(month)) {
      setError("Wybierz miesiąc, od którego obowiązuje stawka.");
      return;
    }
    save.mutate(
      {
        hourly_rate: value,
        currency,
        effective_from: `${month}-01`,
        reason: reason.trim() || null,
      },
      {
        onSuccess: () => {
          showToast("Stawka zapisana", "success");
          onOpenChange(false);
        },
        onError: (err) => setError(apiErrorMessage(err, "Nie udało się zapisać stawki.")),
      },
    );
  };

  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      title={`Nowa stawka · ${name}`}
      description="Stawka obowiązuje od 1. dnia wybranego miesiąca. Wstecz najwyżej 12 miesięcy."
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Anuluj
          </Button>
          <Button onClick={submit} disabled={save.isPending}>
            {save.isPending ? "Zapisywanie…" : "Zapisz stawkę"}
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-3">
        <FormField label="Stawka za godzinę" htmlFor="rate-value">
          <Input
            id="rate-value"
            inputMode="decimal"
            value={rate}
            onChange={(event) => setRate(event.target.value)}
          />
        </FormField>
        <FormField label="Waluta" htmlFor="rate-currency">
          <Select value={currency} onValueChange={(value) => setCurrency(value as Currency)}>
            <SelectTrigger id="rate-currency">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {CURRENCIES.map((code) => (
                <SelectItem key={code} value={code}>
                  {code}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
        <FormField label="Od miesiąca" htmlFor="rate-month">
          <Input
            id="rate-month"
            type="month"
            value={month}
            onChange={(event) => setMonth(event.target.value)}
          />
        </FormField>
        <FormField label="Powód zmiany" htmlFor="rate-reason" className="sm:col-span-3">
          <Input
            id="rate-reason"
            value={reason}
            maxLength={500}
            onChange={(event) => setReason(event.target.value)}
          />
        </FormField>
      </div>
      {error ? (
        <p role="alert" className="mt-4 text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </AppModal>
  );
}
