"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import {
  addMoreFromNexus,
  invalidateNewColumnTempo,
  newColumnTargetHint,
  type NewColumnTempoState,
} from "@/lib/api/reviewBatch";
import { pluralPl } from "@/lib/plural-pl";

/**
 * Plakietka „cel N” i „Dodaj 10 kolejnych” przy kolumnie „Nowi” (decyzja Artura
 * z 08.11.2026). Tablica rysuje ją tylko przy `NEW_COLUMN_TEMPO_TARGET_ENABLED`.
 * Zasady: docs/claude/rekrutacja-tablica/cel-kart-wg-tempa-i-miejsce-dla-swiezych.md.
 */
export function NewColumnTempo({
  jobId,
  readOnly,
  tempo,
}: {
  jobId: number;
  readOnly: boolean;
  tempo: Extract<NewColumnTempoState, { enabled: true }>;
}) {
  const queryClient = useQueryClient();
  const { showError, showSuccess } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const [busy, setBusy] = useState(false);
  const moreCards = tempo.more_cards;

  async function addMore() {
    const confirmed = await askConfirm({
      title: `Dodać ${moreCards} kolejnych osób od systemu?`,
      description: `Cel tej kolumny to ${tempo.target}. System dobierze osoby z puli także ponad ten cel.`,
      confirmLabel: `Dodaj ${moreCards}`,
    });
    if (!confirmed) return;
    setBusy(true);
    try {
      const added = await addMoreFromNexus(jobId);
      invalidateNewColumnTempo(queryClient, jobId);
      if (added > 0) {
        showSuccess(`Dodano ${added} ${pluralPl(added, "osobę", "osoby", "osób")} do „Nowych”.`);
      } else {
        showSuccess("W puli nie ma już kolejnych osób dla tej rekrutacji.");
      }
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się dobrać kolejnych osób."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex w-full flex-wrap items-center justify-between gap-1">
      <span title={newColumnTargetHint(tempo)} data-testid="new-column-target">
        <Badge size="sm" variant="outline" className="tabular-nums">
          cel {tempo.target}
        </Badge>
      </span>
      {tempo.can_add_more && !readOnly && (
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="h-6 shrink-0 px-1.5 text-[10px]"
          disabled={busy}
          onClick={() => void addMore()}
          data-testid="new-column-add-more"
        >
          Dodaj {moreCards} kolejnych
        </Button>
      )}
      {confirmDialog}
    </div>
  );
}
