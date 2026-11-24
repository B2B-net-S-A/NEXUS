"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Undo2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useToast } from "@/components/Toast";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { usePipelineMoveCore } from "@/hooks/usePipelineMoveCore";
import { invalidateReviewBatch, type ReviewBatchOpenScreening } from "@/lib/api/reviewBatch";
import { pluralPl } from "@/lib/plural-pl";

/**
 * „Oddaj do Nowych” w zakładce „Do domknięcia” (makieta 24.11.2026, prośba
 * rekrutera): screening bez wyniku wraca do kolumny „Nowi” bez odrzucenia.
 * Karta, która wróciła do „Nowych”, nie jest decyzją (`_decisions`, P6), więc
 * znika z zaległości i nie liczy się do minimum dnia; w historii osoby nie
 * zostaje „Odrzucony”. Ruch idzie przez `usePipelineMoveCore`, jak na Tablicy.
 */
export function ReturnToNewButton({
  jobId,
  jobTitle,
  people,
  label,
  confirm = false,
  tourAnchor,
}: {
  jobId: number;
  jobTitle: string;
  people: ReviewBatchOpenScreening[];
  label: string;
  confirm?: boolean;
  /** Kotwica Nowości i lekcji (`data-tour`). */
  tourAnchor?: string;
}) {
  const move = usePipelineMoveCore({ jobId });
  const queryClient = useQueryClient();
  const { showError, showSuccess } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const [pending, setPending] = useState(false);

  const run = async () => {
    const count = people.length;
    if (
      confirm &&
      !(await askConfirm({
        title: `Oddać ${count} ${pluralPl(count, "osobę", "osoby", "osób")} do „Nowych”?`,
        description: `„${jobTitle}”: karty wracają do kolumny „Nowi” bez odrzucenia. W historii osób nie zostanie „Odrzucony”, a rekrutacja przestanie blokować Twoje wyszukiwanie. Te osoby nie liczą się do dzisiejszego minimum.`,
        confirmLabel: `Oddaj ${count}`,
      }))
    ) {
      return;
    }
    setPending(true);
    let moved = 0;
    for (const person of people) {
      const outcome = await move.send({ candidate_id: person.candidate_id, job_id: jobId, stage: "new" });
      if (outcome.ok) moved += 1;
    }
    setPending(false);
    invalidateReviewBatch(queryClient);
    if (moved === count) {
      showSuccess(`Oddano do „Nowych”: ${moved}. Bez odrzucenia.`);
    } else {
      showError(`Oddano ${moved} z ${count}. Pozostałe zostały w „Do domknięcia”.`);
    }
  };

  return (
    <>
      <Button
        type="button"
        size="sm"
        variant="outline"
        disabled={pending}
        data-tour={tourAnchor}
        onClick={() => void run()}
      >
        <Undo2 className="h-3.5 w-3.5" aria-hidden />
        {pending ? "Oddaję…" : label}
      </Button>
      {confirmDialog}
    </>
  );
}
