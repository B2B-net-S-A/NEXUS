"use client";

/**
 * Wymagania przejścia na kolejną kolumnę Tablicy (Rekrutacja v5, okno
 * „Przesuń dalej”). Serwer (`GET /api/pipeline/move-requirements`) liczy,
 * czego brakuje do wskazanego etapu — sumując wymagania pominiętych kolumn —
 * i mówi, co zrobić głównym przyciskiem (`primary.kind`). Front niczego tu nie
 * zgaduje; tylko renderuje listę i wykonuje akcje przy brakach.
 *
 * Kontrakt: `docs/recruitment-v5-contract.md` („Wymagania przejścia”).
 */

import { useQuery } from "@tanstack/react-query";

import api from "@/lib/api";
import type { BoardColumnKey } from "@/lib/board-stages";

export type MoveRequirementStatus = "ok" | "missing" | "waiting";

export type MoveRequirementActionKind =
  | "generate_cv"
  | "open_screening"
  | "set_candidate_rate"
  | "open_qc"
  | "set_client_rate"
  | "open_debrief"
  | "request_slots";

export interface MoveRequirementAction {
  kind: MoveRequirementActionKind | null;
  label: string | null;
  /** Wiersz etapu, na którym akcja działa (QC, arkusz screeningu). */
  stage_id?: number | null;
  /** Rozmowa u klienta, pod którą zapisuje się debrief (gdy serwer ją zna). */
  event_id?: number | null;
}

export interface MoveRequirementItem {
  key: string;
  label: string;
  detail?: string | null;
  status: MoveRequirementStatus;
  blocking: boolean;
  action?: MoveRequirementAction | null;
}

export type MovePrimaryKind = "move" | "hand_to_dl" | "hand_to_cpro" | "blocked";

export interface MovePrimary {
  kind: MovePrimaryKind;
  label: string;
  /** `hand_to_cpro`: etap „Wysłać do Cpro” w szablonie tej rekrutacji. */
  target_stage_def_id?: number | null;
}

export interface MoveRequirementsResponse {
  from_column: BoardColumnKey | null;
  to_column: BoardColumnKey | null;
  skipped_columns: BoardColumnKey[];
  items: MoveRequirementItem[];
  primary: MovePrimary;
  owner_note?: string | null;
}

export interface MoveRequirementsParams {
  candidateId: number;
  jobId: number;
  toStageDefId: number | null;
}

/** Prefiks — unieważnia wymagania wszystkich osób (po akcji z okna). */
export const MOVE_REQUIREMENTS_PREFIX = ["move-requirements"] as const;

export const moveRequirementsQueryKey = ({ candidateId, jobId, toStageDefId }: MoveRequirementsParams) =>
  ["move-requirements", jobId, candidateId, toStageDefId] as const;

export const moveRequirementsApi = {
  get: async (params: MoveRequirementsParams, signal?: AbortSignal) =>
    (
      await api.get<MoveRequirementsResponse>("/api/pipeline/move-requirements", {
        params: {
          candidate_id: params.candidateId,
          job_id: params.jobId,
          to_stage_def_id: params.toStageDefId ?? undefined,
        },
        signal,
      })
    ).data,
};

export function useMoveRequirements(params: MoveRequirementsParams | null, enabled = true) {
  return useQuery({
    queryKey: params
      ? moveRequirementsQueryKey(params)
      : (["move-requirements", "idle"] as const),
    queryFn: ({ signal }) => moveRequirementsApi.get(params as MoveRequirementsParams, signal),
    enabled: enabled && params != null && params.toStageDefId != null,
    // Wymagania zmieniają się po każdej akcji z okna — zawsze świeże.
    staleTime: 0,
    retry: 0,
  });
}

/**
 * Brak, który blokuje przycisk główny. `set_candidate_rate` i
 * `set_client_rate` NIE blokują — okno stawki i tak otwiera się przy ruchu
 * (`usePipelineMove`), więc wystarczy, że lista mówi o nich wprost.
 */
export function isBlockingGap(item: MoveRequirementItem, askedDuringMove: boolean): boolean {
  if (!item.blocking || item.status !== "missing") return false;
  const kind = item.action?.kind ?? null;
  if (askedDuringMove && (kind === "set_candidate_rate" || kind === "set_client_rate")) return false;
  return true;
}
