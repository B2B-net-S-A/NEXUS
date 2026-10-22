"use client";

import { AppModal } from "@/components/ds/AppModal";
import { Button } from "@/components/ui/button";

import { FrontOfficeSection } from "../week/FrontOfficeSection";

interface FrontOfficeDialogProps {
  contractId: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * „Przekaż do front office” z tablicy „Do zrobienia” (karta „Decyzja”) —
 * ta sama sekcja co w karcie konsultanta: pasujące rekrutacje z silnika
 * „Pasuje też do” i przekazanie ze śladem i powiadomieniem.
 */
export function FrontOfficeDialog({ contractId, open, onOpenChange }: FrontOfficeDialogProps) {
  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      title="Przekaż do front office"
      description="Przekazanie jest możliwe, gdy konsultant kończy projekt w ciągu 60 dni albo chce zmiany projektu."
      size="lg"
      footer={
        <Button variant="ghost" onClick={() => onOpenChange(false)}>
          Zamknij
        </Button>
      }
    >
      <FrontOfficeSection contractId={contractId} />
    </AppModal>
  );
}
