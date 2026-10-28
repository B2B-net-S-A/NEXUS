"use client";

/**
 * Stan panelu „Ocena AI” w oknie „Kandydaci do dodania” (28.10.2026).
 *
 * Zakładka, z której przyszło zaznaczenie, podaje własne dodanie (`add`) —
 * „Szukaj ręcznie” drogę listy, propozycje drogę `proposals.addToJob` — więc
 * dodani schodzą z zaznaczenia i dostają „Cofnij” jak przy „Dodaj N do
 * Nowych”. Ostatnia zapisana ocena (bez zaznaczenia) dodaje przez
 * `proposals/bulk` ze źródłem `manual_search`, bo tam ją rekruter zlecił.
 */

import { useCallback, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { useToast } from "@/components/Toast";
import { apiErrorMessage } from "@/lib/api-error";
import { proposalsBulkApi } from "@/lib/candidate-search-api";

import { AiAssessmentPanel, type AiAssessmentPerson } from "./AiAssessmentPanel";

export interface AiAssessmentRequest {
  people: readonly AiAssessmentPerson[] | null;
  add?: (candidateIds: number[]) => Promise<readonly number[]>;
}

export function useAiAssessmentWindow({
  jobId,
  readOnly,
  onAdded,
}: {
  jobId: number;
  readOnly: boolean;
  onAdded?: () => void;
}): {
  open: (request: AiAssessmentRequest) => void;
  close: () => void;
  isOpen: boolean;
  overlay: ReactNode;
} {
  const [request, setRequest] = useState<AiAssessmentRequest | null>(null);
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();

  const addSaved = useCallback(
    async (candidateIds: number[]): Promise<readonly number[]> => {
      try {
        const result = await proposalsBulkApi.addInChunks(jobId, {
          candidate_ids: candidateIds,
          initial_stage_legacy: "new",
          source: "manual_search",
        });
        if (result.total_added > 0) showSuccess(`Dodano do Nowych: ${result.total_added}.`);
        else showError("Nikogo nie dodano — te osoby są już w rekrutacji albo dodanie jest zablokowane.");
        void queryClient.invalidateQueries({ queryKey: ["candidates-v2"] });
        void queryClient.invalidateQueries({ queryKey: ["kanban", String(jobId)] });
        void queryClient.invalidateQueries({ queryKey: ["kanban", jobId] });
        if (result.total_added > 0) onAdded?.();
        return result.added;
      } catch (err) {
        showError(apiErrorMessage(err, "Nie udało się dodać kandydatów do rekrutacji."));
        return [];
      }
    },
    [jobId, onAdded, queryClient, showError, showSuccess],
  );

  const close = useCallback(() => {
    setRequest(null);
    void queryClient.invalidateQueries({ queryKey: ["ai-assessment-latest", jobId] });
  }, [jobId, queryClient]);

  const overlay = request ? (
    <AiAssessmentPanel
      jobId={jobId}
      people={request.people}
      onAdd={request.add ?? addSaved}
      onClose={close}
      readOnly={readOnly}
    />
  ) : null;

  return { open: setRequest, close, isOpen: request != null, overlay };
}
