"use client";

import { useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useHolderEquipment,
  useMoveExternalToUser,
  type EquipmentHolder,
} from "@/lib/api/equipment";

import { HolderPicker } from "./HolderPicker";

interface MoveToAccountDialogProps {
  /** Osoba spoza NEXUSA, której sprzęt przechodzi na konto. */
  person: EquipmentHolder;
  onClose: () => void;
}

function itemsLabel(count: number): string {
  return count === 1 ? "1 rzecz" : `${count} rzeczy`;
}

/**
 * „Przepisz na konto”: nowa osoba dostała sprzęt jako osoba spoza NEXUSA,
 * a teraz ma konto (decyzja Artura 28.10.2026, wariant B). Wydania, otwarte
 * zadania i niepotwierdzone protokoły przechodzą na konto; potwierdzone
 * protokoły zostają z nazwiskiem z chwili wydania.
 */
export function MoveToAccountDialog({ person, onClose }: MoveToAccountDialogProps) {
  const { showToast } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const [account, setAccount] = useState<EquipmentHolder | null>(null);
  const [error, setError] = useState<string | null>(null);
  const equipment = useHolderEquipment("external", person.id);
  const move = useMoveExternalToUser();
  const count = equipment.data?.active.length ?? null;

  const submit = async () => {
    if (!account) return;
    setError(null);
    const ok = await askConfirm({
      title: `Przepisać sprzęt na konto ${account.name}?`,
      description:
        "Niezwrócony sprzęt, otwarte zadania i protokoły czekające na podpis przejdą na konto NEXUSA. " +
        "Potwierdzone protokoły zostają z nazwiskiem z chwili wydania; przepisanie zostaje w dzienniku.",
      confirmLabel: "Przepisz",
    });
    if (!ok) return;
    move.mutate(
      { personId: person.id, userId: account.id },
      {
        onSuccess: (result) => {
          showToast(
            `Przepisano na konto ${result.holder.name}: ${itemsLabel(result.assignments)}`,
            "success",
          );
          onClose();
        },
        onError: (err) => setError(apiErrorMessage(err, "Nie udało się przepisać sprzętu.")),
      },
    );
  };

  return (
    <AppModal
      open
      onOpenChange={(open) => (open ? undefined : onClose())}
      title="Przepisz na konto"
      description={`${person.name} ma już konto w NEXUSIE? Sprzęt wydany jako osobie spoza NEXUSA przejdzie na to konto.`}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Anuluj
          </Button>
          <Button onClick={submit} disabled={!account || move.isPending}>
            Przepisz na konto
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <p className="text-sm text-muted-foreground">
          {count === null
            ? "Sprawdzam, co ma ta osoba…"
            : `Do przepisania: ${itemsLabel(count)} od ${person.name}.`}
        </p>
        <HolderPicker accountsOnly value={account} onChange={setAccount} />
        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : null}
      </div>
      {confirmDialog}
    </AppModal>
  );
}
