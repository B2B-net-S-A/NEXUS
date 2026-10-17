"use client";

import { useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { apiErrorMessage } from "@/lib/api-error";
import { useReopenMonth } from "@/lib/api/hr-payroll";

interface ReopenMonthDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  year: number;
  month: number;
  label: string;
}

/** „Otwórz ponownie” zamknięty miesiąc płac — z powodem do śladu zmian. */
export function ReopenMonthDialog({
  open,
  onOpenChange,
  year,
  month,
  label,
}: ReopenMonthDialogProps) {
  const { showToast } = useToast();
  const reopen = useReopenMonth(year, month);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const submit = () => {
    setError(null);
    if (reason.trim().length < 3) {
      setError("Podaj powód ponownego otwarcia.");
      return;
    }
    reopen.mutate(reason.trim(), {
      onSuccess: () => {
        showToast("Miesiąc otwarty ponownie", "success");
        onOpenChange(false);
      },
      onError: (err) => setError(apiErrorMessage(err, "Nie udało się otworzyć miesiąca.")),
    });
  };
  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      title={`Otworzyć ponownie ${label}?`}
      description="Zamrożone kwoty znikną, raport znów policzy się z danych, a timesheety tego miesiąca zostaną odblokowane. Powód trafi do śladu zmian."
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Anuluj
          </Button>
          <Button variant="destructive" onClick={submit} disabled={reopen.isPending}>
            {reopen.isPending ? "Otwieranie…" : "Otwórz ponownie"}
          </Button>
        </>
      }
    >
      <FormField label="Powód" htmlFor="payroll-reopen-reason">
        <Input
          id="payroll-reopen-reason"
          value={reason}
          maxLength={1000}
          onChange={(event) => setReason(event.target.value)}
        />
      </FormField>
      {error ? (
        <p role="alert" className="mt-3 text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </AppModal>
  );
}
