// Kolejka „Czeka na Ciebie" (0348) — praca na Tablicach, której nikt nie widzi.
//
// Typy są lustrem `backend/app/api/board_tasks.py`. Serwer rozstrzyga, co
// należy do danej osoby (DZ: Delivery Lead w swoim portfelu, Head of
// Recruitment wszędzie; Cpro: wytypowana osoba). Front tylko pokazuje i woła
// zwykły ruch w pipeline — bez własnej ścieżki zapisu etapu.

import { useQuery } from "@tanstack/react-query";

import api from "@/lib/api";
import { WS_BACKED_SAFETY_POLL_MS } from "@/lib/polling";

export type BoardTaskKind = "dz" | "cpro_to_send" | "cpro_sent" | "dl_review";

export interface BoardTaskRow {
  kind: BoardTaskKind;
  stage_id: number;
  candidate_id: number;
  candidate_name: string;
  job_id: number;
  job_title: string;
  client_id: number | null;
  client_name: string | null;
  since: string;
  process_state_version: number;
  /** Etap, na który prowadzi akcja (DZ, „Wysłane do Cpro", a przy przeglądzie
   *  DL — „CV wysłane"). */
  target_stage_def_id: number | null;
  assignee_id: number | null;
  assignee_name: string | null;
  // Tylko przegląd DL (`dl_review`); przy pozostałych rodzajach puste.
  /** Etap „Odrzucony" szablonu rekrutacji — cel „Odrzuć (DL)". */
  rejected_stage_def_id?: number | null;
  verified_by_id?: number | null;
  verified_by_name?: string | null;
  verified_at?: string | null;
  /** Migawka stawki kandydata z wiersza „Zweryfikowany". */
  expected_rate_value?: number | null;
  expected_rate_unit?: "hourly" | "daily" | "monthly" | null;
  expected_rate_currency?: string | null;
  /** Wiersz etapu z zapisanym arkuszem screeningu (zwykle „Screening"). */
  screening_stage_id?: number | null;
}

export interface BoardTasksResponse {
  dz: BoardTaskRow[];
  cpro_to_send: BoardTaskRow[];
  cpro_sent: BoardTaskRow[];
  // Pola Pipeline v4 serwer wysyła zawsze; opcjonalne w typie, bo harness
  // `/preview/custom-dashboard` zasiewa kolejkę sprzed v4 (panel traktuje
  // brak jak pustą listę / bramkę z ról).
  /** Pipeline v4: zweryfikowani poza Nordeą czekający na przegląd DL. */
  dl_review?: BoardTaskRow[];
  window_days: number;
  dl_review_window_days?: number;
  can_approve_dz: boolean;
  /** Ruch na „CV wysłane" ze stawką do klienta — admin i Delivery Lead. */
  can_send_to_client?: boolean;
}

export const BOARD_TASKS_QUERY_KEY = ["board-tasks"] as const;

export function useBoardTasks() {
  return useQuery<BoardTasksResponse>({
    queryKey: BOARD_TASKS_QUERY_KEY,
    queryFn: () => api.get<BoardTasksResponse>("/api/board-tasks").then((r) => r.data),
    // Ruch na Tablicy unieważnia klucz sam (`pipeline_changed`); odpytywanie
    // to tylko siatka bezpieczeństwa.
    refetchInterval: WS_BACKED_SAFETY_POLL_MS,
    staleTime: 30_000,
  });
}

export function setCproAssignee(stageId: number, assigneeId: number) {
  return api
    .patch<{ stage_id: number; assignee_id: number; assignee_name: string | null; added_to_team: boolean }>(
      `/api/board-tasks/cpro/${stageId}/assignee`,
      { assignee_id: assigneeId }
    )
    .then((r) => r.data);
}

export interface AssigneeOption {
  id: number;
  name?: string | null;
  email?: string | null;
}

// Osoby, które mogą wysłać kandydata do Cpro — ten sam katalog, z którego
// wybiera się zespół rekrutacji (+ Head of Recruitment).
const ASSIGNEE_ROLES = [
  "recruiter",
  "sourcer",
  "tac",
  "delivery_lead",
  "talent_community_manager",
  "head_of_recruitment",
  "admin",
];

export function useCproAssigneeOptions(enabled = true) {
  return useQuery<AssigneeOption[]>({
    queryKey: ["users-directory", "cpro-assignees"],
    queryFn: () =>
      api
        .get<AssigneeOption[]>("/api/users", {
          params: { roles: ASSIGNEE_ROLES },
          paramsSerializer: { indexes: null },
        })
        .then((r) => r.data),
    enabled,
    staleTime: 5 * 60_000,
  });
}

export function assigneeLabel(option: AssigneeOption): string {
  return option.name || option.email || `Użytkownik #${option.id}`;
}

/** „od dziś", „od wczoraj", „od 3 dni" — ile czeka osoba w kolejce. */
export function waitingFor(since: string, now: Date = new Date()): string {
  const days = Math.floor((now.getTime() - new Date(since).getTime()) / 86_400_000);
  if (days <= 0) return "od dziś";
  if (days === 1) return "od wczoraj";
  return `od ${days} dni`;
}
