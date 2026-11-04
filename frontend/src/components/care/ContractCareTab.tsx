"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import { useConsultantCard, useContractCare, type TechCard, type TimelineEvent } from "@/lib/api/care";

import { ConsultantCard } from "./card/ConsultantCard";
import { TechCardDialog } from "./TechCardDialog";

/** Karta do „Edytuj” z historii: po `tech_card_id` zdarzenia, a bez niego (stara oś) po dacie. */
export function findTechCard<T extends Pick<TechCard, "id" | "interview_on">>(
  cards: readonly T[] | undefined,
  target: { id: number | null; on: string },
): T | null {
  if (!cards) return null;
  if (target.id != null) return cards.find((item) => item.id === target.id) ?? null;
  return cards.find((item) => item.interview_on === target.on) ?? null;
}

/**
 * Edycja starej karty technologicznej z „Historii” (przycisk „Karta
 * technologiczna” zniknął 22.10.2026 — nowy stan u klienta zapisuje okno
 * „Rozmowa”). Karty czyta zakładka kontraktu dopiero po „Edytuj”.
 */
function TechCardEditor({
  contractId,
  clientId,
  target,
  onClose,
}: {
  contractId: number;
  clientId: number;
  target: { id: number | null; on: string };
  onClose: () => void;
}) {
  const care = useContractCare(contractId);
  if (care.isLoading) return null;
  if (care.isError) {
    return (
      <p role="alert" className="text-sm text-destructive">
        {apiErrorMessage(care.error, "Nie udało się wczytać karty technologicznej.")}
      </p>
    );
  }
  const card = findTechCard(care.data?.tech_cards, target);
  if (!card) {
    return <p className="text-sm text-muted-foreground">Tej karty nie da się już edytować.</p>;
  }
  return (
    <TechCardDialog
      contractId={contractId}
      clientId={clientId}
      card={card}
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    />
  );
}

/**
 * Zakładka „Opieka” kontraktu = karta konsultanta na pełną szerokość (ta
 * sama co w panelu `/care?contract=`). Historię opinii klienta (D11)
 * dokłada strona kontraktu pod kartą (`ContractFeedbackHistory`).
 */
export function ContractCareTab({ contractId }: { contractId: number }) {
  const card = useConsultantCard(contractId);
  const [editTarget, setEditTarget] = useState<{ id: number | null; on: string } | null>(null);
  const canEdit = card.data?.can_edit ?? false;

  const historyAction = (event: TimelineEvent) =>
    canEdit && event.kind === "tech_card" ? (
      <Button
        size="sm"
        variant="ghost"
        className="h-7 px-2 text-xs"
        onClick={() => setEditTarget({ id: event.tech_card_id ?? null, on: event.on })}
      >
        Edytuj
      </Button>
    ) : null;

  return (
    <div className="space-y-3 rounded-lg border border-border bg-card p-4">
      <ConsultantCard contractId={contractId} layout="page" historyAction={historyAction} />
      {editTarget && card.data ? (
        <TechCardEditor
          contractId={contractId}
          clientId={card.data.client_id}
          target={editTarget}
          onClose={() => setEditTarget(null)}
        />
      ) : null}
    </div>
  );
}
