"use client";

/**
 * Szuflada edycji jednego bloku Profilu Championa (04.10.2026).
 *
 * „Edytuj” przy bloku Briefu otwiera z prawej ten sam edytor co pełny
 * formularz, ale tylko z sekcjami tego bloku (`CHAMPION_BLOCKS`). Zapis to ten
 * sam `PUT …/champion-profile` — jedzie w nim tylko to, co zmieniono
 * (`lib/champion-save.ts`), serwer scala resztę. Zamknięcie z niezapisanymi
 * zmianami pyta.
 */

import { useState } from "react";

import { ChampionProfileEditor } from "@/components/ChampionProfileEditor";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { RecruitmentSheet } from "@/components/v2/recruitment/slideovers/RecruitmentSheet";
import { CHAMPION_BLOCKS, type ChampionBlock } from "@/lib/champion-blocks";

export interface ChampionEditDrawerProps {
  jobId: number;
  clientId: number | null;
  block: ChampionBlock | null;
  canEdit: boolean;
  onClose: () => void;
}

export function ChampionEditDrawer({
  jobId,
  clientId,
  block,
  canEdit,
  onClose,
}: ChampionEditDrawerProps) {
  const [dirty, setDirty] = useState(false);
  const { askConfirm, confirmDialog } = useConfirmV2();

  const close = () => {
    setDirty(false);
    onClose();
  };
  const requestClose = async () => {
    if (dirty) {
      const ok = await askConfirm({
        title: "Zamknąć bez zapisu?",
        description: "Zmiany w tym bloku nie zostały zapisane i przepadną.",
        confirmLabel: "Zamknij bez zapisu",
        cancelLabel: "Wróć do edycji",
        variant: "destructive",
      });
      if (!ok) return;
    }
    close();
  };

  if (!block) return confirmDialog;
  const meta = CHAMPION_BLOCKS[block];

  return (
    <>
      <ChampionProfileEditor
        key={block}
        jobId={jobId}
        clientId={clientId}
        canEdit={canEdit}
        layout="drawer"
        onlySections={meta.sections}
        onDirtyChange={setDirty}
        onSaved={close}
        onCancel={close}
        renderDrawer={({ body, footer }) => (
          <RecruitmentSheet
            open
            onOpenChange={(next) => {
              if (!next) void requestClose();
            }}
            title={`Edycja: ${meta.title}`}
            description="Zapis zmienia tylko ten blok. Cały profil: menu ⋯ → „Edytuj cały Profil Championa”."
            footer={footer}
            data-testid="champion-edit-drawer"
          >
            {body}
          </RecruitmentSheet>
        )}
      />
      {confirmDialog}
    </>
  );
}
