/**
 * „Wymagania do poprawy” (13.10.2026, D4) — propozycja uporządkowania wymagań
 * otwartej rekrutacji (backend `services/requirement_cleanup.py`, trasy
 * `…/requirement-proposal` w `api/jobs.py`).
 *
 * Serwer liczy propozycję na żywo z Profilu Championa: zdania z wierszy
 * słów kluczowych idą do „Rekruter sprawdza w rozmowie”, technologia traci
 * komentarz w nawiasie, kolumnę zdań z requestu zastępują słowa z Championa,
 * a krytyczne zapisane samymi zdaniami spadają do „Musi mieć”.
 * Decyzja (zatwierdź / odrzuć) niesie `profile_hash` — profil zmieniony od
 * odczytu = 409 z nową propozycją.
 */

import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";

import { api, type ChampionProfileResponse } from "@/lib/api";
import { BOARD_TASKS_QUERY_KEY } from "@/lib/api/boardTasks";
import { invalidateChampionDependents } from "@/lib/champion-cache";
import type { StoredRequirementRow } from "@/lib/requirement-rows";

export interface RequirementProposalReason {
  code: string;
  text: string;
}

/** Pozycja przenoszona do „Rekruter sprawdza w rozmowie”. */
export interface RequirementProposalTalkItem {
  name: string;
  kind: "skills" | "domains";
  level: "must" | "nice";
}

/**
 * Wiersz „musi mieć” z mniej niż 20 osobami w bazie (27.10.2026, `rare_word`):
 * rozdzielony na sklejone warianty albo przeniesiony do rozmowy.
 */
export interface RequirementProposalRareRow {
  words: string[];
  /** Liczba osób jak licznik „W bazie” w edytorze (najwyżej 20). */
  people: number;
  action: "split" | "talk";
  parts: string[] | null;
}

export interface RequirementProposal {
  job_id: number;
  reasons: RequirementProposalReason[];
  /** Pisownia jak na ekranie dziś: kolumna rekrutacji albo Champion. */
  before: { must: string[]; critical: string[]; language: string | null };
  after: {
    rows: StoredRequirementRow[];
    critical: string[] | null;
    talk: RequirementProposalTalkItem[];
    language: string | null;
    /** Słowa ponad limit wierszy — trafią do opisu wymagań (jak przy zapisie). */
    overflow?: string[];
    rare?: RequirementProposalRareRow[];
  };
  profile_hash: string;
  /** Wymagania sprawdził wcześniej człowiek — zatwierdzenie je zastąpi. */
  contract_reviewed: boolean;
  /** `false` = brak słów do szukania; zatwierdzić się nie da. */
  can_apply: boolean;
  /** Odcisk propozycji — decyzja go odsyła; liczby osób nie wchodzą do `profile_hash`. */
  digest?: string;
}

/** Co decyzja odsyła serwerowi: odcisk profilu i odcisk widzianej propozycji. */
export type RequirementProposalDecisionKey = Pick<RequirementProposal, "profile_hash" | "digest">;

export interface RequirementProposalResponse {
  proposal: RequirementProposal | null;
  /** DL tej rekrutacji, Head of Recruitment albo admin. */
  can_decide: boolean;
}

/** Odpowiedź zatwierdzenia = odpowiedź zapisu Profilu Championa. */
export type ApplyRequirementProposalResponse = ChampionProfileResponse & {
  notices?: string[];
};

export interface DismissRequirementProposalResponse {
  job_id: number;
  status: "dismissed";
}

export const STALE_PROPOSAL_CODE = "requirement_proposal_stale";

export const requirementProposalKey = (jobId: number) =>
  ["requirement-proposal", jobId] as const;

export const requirementProposalApi = {
  get: (jobId: number) =>
    api
      .get<RequirementProposalResponse>(`/api/jobs/${jobId}/requirement-proposal`)
      .then((r) => r.data),
  apply: (jobId: number, key: RequirementProposalDecisionKey) =>
    api
      .post<ApplyRequirementProposalResponse>(
        `/api/jobs/${jobId}/requirement-proposal/apply`,
        { profile_hash: key.profile_hash, proposal_digest: key.digest },
      )
      .then((r) => r.data),
  dismiss: (jobId: number, key: RequirementProposalDecisionKey) =>
    api
      .post<DismissRequirementProposalResponse>(
        `/api/jobs/${jobId}/requirement-proposal/dismiss`,
        { profile_hash: key.profile_hash, proposal_digest: key.digest },
      )
      .then((r) => r.data),
};

/** Nowa propozycja z 409 `requirement_proposal_stale` albo `null`. */
export function staleProposalFrom(error: unknown): RequirementProposal | null {
  const response = (error as { response?: { status?: unknown; data?: unknown } } | null)?.response;
  if (response?.status !== 409) return null;
  const detail = (response.data as { detail?: unknown } | null | undefined)?.detail;
  if (!detail || typeof detail !== "object") return null;
  const { code, proposal } = detail as { code?: unknown; proposal?: unknown };
  if (code !== STALE_PROPOSAL_CODE || !proposal || typeof proposal !== "object") return null;
  return proposal as RequirementProposal;
}

function isConflict(error: unknown): boolean {
  return (error as { response?: { status?: unknown } } | null)?.response?.status === 409;
}

export function useRequirementProposal(jobId: number, enabled = true) {
  return useQuery({
    queryKey: requirementProposalKey(jobId),
    queryFn: () => requirementProposalApi.get(jobId),
    enabled: enabled && Number.isFinite(jobId) && jobId > 0,
  });
}

function invalidateAfterDecision(qc: QueryClient, jobId: number) {
  void qc.invalidateQueries({ queryKey: requirementProposalKey(jobId) });
  void qc.invalidateQueries({ queryKey: BOARD_TASKS_QUERY_KEY });
}

/**
 * 409: profil zmienił się od odczytu — nowa propozycja trafia od razu do
 * pamięci zapytania (okno rysuje ją bez ponownego odczytu); 409 bez
 * propozycji = nie ma już czego poprawiać, więc wiersz pulpitu znika.
 */
function onDecisionError(qc: QueryClient, jobId: number, error: unknown) {
  const fresh = staleProposalFrom(error);
  if (fresh) {
    qc.setQueryData<RequirementProposalResponse>(requirementProposalKey(jobId), (prev) => ({
      proposal: fresh,
      // Serwer sprawdza prawo do decyzji przed porównaniem odcisku.
      can_decide: prev?.can_decide ?? true,
    }));
    void qc.invalidateQueries({ queryKey: BOARD_TASKS_QUERY_KEY });
    return;
  }
  if (isConflict(error)) invalidateAfterDecision(qc, jobId);
}

export function useApplyRequirementProposal(jobId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (key: RequirementProposalDecisionKey) =>
      requirementProposalApi.apply(jobId, key),
    onSuccess: () => {
      invalidateAfterDecision(qc, jobId);
      invalidateChampionDependents(qc, jobId);
    },
    onError: (error) => onDecisionError(qc, jobId, error),
  });
}

export function useDismissRequirementProposal(jobId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (key: RequirementProposalDecisionKey) =>
      requirementProposalApi.dismiss(jobId, key),
    onSuccess: () => invalidateAfterDecision(qc, jobId),
    onError: (error) => onDecisionError(qc, jobId, error),
  });
}
