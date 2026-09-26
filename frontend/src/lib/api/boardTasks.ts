// Kolejka „Czeka na Ciebie" (0348, Rekrutacja v5) — praca na Tablicach, której
// nikt nie widzi.
//
// Typy są lustrem `backend/app/api/board_tasks.py` i kontraktu
// `docs/recruitment-v5-contract.md`. Serwer rozstrzyga, co należy do danej
// osoby (przegląd DL: osoby w kolumnie „QC CV" poza Nordeą; Cpro: JEDNA osoba
// na całą firmę, decyzja Artura 23.09.2026). Front tylko pokazuje i woła
// zwykły ruch w pipeline — bez własnej ścieżki zapisu etapu. Przegląd DZ
// (0353) zastąpiło QC CV (`lib/api/cvQc.ts`).

import { useQuery } from "@tanstack/react-query";

import api from "@/lib/api";
import type { FollowupRow } from "@/lib/api/candidateFollowups";
import { WS_BACKED_SAFETY_POLL_MS } from "@/lib/polling";

export type BoardTaskKind = "cpro_to_send" | "cpro_sent" | "dl_review";

/** Wynik QC CV pary (najnowszy przebieg) — lustro `qc_status` z serwera. */
export type QcStatus = "passed" | "failed" | "overridden" | "unchecked";

export interface BoardTaskRow {
  kind: BoardTaskKind;
  stage_id: number;
  candidate_id: number;
  candidate_name: string;
  job_id: number;
  job_title: string;
  /** 0380: tytuł dla rekrutera (ekrany wewnętrzne); `job_title` = nazwa od klienta. */
  job_working_title?: string | null;
  client_reference?: string | null;
  client_id: number | null;
  client_name: string | null;
  since: string;
  process_state_version: number;
  /** Etap, na który prowadzi akcja („Wysłane do Cpro", a przy przeglądzie
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
  /** v5: wynik QC CV (przegląd DL = osoby w kolumnie „QC CV"). */
  qc_status?: QcStatus | null;
  qc_blocking_failed?: number | null;
  /** Przegląd DL: etap z CV firmowym pary (po QC) — z niego podgląd i DOCX. */
  cv_stage_id?: number | null;
}

/** 0370: prep przed rozmową u klienta, który wymaga uwagi. Widzi go
 *  organizator prepu, admin i Head of Recruitment. */
export type PrepAttentionReason = "missing" | "weak" | "unrecorded";

export interface PrepAttentionRow {
  reason: PrepAttentionReason;
  /** 1 = prep prowadzi Delivery Lead, 2 = rekruter. */
  prep_no: 1 | 2;
  candidate_id: number;
  candidate_name: string;
  job_id: number;
  job_title: string;
  interview_event_id: number;
  /** Start rozmowy u klienta (ISO). */
  interview_start: string;
  prep_event_id: number | null;
  owner_id: number | null;
  /** Rozmowa tuż-tuż — wiersz wyróżniony. */
  urgent: boolean;
}

export const PREP_ATTENTION_REASON_LABEL: Record<PrepAttentionReason, string> = {
  missing: "brak prepu",
  weak: "prep słaby",
  unrecorded: "prep bez nagrania",
};

/** Karta kandydata w kalendarzu „Rozmowy u klienta” (`?cycle=c-j`). */
export function prepAttentionLink(row: Pick<PrepAttentionRow, "candidate_id" | "job_id">): string {
  return `/calendar?cycle=${row.candidate_id}-${row.job_id}`;
}

