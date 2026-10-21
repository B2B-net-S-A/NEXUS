"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import { useConsultantCard, useContractCare, type TimelineEvent } from "@/lib/api/care";

import { ConsultantCard } from "./card/ConsultantCard";
import { TechCardDialog } from "./TechCardDialog";

/**
 * Edycja starej karty technologicznej z „Historii” (przycisk „Karta
 * technologiczna” zniknął 22.10.2026 — nowy stan u klienta zapisuje okno
 * „Rozmowa”). Karty czyta zakładka kontraktu dopiero po „Edytuj”.
 */
function TechCardEditor({
  contractId,
  clientId,
  on,
  onClose,
}: {
  contractId: number;
  clientId: number;
  on: string;
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
  const card = care.data?.tech_cards.find((item) => item.interview_on === on) ?? null;
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
  const [editOn, setEditOn] = useState<string | null>(null);
  const canEdit = card.data?.can_edit ?? false;

  const historyAction = (event: TimelineEvent) =>
    canEdit && event.kind === "tech_card" ? (
      <Button size="sm" variant="ghost" className="h-7 px-2 text-xs" onClick={() => setEditOn(event.on)}>
        Edytuj
      </Button>
    ) : null;

  return (
    <div className="space-y-3 rounded-lg border border-border bg-card p-4">
      <ConsultantCard contractId={contractId} layout="page" historyAction={historyAction} />
      {editOn && card.data ? (
        <TechCardEditor
          contractId={contractId}
          clientId={card.data.client_id}
          on={editOn}
          onClose={() => setEditOn(null)}
        />
      ) : null}
    </div>
  );
}
