"use client";

/**
 * Wypełnienie formularza CV klienta (albo tabeli punktowej) modelem — jedno
 * dla karty w sekcji CV i przycisku w ramce „Następny etap” (26.11.2026).
 *
 * Ramka wołała tylko „otwórz okno”, a okno rysuje się dopiero przy
 * wypełnionym formularzu, więc „Wypełnij formularz / tabelę” nic nie robiły
 * (zgłoszenie DL z 26.11.2026). Teraz oba miejsca wołają to samo wypełnienie;
 * klucz mutacji jest wspólny, więc karta i ramka widzą ten sam stan „w toku”.
 */

import { useIsMutating, useMutation, useQueryClient, type QueryClient } from "@tanstack/react-query";

import { useToast } from "@/components/Toast";
import { apiErrorMessage } from "@/lib/api-error";
import { clientFormKey, fillClientForm, type ClientFormView } from "@/lib/api/clientForms";
import type { ClientFormKind } from "@/lib/api/jobFiles";

export const clientFormFillKey = (stageId: number, kind: ClientFormKind) =>
  ["client-form-fill", stageId, kind] as const;

/** Nowy stan formularza do pamięci; tablica i lista wymagań liczą braki z serwera. */
export function storeClientFormView(
  queryClient: QueryClient,
  stageId: number,
  kind: ClientFormKind,
  view: ClientFormView,
): void {
  queryClient.setQueryData(clientFormKey(stageId, kind), view);
  void queryClient.invalidateQueries({ queryKey: ["move-requirements"] });
  void queryClient.invalidateQueries({ queryKey: ["kanban"] });
}

export interface ClientFormFill {
  /** Wynik wypełnienia albo `null` po błędzie (komunikat już pokazany). */
  fill: () => Promise<ClientFormView | null>;
  filling: boolean;
}

export function useClientFormFill(stageId: number, kind: ClientFormKind = "form"): ClientFormFill {
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  const score = kind === "score";
  const mutationKey = clientFormFillKey(stageId, kind);
  const mutation = useMutation({
    mutationKey,
    mutationFn: () => fillClientForm(stageId, kind),
    onSuccess: (view) => {
      storeClientFormView(queryClient, stageId, kind, view);
      if (view.message) showError(view.message);
      else
        showSuccess(
          view.missing.length
            ? `${score ? "Tabela wypełniona" : "Formularz wypełniony"} — ${view.missing.length} do uzupełnienia.`
            : score
              ? "Tabela wypełniona."
              : "Formularz wypełniony.",
        );
    },
    onError: (error) => {
      showError(
        apiErrorMessage(error, score ? "Nie udało się wypełnić tabeli." : "Nie udało się wypełnić formularza."),
      );
    },
  });
  const filling = useIsMutating({ mutationKey }) > 0;
  return {
    fill: () => mutation.mutateAsync().catch(() => null),
    filling,
  };
}
