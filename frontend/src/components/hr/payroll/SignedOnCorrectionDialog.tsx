"use client";

// Płace poprawiają dzień podpisu umowy B2B z powodem (decyzja Artura 06.11.2026).
// Dzień decyduje o miesiącu premii 200%; zapisany wynik miesiąca trzeba potem
// przeliczyć („Przelicz wynik”). Ślad: historia umowy (`signed_on_corrected`).

import { useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import { useCorrectSignedOn, type DoubleBonusContract } from "@/lib/api/hr-payroll";
import { formatIsoDatePl, monthYearPl } from "@/lib/date-pl";
import { warsawToday } from "@/lib/warsaw-date";

export function SignedOnCorrectionDialog({
  contract,
  onClose,
}: {
  contract: DoubleBonusContract & { agreement: NonNullable<DoubleBonusContract["agreement"]> };
  onClose: () => void;
}) {
  const { showToast } = useToast();
  const correct = useCorrectSignedOn();
  const [signedOn, setSignedOn] = useState(contract.signed_on);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const today = warsawToday();
  const problem = !signedOn
    ? "Wpisz datę podpisu."
    : signedOn > today
      ? "Data podpisu nie może być z przyszłości."
      : reason.trim().length < 3
        ? "Podaj powód poprawki."
        : null;

  const submit = () => {
    setError(null);
    correct.mutate(
      {
        generatedContractId: contract.agreement.generated_contract_id,
        signedOn,
        reason: reason.trim(),
      },
      {
        onSuccess: (result) => {
          const settle = result.settle_months.length
            ? ` Przelicz wynik: ${result.settle_months.map((key) => monthYearPl(key)).join(", ")}.`
            : "";
          showToast(`Data podpisu poprawiona na ${formatIsoDatePl(result.signed_on)}.${settle}`, "success");
          onClose();
        },
        onError: (err) => setError(apiErrorMessage(err, "Nie udało się poprawić daty podpisu.")),
      },
    );
  };

  return (
    <AppModal
      open
      onOpenChange={(value) => {
        if (!value) onClose();
      }}
      title="Popraw datę podpisu"
      description={`${contract.label} · umowa ${contract.agreement.contract_number ?? ""} · teraz ${formatIsoDatePl(contract.signed_on)}`}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Wróć
          </Button>
          <Button onClick={submit} disabled={!!problem || correct.isPending}>
            {correct.isPending ? "Zapisywanie…" : "Zapisz datę"}
          </Button>
        </>
      }
    >
      <div className="grid gap-4">
        <FormField label="Data podpisu konsultanta" htmlFor="signed-on-correction-date">
          <Input
            id="signed-on-correction-date"
            type="date"
            className="w-44"
            value={signedOn}
            max={today}
            onChange={(event) => setSignedOn(event.target.value)}
          />
        </FormField>
        <FormField label="Powód" htmlFor="signed-on-correction-reason">
          <Textarea
            id="signed-on-correction-reason"
            rows={2}
            maxLength={500}
            placeholder="np. podpis konsultanta w pliku 02.11 07:32"
            value={reason}
            onChange={(event) => setReason(event.target.value)}
          />
        </FormField>
        <p className="text-sm text-muted-foreground">
          Data decyduje o miesiącu premii 200%. Zapisany wynik miesiąca przeliczysz potem przyciskiem
          „Przelicz wynik”.
        </p>
        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : null}
      </div>
    </AppModal>
  );
}
