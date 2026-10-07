"use client";

/**
 * „Nie odebrał” jednym kliknięciem — ta sama notatka-próba co w profilu
 * (rodzaj `contact_attempt`, typ ogólny; follow-up nie liczy jej jako
 * rozmowy). Licznik prób na karcie odświeża Tablica.
 *
 * Wydzielone z doku osoby (0424, 07.10.2026): ten sam przycisk stoi w doku
 * i w profilu przed telefonem obok formularza screeningu — jedna ścieżka
 * zapisu zamiast dwóch kopii.
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { useToast } from "@/components/Toast";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";
import api, { extractErrorMsg } from "@/lib/api";

export function useNoAnswerNote({ candidateId, jobId }: { candidateId: number; jobId: number }) {
  const { showSuccess, showError } = useToast();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      api.post("/api/notes", {
        candidate_id: candidateId,
        content: "Nie odebrał.",
        note_type: "general",
        kind: "contact_attempt",
        job_id: jobId,
      }),
    onSuccess: () => {
      showSuccess("Zapisano próbę kontaktu.");
      void queryClient.invalidateQueries({ queryKey: ["kanban", String(jobId)] });
      void queryClient.invalidateQueries({ queryKey: ["kanban", jobId] });
      void queryClient.invalidateQueries({ queryKey: candidateQueryKeys.notes(candidateId) });
      void queryClient.invalidateQueries({ queryKey: candidateQueryKeys.timelineRoot(candidateId) });
    },
    onError: (e) => showError(extractErrorMsg(e) || "Nie udało się zapisać próby kontaktu."),
  });
}
