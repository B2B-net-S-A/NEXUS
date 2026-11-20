"use client";
// „Anuluj szkic” z pozycji „Klient zamówił okres po zakończeniu” w pasie
// „Co się dzieje” (decyzja Artura 19.11.2026). Istniejąca ścieżka zapisu:
// PATCH zamówienia ze statusem „Anulowane”. Szkic zostaje w historii zamówień
// razem z plikiem, a znika z konfliktu, bo anulowane zamówienie nic nie wymaga.
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { useToast } from "@/components/Toast";
import { api } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";

export interface CancelOrderDraftButtonProps {
  contractId: number;
  clientId: number;
  orderId: number;
  orderNumber: string | null;
}

export function CancelOrderDraftButton({
  contractId,
  clientId,
  orderId,
  orderNumber,
}: CancelOrderDraftButtonProps) {
  const queryClient = useQueryClient();
  const { showError, showSuccess } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const cancel = useMutation({
    mutationFn: () => api.patch(`/api/clients/${clientId}/orders/${orderId}`, { status: "cancelled" }),
    onSuccess: async () => {
      showSuccess("Szkic zamówienia anulowany.");
      await queryClient.invalidateQueries({ queryKey: ["contract", contractId] });
      void queryClient.invalidateQueries({ queryKey: ["contracts-v2"] });
      void queryClient.invalidateQueries({ queryKey: ["contracts-quick-counts"] });
    },
    onError: (error: unknown) =>
      showError(apiErrorMessage(error, "Nie udało się anulować szkicu zamówienia.")),
  });

  const handleClick = async () => {
    const ok = await askConfirm({
      title: "Anulować szkic zamówienia?",
      description: `${orderNumber ? `Szkic ${orderNumber}` : "Szkic"} zostanie w historii zamówień jako „Anulowane”, razem z plikiem. Zakończenie współpracy się nie zmienia.`,
      confirmLabel: "Anuluj szkic",
      cancelLabel: "Zostaw",
      variant: "destructive",
    });
    if (ok) cancel.mutate();
  };

  return (
    <>
      <Button size="sm" variant="quiet" onClick={handleClick} loading={cancel.isPending}>
        Anuluj szkic
      </Button>
      {confirmDialog}
    </>
  );
}
