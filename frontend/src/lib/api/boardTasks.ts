// Kolejka „Czeka na Ciebie" (0348, 0353) — praca na Tablicach, której nikt nie widzi.
//
// Typy są lustrem `backend/app/api/board_tasks.py`. Serwer rozstrzyga, co
// należy do danej osoby (DZ: Delivery Lead w swoim portfelu, Head of
// Recruitment wszędzie; Cpro: osoba ustawiona dla CAŁEJ rekrutacji). Front
// tylko pokazuje i woła zwykły ruch w pipeline — bez własnej ścieżki zapisu
// etapu.

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
  /** 0353: osoba ustawiona dla CAŁEJ rekrutacji (`jobs.cpro_sender_id`). */
  job_sender_id?: number | null;
  job_sender_name?: string | null;
}

/** 0358: prep przed rozmową u klienta, który wymaga uwagi. Widzi go
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
  /** 0358: brak prepu, prep słaby albo bez nagrania. Opcjonalne w typie —
   *  harnessy zasiewają kolejkę sprzed 0355 (brak = pusta lista). */
  prep_attention?: PrepAttentionRow[];
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

/** Jedna osoba wysyła do Cpro kandydatów całej rekrutacji (decyzja 23.09.2026). */
export function setCproSender(jobId: number, assigneeId: number) {
  return api
    .put<{ job_id: number; assignee_id: number; assignee_name: string | null; added_to_team: boolean }>(
      `/api/board-tasks/cpro/jobs/${jobId}/sender`,
      { assignee_id: assigneeId }
    )
    .then((r) => r.data);
}

export interface CproJobGroup {
  job_id: number;
  job_title: string;
  client_name: string | null;
  /** Osoba ustawiona dla rekrutacji — nigdy typowanie jednego kandydata. */
  assignee_id: number | null;
  assignee_name: string | null;
  /** Typowania per kandydat sprzed 0353, gdy rekrutacja nie ma jeszcze osoby. */
  legacy_assignees: string[];
  /** Najdłużej czekający na górze — ta sama kolejność co lista z serwera. */
  rows: BoardTaskRow[];
}

/** „Do wysłania do Cpro" pogrupowane po rekrutacji — osoba jest per rekrutacja. */
export function groupCproByJob(rows: BoardTaskRow[]): CproJobGroup[] {
  const groups = new Map<number, CproJobGroup>();
  for (const row of rows) {
    let group = groups.get(row.job_id);
    if (!group) {
      group = {
        job_id: row.job_id,
        job_title: row.job_title,
        client_name: row.client_name,
        assignee_id: row.job_sender_id ?? null,
        assignee_name: row.job_sender_name ?? null,
        legacy_assignees: [],
        rows: [],
      };
      groups.set(row.job_id, group);
    }
    group.rows.push(row);
    if (group.assignee_id == null && row.assignee_name && !group.legacy_assignees.includes(row.assignee_name)) {
      group.legacy_assignees.push(row.assignee_name);
    }
  }
  return [...groups.values()];
}

// ── Przegląd DZ (0353) ──────────────────────────────────────────────────────

export interface DzCvRun {
  t: string;
  b: boolean;
}

export interface DzCvBlock {
  kind: "h" | "p" | "li";
  section: string | null;
  runs: DzCvRun[];
}

export interface DzCheck {
  label: string;
  /** Frazy szukane w CV: nazwa bez opisu po myślniku i bez nawiasów. */
  terms?: string[];
  in_cv: boolean;
  /** `null` = pogrubień nie da się odczytać (CV dla klienta z PDF-a). */
  bolded: boolean | null;
  in_original: boolean;
  original_roles: string[];
  missing_in_roles: string[];
  roles_absent: string[];
}

export interface DzReview {
  stage_id: number;
  candidate_id: number;
  candidate_name: string;
  job_id: number;
  job_title: string;
  client_name: string | null;
  client_request: {
    must: string[];
    nice: string[];
    description: string | null;
    project_about: string | null;
  };
  generated_cv: {
    /** `document` = plik „…B2B…" kandydata (CV zrobione poza generatorem). */
    source: "branded_finalized" | "branded_draft" | "generated" | "document";
    stage_id: number | null;
    generated_document_id: number | null;
    document_id?: number | null;
    filename?: string | null;
    bold_known?: boolean;
    updated_at: string | null;
    blocks: DzCvBlock[];
  } | null;
  original_cv: {
    source: "snapshot" | "profile_text" | null;
    stage_id: number | null;
    filename: string | null;
    text: string | null;
  };
  checks: DzCheck[];
  extra_bold: string[];
  summary: {
    must_total: number;
    must_in_cv: number;
    must_bolded: number;
    roles_missing: number;
    generated_roles: number;
    /** `false` = w CV dla klienta nie rozpoznano ról — sprawdź ręcznie. */
    roles_checked?: boolean;
    bold_known?: boolean;
  };
}

export interface DzHint {
  kind: string;
  severity: "high" | "medium" | "low";
  must_have: string | null;
  message: string;
  quote: string | null;
}

export interface DzHints {
  status: "ok" | "unavailable" | "no_cv";
  verdict: "ok" | "fix" | null;
  hints: DzHint[];
  model: string | null;
  cached: boolean;
}

export const dzReviewQueryKey = (stageId: number) => ["dz-review", stageId] as const;
/** Podpowiedzi należą do TREŚCI przeglądu: CV poprawione na Tablicy daje nowy
 *  klucz, więc stare „Brak must-have X" nie stoi obok CV, które już ma X. */
export function dzHintsSignature(review: DzReview | undefined): string {
  if (!review) return "";
  const cv = review.generated_cv;
  const words = (cv?.blocks ?? []).reduce((n, b) => n + b.runs.reduce((m, r) => m + r.t.length, 0), 0);
  return [
    cv?.source ?? "none",
    cv?.generated_document_id ?? cv?.document_id ?? "",
    cv?.updated_at ?? "",
    words,
    review.original_cv.stage_id ?? review.original_cv.source ?? "",
    review.client_request.must.join("|"),
  ].join(":");
}

export const dzHintsQueryKey = (stageId: number, signature: string) =>
  ["dz-review", stageId, "hints", signature] as const;

export function useDzReview(stageId: number | null) {
  return useQuery<DzReview>({
    queryKey: dzReviewQueryKey(stageId ?? 0),
    queryFn: () => api.get<DzReview>(`/api/board-tasks/dz/${stageId}/review`).then((r) => r.data),
    enabled: stageId != null,
    // Z okna idzie się na Tablicę poprawić CV — po powrocie zawsze świeży odczyt.
    staleTime: 0,
    refetchOnMount: "always",
  });
}

/** Podpowiedzi Luny — POST, bo pierwszy odczyt danej treści CV płaci za model;
 *  serwer pamięta wynik per treść, więc ponowne otwarcie nic nie kosztuje. */
export function useDzHints(stageId: number | null, review: DzReview | undefined, enabled: boolean) {
  return useQuery<DzHints>({
    queryKey: dzHintsQueryKey(stageId ?? 0, dzHintsSignature(review)),
    queryFn: () => api.post<DzHints>(`/api/board-tasks/dz/${stageId}/hints`).then((r) => r.data),
    enabled: stageId != null && review != null && enabled,
    staleTime: Infinity,
  });
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
