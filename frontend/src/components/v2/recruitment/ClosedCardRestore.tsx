"use client";

/**
 * Zamknięta karta jednej osoby w jednej rekrutacji: powód z serwera
 * i „Przywróć” ruchem karty (`usePipelineMoveCore`) — dla ekranów, które
 * przypisują jedną osobę („Przypisz do rekrutacji”). Ten sam wygląd i ten sam
 * ruch co w oknie „Dodaj do rekrutacji”.
 *
 * Osobny komponent, bo hak ruchu wymaga dostawcy toastów: ekran montuje go
 * dopiero wtedy, gdy serwer odpowie zamkniętą kartą.
 */

import { useEffect, useRef, useState } from "react";

import { usePipelineMoveCore } from "@/hooks/usePipelineMoveCore";
import {
  AddToRecruitmentOutcome,
  restoreMovePayload,
  type ClosedRow,
} from "./AddToRecruitmentDialog";

const NONE: ReadonlySet<number> = new Set();

interface ClosedCardRestoreProps {
  job: { id: number; title: string };
  row: ClosedRow;
  onRestored: () => void;
  /** Zdanie nad kartą; domyślnie „Nie przypisano do …” („Przypisz do rekrutacji”). */
  headline?: string;
}

export function ClosedCardRestore({ job, row, onRestored, headline }: ClosedCardRestoreProps) {
  const move = usePipelineMoveCore({ jobId: job.id });
  const [restoring, setRestoring] = useState(false);
  // Ekran pokazuje panel nad listą rekrutacji, a „Przypisz” bywa kliknięte
  // daleko niżej — bez przewinięcia odmowa byłaby poza widokiem.
  const panel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    panel.current?.scrollIntoView?.({ block: "nearest" });
  }, [job.id]);

  const restore = async () => {
    setRestoring(true);
    let restored = false;
    try {
      const outcome = await move.send(restoreMovePayload(row.candidate_id, job.id, row.closed), {
        candidateName: row.closed.candidate_name,
        eligibilitySubject: row.closed.candidate_name,
        fallbackMessage: "Nie udało się przywrócić karty.",
      });
      restored = outcome.ok;
    } finally {
      setRestoring(false);
    }
    if (restored) onRestored();
  };

  return (
    <div ref={panel}>
      <AddToRecruitmentOutcome
        headline={headline ?? `Nie przypisano do „${job.title}”.`}
        closedRows={[row]}
        otherText={null}
        restoredIds={NONE}
        restoringId={restoring ? row.candidate_id : null}
        onRestore={() => void restore()}
      />
      {move.dialogs}
    </div>
  );
}
