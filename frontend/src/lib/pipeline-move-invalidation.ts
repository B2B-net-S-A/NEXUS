/**
 * Co odświeżyć po ruchu karty w pipeline — JEDNA lista dla Tablicy
 * (`usePipelineMove`), ekranów z własnym ruchem (`usePipelineMoveCore`)
 * i okna debriefu przed ruchem (`DebriefRequiredDialog`).
 *
 * Ruch zmienia nie tylko kolumnę: karta traci albo zyskuje follow-up „Klient
 * milczy” (liczony z kolumny procesu), zmienia się kolejka „Czeka na Ciebie”,
 * wymagania następnego etapu i historia etapów w panelu osoby. Przeglądy
 * produkcji 05.10.2026: po ruchu z „Rozmowy u klienta” na „Umowę” panel dalej
 * pokazywał „Kontakt z kandydatem — Klient milczy”, a po debriefie z bramki
 * ruchu Tablica i panel zostawały w „Rozmowie u klienta”, dopóki strona nie
 * została przeładowana.
 */

import type { QueryClient } from "@tanstack/react-query";

import { BOARD_TASKS_QUERY_KEY } from "@/lib/api/boardTasks";
import { MOVE_REQUIREMENTS_PREFIX } from "@/lib/api/moveRequirements";
import { candidateStageHistoryKey } from "@/lib/pipeline-version-conflict";

/** Prefiks follow-upu osoby (`candidateFollowupKeys.detail`). */
export const CANDIDATE_FOLLOWUP_PREFIX = ["candidate-followup"] as const;

export function invalidateAfterPipelineMove(
  queryClient: QueryClient,
  jobId: number,
  candidateId?: number | null,
): void {
  // Oba kształty klucza tablicy: strona trzyma `jobId` z `useParams` (tekst),
  // część konsumentów — liczbę.
  void queryClient.invalidateQueries({ queryKey: ["kanban", String(jobId)] });
  void queryClient.invalidateQueries({ queryKey: ["kanban", jobId] });
  // Follow-up liczy się dla OSOBY ze wszystkich jej procesów — ruch w tej
  // rekrutacji zmienia go też w innych, więc cały prefiks.
  void queryClient.invalidateQueries({ queryKey: CANDIDATE_FOLLOWUP_PREFIX });
  void queryClient.invalidateQueries({ queryKey: BOARD_TASKS_QUERY_KEY });
  void queryClient.invalidateQueries({ queryKey: MOVE_REQUIREMENTS_PREFIX });
  if (candidateId != null) {
    void queryClient.invalidateQueries({
      queryKey: candidateStageHistoryKey(candidateId, jobId),
    });
  }
}
