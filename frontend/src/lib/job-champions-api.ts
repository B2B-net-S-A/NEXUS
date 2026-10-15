/**
 * Championi rekrutacji — `GET/PUT /api/jobs/{id}/champions` (D1–D9,
 * 15.10.2026). PUT niesie PEŁNĄ listę po zapisie (pusta = zdejmij wszystkich);
 * serwer liczy z niej flagę „nie szukamy”, wstrzymanie P1 i stan pracy.
 * Stary `POST …/champion-found` zostaje tylko dla „Zdejmij championa”
 * z przeglądu requestów.
 */

import type { QueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type { BoardColumnKey } from "@/lib/board-stages";
import { invalidateJobTeam } from "@/lib/job-team-cache";

export interface JobChampionEntry {
  candidate_id: number;
  name: string;
  column: BoardColumnKey | null;
  /** Nazwa etapu do wyświetlenia (np. inna nazwa „CV wysłane” u klienta z Cpro). */
  stage_label: string | null;
  marked_by_name: string | null;
  marked_at: string | null;
}

export interface JobChampionEligible {
  candidate_id: number;
  name: string;
  column: BoardColumnKey | null;
  stage_label: string | null;
  is_champion: boolean;
}

export interface JobChampionsView {
  job_id: number;
  can_edit: boolean;
  /** `max(headcount, 1)`. */
  seats: number;
  hired_count: number;
  /** Flaga „nie szukamy” (`champion_found_at`). */
  search_stopped: boolean;
  /** Flaga bez żadnej osoby — oznaczenie sprzed 15.10.2026. */
  legacy_flag: boolean;
  /** Surowy `jobs.work_state`. */
  work_state: string | null;
  champions: JobChampionEntry[];
  /** Tylko przy `can_edit`; posortowane od najdalszej kolumny. */
  eligible: JobChampionEligible[];
}

export interface JobChampionsSaveResponse extends JobChampionsView {
  changed: boolean;
  work_state_changed: boolean;
}

export const jobChampionsQueryKey = (jobId: number) => ["job-champions", jobId] as const;

export const jobChampionsApi = {
  get: (jobId: number) =>
    api.get<JobChampionsView>(`/api/jobs/${jobId}/champions`).then((r) => r.data),
  save: (jobId: number, candidateIds: readonly number[]) =>
    api
      .put<JobChampionsSaveResponse>(`/api/jobs/${jobId}/champions`, {
        candidate_ids: candidateIds,
      })
      .then((r) => r.data),
};

/**
 * Po zmianie championów (zapis w okienku, odrzucenie championa): nagłówek
 * i lista (status, P1 wstrzymany), liczniki listy, pulpit obłożenia i karty
 * Tablicy (`is_champion`). Klucz rekrutacji ma dwa kształty — jak
 * w `invalidateJobTeam`. Lista championów tylko traci świeżość: okienko
 * i tak pyta o nią przy każdym otwarciu, a zamykane właśnie okienko nie ma
 * po co pobierać jej drugi raz.
 */
export function invalidateAfterChampionsChange(qc: QueryClient, jobId: number): void {
  invalidateJobTeam(qc, jobId);
  void qc.invalidateQueries({ queryKey: ["kanban", String(jobId)] });
  void qc.invalidateQueries({ queryKey: ["kanban", jobId] });
  void qc.invalidateQueries({ queryKey: jobChampionsQueryKey(jobId), refetchType: "none" });
}