export interface BoardTasksResponse {
  cpro_to_send: BoardTaskRow[];
  cpro_sent: BoardTaskRow[];
  // Pola Pipeline v4 serwer wysyła zawsze; opcjonalne w typie (panel traktuje
  // brak jak pustą listę / bramkę z ról).
  /** v5: osoby w kolumnie „QC CV" poza Nordeą czekające na przegląd DL. */
  dl_review?: BoardTaskRow[];
  window_days: number;
  dl_review_window_days?: number;
  /** Ruch na „CV wysłane" ze stawką do klienta — admin i Delivery Lead. */
  can_send_to_client?: boolean;
  /** 0370: brak prepu, prep słaby albo bez nagrania. Opcjonalne w typie —
   *  harnessy zasiewają kolejkę sprzed 0355 (brak = pusta lista). */
  prep_attention?: PrepAttentionRow[];
  /** 0372: follow-upy z kandydatami do zrobienia przez Ciebie (termin do
   *  jutra). Opcjonalne w typie — brak = pusta lista. */
  followups?: FollowupRow[];
  /** 0372: Twoi kandydaci, z którymi follow-up robi ktoś inny. */
  followups_by_others?: FollowupRow[];
  /** Osobę od Cpro ustawia admin albo Delivery Lead Nordei (25.09.2026) —
   *  przełącznik stoi także wtedy, gdy sekcja Cpro jest pusta. */
  can_set_cpro_sender?: boolean;
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

// ── Cpro: jedna osoba na firmę (v5) ─────────────────────────────────────────

export interface CproSender {
  /** `null` = nikt nie jest ustawiony. */
  user_id: number | null;
  user_name: string | null;
  /** Zastępstwo do tego dnia (ISO), potem wraca `fallback_*`. */
  until: string | null;
  fallback_user_id: number | null;
  fallback_user_name: string | null;
  set_by_name: string | null;
  set_at: string | null;
  /** Czy pytający może zmienić osobę (admin albo Delivery Lead Nordei). */
  can_set?: boolean;
}

export interface CproQueueItem {
  stage_id: number;
  candidate_id: number;
  candidate_name: string;
  since: string;
  process_state_version: number;
  /** Etap „Wysłane do Cpro" — cel „✓ Wrzucone". */
  target_stage_def_id: number | null;
  /** Etap „QC CV" — cel „Zwróć do rekrutera". */
  return_stage_def_id: number | null;
  client_rate_value: number | null;
  client_rate_unit: "hourly" | "daily" | "monthly" | null;
  client_rate_currency: string | null;
  availability: string | null;
  qc_status: QcStatus | null;
  /** `stage_id` = CV firmowe etapu (po QC) — ma pierwszeństwo przed generatorem. */
  cv: {
    stage_id?: number | null;
    generated_document_id: number | null;
    document_id: number | null;
  } | null;
}

export interface CproQueueJob {
  job_id: number;
  job_title: string;
  /** 0380: tytuł dla rekrutera (ekrany wewnętrzne); `job_title` = nazwa od klienta. */
  job_working_title?: string | null;
  client_reference?: string | null;
  client_name: string | null;
  oldest_since: string;
  items: CproQueueItem[];
}

export interface CproQueueResponse {
  sender: CproSender;
  jobs: CproQueueJob[];
  sent_today: number;
}

export const CPRO_SENDER_QUERY_KEY = ["board-tasks", "cpro", "sender"] as const;
export const CPRO_QUEUE_QUERY_KEY = ["board-tasks", "cpro", "queue"] as const;

export function useCproSender(enabled = true) {
  return useQuery<CproSender>({
    queryKey: CPRO_SENDER_QUERY_KEY,
    queryFn: () => api.get<CproSender>("/api/board-tasks/cpro/sender").then((r) => r.data),
    enabled,
    staleTime: 60_000,
  });
}

export function useCproQueue(enabled = true) {
  return useQuery<CproQueueResponse>({
    queryKey: CPRO_QUEUE_QUERY_KEY,
    queryFn: () => api.get<CproQueueResponse>("/api/board-tasks/cpro/queue").then((r) => r.data),
    enabled,
    // Ruch z okna unieważnia kolejkę sam; odpytywanie to siatka bezpieczeństwa.
    refetchInterval: enabled ? WS_BACKED_SAFETY_POLL_MS : false,
  });
}

/** Osoba od Cpro dla CAŁEJ firmy; `until` = zastępstwo (potem wraca poprzednia). */
export function setCproSender(body: { user_id: number; until: string | null }) {
  return api.put<CproSender>("/api/board-tasks/cpro/sender", body).then((r) => r.data);
}

export interface CproJobGroup {
  job_id: number;
  job_title: string;
  client_name: string | null;
  /** Najdłużej czekający na górze — ta sama kolejność co lista z serwera. */
  rows: BoardTaskRow[];
}

/** „Do wrzucenia do Cpro" pogrupowane po rekrutacji — jedna linia na proces. */
export function groupCproByJob(rows: BoardTaskRow[]): CproJobGroup[] {
  const groups = new Map<number, CproJobGroup>();
  for (const row of rows) {
    let group = groups.get(row.job_id);
    if (!group) {
      group = { job_id: row.job_id, job_title: row.job_title, client_name: row.client_name, rows: [] };
      groups.set(row.job_id, group);
    }
    group.rows.push(row);
  }
  return [...groups.values()];
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
