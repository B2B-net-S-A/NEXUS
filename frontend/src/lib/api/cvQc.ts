// QC CV (Rekrutacja v5, 24.09.2026) — kontrola CV firmowego przed wysłaniem
// do klienta albo do Cpro. Typy są lustrem kontraktu
// `docs/recruitment-v5-contract.md` (backend: `GET/POST
// /api/pipeline/stages/{id}/qc…`). Serwer liczy sprawdzenia i zmienia szkic
// CV; front pokazuje wynik i woła poprawki.

import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";

import api from "@/lib/api";
import { BOARD_TASKS_QUERY_KEY } from "@/lib/api/boardTasks";

export type QcCheckStatus = "pass" | "fail" | "manual" | "skip";
export type QcSeverity = "blocking" | "warning";
export type QcFixKind =
  | "bold_all"
  | "generate_cv"
  | "upload_consent"
  | "ask_candidate"
  | "remove_term"
  | "ai"
  | "spelling";

export interface QcItem {
  requirement?: string | null;
  role?: string | null;
  detail?: string | null;
  fix?: QcFixKind | null;
  term?: string | null;
  /** Numer stanowiska w CV (kolejność ról w sekcji doświadczenia, od 0). */
  role_index?: number | null;
}

export interface QcCheck {
  key: string;
  label: string;
  severity: QcSeverity;
  status: QcCheckStatus;
  summary: string | null;
  items: QcItem[];
}

export interface QcCvRun {
  t: string;
  b: boolean;
}

export interface QcCvBlock {
  kind: "h" | "p" | "li";
  section: string | null;
  runs: QcCvRun[];
}

export interface QcCv {
  source: "branded_draft" | "branded_finalized" | "generated" | "document";
  editable: boolean;
  stage_id: number | null;
  generated_document_id: number | null;
  document_id: number | null;
  filename: string | null;
  /** `false` = pogrubień nie da się odczytać (CV z PDF-a). */
  bold_known: boolean;
  updated_at: string | null;
  blocks: QcCvBlock[];
}

export interface QcOverride {
  reason: string;
  by_name: string | null;
  at: string | null;
}

export interface QcResult {
  stage_id: number;
  candidate_id: number;
  candidate_name: string;
  job_id: number;
  job_title: string;
  client_name: string | null;
  passed: boolean;
  blocking_failed: number;
  warnings_count: number;
  override: QcOverride | null;
  run_id: number | null;
  computed_at: string | null;
  cv: QcCv | null;
  original_cv: { source: "snapshot" | "profile_text" | null; filename: string | null; text: string | null };
  client_request: { must: string[]; nice: string[] };
  checks: QcCheck[];
}

export interface QcFix {
  id: string;
  check_key: string;
  requirement: string | null;
  role: string | null;
  role_index?: number | null;
  /** Etykieta stanowiska tak, jak stoi w CV (`role` = etykieta z oryginału). */
  cv_role_label?: string | null;
  current_text: string | null;
  /** `**x**` = pogrubienie — renderowane jako tekst, nigdy HTML. */
  proposed_text: string;
  source: "original" | "notes";
  source_quote: string | null;
}

export interface QcFixesResponse {
  status: "ok" | "unavailable" | "no_cv" | "not_editable";
  cached: boolean;
  fixes: QcFix[];
}

export type QcApplyBody =
  | { action: "ai_fix"; fix_id: string; text?: string }
  | { action: "bold_all"; scope: "must" | "nice" }
  | { action: "remove_term"; term: string }
  | { action: "spelling" };

export const cvQcQueryKey = (stageId: number) => ["cv-qc", stageId] as const;
export const cvQcFixesQueryKey = (stageId: number) => ["cv-qc", stageId, "fixes"] as const;

export function useCvQc(stageId: number | null, enabled = true) {
  return useQuery<QcResult>({
    queryKey: cvQcQueryKey(stageId ?? 0),
    queryFn: () => api.get<QcResult>(`/api/pipeline/stages/${stageId}/qc`).then((r) => r.data),
    enabled: stageId != null && enabled,
    // CV poprawia się też poza oknem (edytor, generator) — każde otwarcie
    // liczy QC od nowa.
    staleTime: 0,
    refetchOnMount: "always",
  });
}

/**
 * Propozycje poprawek AI — POST, bo pierwszy odczyt danej treści płaci za
 * model; serwer pamięta wynik per treść. `enabled` = rekruter kliknął
 * „Zaproponuj poprawki (AI)". Wynik zapisany wcześniej w cache (także zasiew
 * harnessu) jest widoczny bez kliknięcia.
 */
export function useCvQcFixes(stageId: number | null, enabled: boolean) {
  return useQuery<QcFixesResponse>({
    queryKey: cvQcFixesQueryKey(stageId ?? 0),
    queryFn: () => api.post<QcFixesResponse>(`/api/pipeline/stages/${stageId}/qc/fixes`).then((r) => r.data),
    enabled: stageId != null && enabled,
    staleTime: Infinity,
  });
}

/** Po każdej zmianie QC: karta na Tablicy (oba klucze) i kolejki pulpitu. */
export function invalidateAfterQcChange(queryClient: QueryClient, jobId: number): void {
  void queryClient.invalidateQueries({ queryKey: ["kanban", String(jobId)] });
  void queryClient.invalidateQueries({ queryKey: ["kanban", jobId] });
  void queryClient.invalidateQueries({ queryKey: BOARD_TASKS_QUERY_KEY });
}

function useQcWrite<TBody>(stageId: number | null, path: string, onChanged?: () => void) {
  const queryClient = useQueryClient();
  return useMutation<QcResult, unknown, TBody>({
    mutationFn: (body) =>
      api.post<QcResult>(`/api/pipeline/stages/${stageId}/qc/${path}`, body).then((r) => r.data),
    onSuccess: (result) => {
      queryClient.setQueryData(cvQcQueryKey(stageId ?? result.stage_id), result);
      invalidateAfterQcChange(queryClient, result.job_id);
      onChanged?.();
    },
  });
}

/** Zastosowanie poprawki — serwer zwraca świeży wynik QC, który zastępuje cache. */
export function useQcApply(stageId: number | null, onChanged?: () => void) {
  return useQcWrite<QcApplyBody>(stageId, "apply", onChanged);
}

/** „Przepuść mimo QC" — tylko admin i Delivery Lead (serwer odmawia reszcie). */
export function useQcOverride(stageId: number | null, onChanged?: () => void) {
  return useQcWrite<{ reason: string }>(stageId, "override", onChanged);
}

/** Minimalna długość powodu obejścia — lustro walidacji serwera. */
export const QC_OVERRIDE_MIN_REASON = 10;
