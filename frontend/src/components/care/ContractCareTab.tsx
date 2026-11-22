"use client";

import { useState } from "react";

import { apiErrorMessage } from "@/lib/api-error";
import { useConsultantCard, useContractCare, type TechCard } from "@/lib/api/care";

import { ConsultantCard, type CareStreamActions } from "./card/ConsultantCard";
import { CareStream } from "./stream/CareStream";
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
 * Edycja starej karty technologicznej ze strumienia rozmów (przycisk „Karta
 * technologiczna” zniknął 22.10.2026 — nowy stan u klienta zapisuje okno
 * „Rozmowa”). Karty czyta ten sam odczyt co strumień (`useContractCare`).
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
 * Zakładka „Opieka i rozmowy” kontraktu (wariant A, 20.11.2026): cienki
 * wiersz z opiekunem i rytmem, po lewej jeden strumień rozmów, notatek
 * i opinii klienta z polem zapisu, po prawej następny krok, plan kontaktów,
 * zadowolenie i opinie, sprawy i to, co wiemy o projekcie (karta konsultanta
 * w układzie `page`; panel `/care` ma układ `panel` bez zmian). Bez modułu
 * opieki zostają same notatki kontraktu.
 */
export function ContractCareTab({
  contractId,
  careOpen = true,
  canAddNote = false,
  canReadFeedback = false,
  autoStartTalk = false,
  onAutoStartTalkDone,
}: {
  contractId: number;
  /** Moduł opieki „Ludzi w NEXUSIE” włączony dla czytającego (bez niego same notatki). */
  careOpen?: boolean;
  /** Notatka przy kontrakcie — edycja kontraktów (`POST /api/contracts/{id}/notes`). */
  canAddNote?: boolean;
  /** Opinie klienta (krąg D11). */
  canReadFeedback?: boolean;
  /** Otwórz od razu okno zapisu rozmowy (pas „Co się dzieje” strony kontraktu). */
  autoStartTalk?: boolean;
  onAutoStartTalkDone?: () => void;
}) {
  const card = useConsultantCard(contractId, careOpen);
  const [editTarget, setEditTarget] = useState<{ id: number | null; on: string } | null>(null);
  const canEdit = careOpen && (card.data?.can_edit ?? false);

  const stream = (actions: CareStreamActions | null) => (
    <CareStream
      contractId={contractId}
      careOpen={careOpen}
      care={actions}
      canAddNote={canAddNote}
      canReadFeedback={careOpen && canReadFeedback}
      onEditTechCard={canEdit ? (target) => setEditTarget(target) : undefined}
    />
  );

  if (!careOpen) return stream(null);
  return (
    <>
      <ConsultantCard
        contractId={contractId}
        layout="page"
        stream={stream}
        autoStartTalk={autoStartTalk}
        onAutoStartTalkDone={onAutoStartTalkDone}
      />
      {editTarget && card.data ? (
        <TechCardEditor
          contractId={contractId}
          clientId={card.data.client_id}
          target={editTarget}
          onClose={() => setEditTarget(null)}
        />
      ) : null}
    </>
  );
}
