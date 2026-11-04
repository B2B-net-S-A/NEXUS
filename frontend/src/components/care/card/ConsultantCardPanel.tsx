"use client";

import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";

import { ConsultantCard } from "./ConsultantCard";

interface ConsultantCardPanelProps {
  /** `null` = panel zamknięty. */
  contractId: number | null;
  onClose: () => void;
}

/**
 * Panel boczny `/care?contract=<id>` na każdej zakładce: ta sama karta
 * konsultanta co w zakładce „Opieka” kontraktu. Esc i krzyżyk zamykają panel
 * (adres traci `contract`); okna otwierane z karty leżą nad panelem.
 */
export function ConsultantCardPanel({ contractId, onClose }: ConsultantCardPanelProps) {
  return (
    <Sheet open={contractId != null} onOpenChange={(open) => (open ? undefined : onClose())}>
      <SheetContent
        side="right"
        size="lg"
        className="overflow-hidden"
        data-testid="care-consultant-card-panel"
        aria-describedby={undefined}
      >
        <SheetTitle className="sr-only">Karta konsultanta</SheetTitle>
        <SheetDescription className="sr-only">
          Zdrowie relacji, najbliższy krok, wiedza o projekcie, sprawy i historia konsultanta.
        </SheetDescription>
        <div className="relative min-h-0 flex-1 overflow-y-auto px-4 pb-6 pt-4 sm:px-5">
          {contractId != null ? <ConsultantCard key={contractId} contractId={contractId} layout="panel" /> : null}
        </div>
      </SheetContent>
    </Sheet>
  );
}
