"use client";

import { useToast } from "@/components/Toast";
import type { ConfirmRequest } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import { useCancelBonus, type BonusRow } from "@/lib/api/hr-payroll";
import { formatMoney } from "@/lib/money";

/** „Anuluj” przy premii: potwierdzenie i komunikaty wspólne dla ekranu miesiąca i kartoteki. */
export function useCancelBonusRow(askConfirm: (request: ConfirmRequest) => Promise<boolean>) {
  const cancel = useCancelBonus();
  const { showToast } = useToast();

  return async (row: BonusRow) => {
    const proposal = row.status === "proposed";
    const ok = await askConfirm({
      title: proposal ? "Odrzucić propozycję premii?" : "Anulować premię?",
      description: `${row.recipient_name ?? "Osoba"} · ${formatMoney(row.amount, row.currency)}. ${
        proposal
          ? row.source === "manual"
            ? "Propozycja zniknie z decyzji Rozliczeń."
            : "Automat nie zaproponuje jej ponownie."
          : "Osoba dostanie powiadomienie o anulowaniu (bez kwoty)."
      }`,
      confirmLabel: proposal ? "Odrzuć" : "Anuluj premię",
      cancelLabel: "Zostaw",
      variant: "destructive",
    });
    if (!ok) return;
    cancel.mutate(
      { id: row.id },
      {
        onSuccess: () => showToast(proposal ? "Propozycja odrzucona" : "Premia anulowana", "success"),
        onError: (err) => showToast(apiErrorMessage(err, "Nie udało się anulować."), "error"),
      },
    );
  };
}
