"use client";

import { AppModal } from "@/components/ds/AppModal";
import { Button } from "@/components/ui/button";
import type { CareBoardCard } from "@/lib/api/care-board";

import { careTileTitle } from "./work-board-model";

export type DecisionOutcome = "done" | "dismissed";

/**
 * „Zrobione” karty „Decyzja” (K3): przekazana albo „nie dotyczy”. Zamyka wpis
 * „Do przepięcia” (`done` / `dismissed`) i karta znika z tablicy.
 */
export function DecisionDoneDialog({
  card,
  pending,
  error,
  onCancel,
  onPick,
}: {
  card: CareBoardCard;
  pending: boolean;
  error: string | null;
  onCancel: () => void;
  onPick: (outcome: DecisionOutcome) => void;
}) {
  return (
    <AppModal
      open
      onOpenChange={(open) => (open ? null : onCancel())}
      title="Jak zamknąć decyzję?"
      description={`${careTileTitle(card)} — wpis „Do przepięcia” zostanie zamknięty i zniknie z tablicy.`}
      size="sm"
      footer={
        <Button variant="ghost" onClick={onCancel}>
          Anuluj
        </Button>
      }
    >
      <div className="grid gap-2 sm:grid-cols-2">
        <Button variant="outline" className="h-auto flex-col items-start py-2.5" disabled={pending} onClick={() => onPick("done")}>
          <span className="font-medium">Przekazana</span>
          <span className="text-xs font-normal text-muted-foreground">front office przejął temat</span>
        </Button>
        <Button
          variant="outline"
          className="h-auto flex-col items-start py-2.5"
          disabled={pending}
          onClick={() => onPick("dismissed")}
        >
          <span className="font-medium">Nie dotyczy</span>
          <span className="text-xs font-normal text-muted-foreground">przepięcie nie jest potrzebne</span>
        </Button>
      </div>
      {error ? (
        <p role="alert" className="mt-3 text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </AppModal>
  );
}
