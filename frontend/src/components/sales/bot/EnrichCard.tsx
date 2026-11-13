"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { apiErrorMessage } from "@/lib/api-error";
import { salesKeys } from "@/lib/api/sales";
import { salesBotKeys, useCompanyEnrich, useStartEnrich } from "@/lib/api/sales-bot";

/** „Uzupełnij dane” w nagłówku karty firmy; z wyłączoną flagą go nie ma. */
export function EnrichButton({ companyId, disabled }: { companyId: number; disabled?: boolean }) {
  const state = useCompanyEnrich(companyId);
  const start = useStartEnrich(companyId);
  const { showError, showSuccess } = useToast();
  if (!state.isSuccess || !state.data.enabled) return null;
  const running = state.data.run?.status === "started";
  return (
    <Button
      size="sm"
      variant="outline"
      data-tour="sales.company.enrich"
      disabled={disabled || running || start.isPending}
      onClick={() =>
        start.mutate(undefined, {
          onSuccess: () => showSuccess("Szukam danych firmy. Puste pola uzupełnią się same za kilka minut."),
          onError: (error) => showError(apiErrorMessage(error, "Nie udało się zlecić uzupełnienia karty.")),
        })
      }
    >
      {running ? "Szukam danych…" : "Uzupełnij dane"}
    </Button>
  );
}

/**
 * Od 13.11.2026 (decyzja Artura) dane trafiają na kartę od razu, bez „Przyjmij”.
 * Karta pokazuje tylko, że trwa szukanie; gdy bieg się skończy, odświeża fakty
 * firmy i historię. Skąd przyszła wartość, widać w historii karty (Aktywności).
 */
export function EnrichCard({ companyId }: { companyId: number }) {
  const state = useCompanyEnrich(companyId);
  const queryClient = useQueryClient();
  const status = state.data?.run?.status;
  const previous = useRef(status);
  useEffect(() => {
    if (previous.current === "started" && status && status !== "started") {
      void queryClient.invalidateQueries({ queryKey: salesKeys.company(companyId), exact: true });
      void queryClient.invalidateQueries({ queryKey: salesBotKeys.history(companyId) });
    }
    previous.current = status;
  }, [status, companyId, queryClient]);

  if (!state.isSuccess || !state.data.enabled || status !== "started") return null;
  return (
    <Card className="p-4 text-sm text-muted-foreground" role="status">
      Szukam danych firmy, zwykle kilka minut. Puste pola uzupełnią się same.
    </Card>
  );
}
