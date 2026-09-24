/**
 * Klient skrzynki „Propozycje z bazy" rekrutacji (backend: `job_proposals.py`)
 * oraz odczytu najnowszego zakończonego przeglądu bazy (`candidate_search.py`).
 *
 * Ścieżka to `/proposal-inbox`, NIE `/proposals` — tamten adres zwraca
 * historię migawek rekomendacji (`proposalsApi` w `lib/api.ts`).
 */

import { api, type MatchEligibility } from "@/lib/api";
import type { SearchState } from "@/lib/full-candidate-search-api";
import type { ProposalSource } from "@/components/v2/recruitment/types";

export type ProposalInboxStatus = "proposed" | "dismissed" | "added";

/** Tożsamość węższa niż profil — bez kontaktu, jak wiersz pełnego przeglądu. */
export interface ProposalInboxCandidate {
  id: number;
  name: string | null;
  lastname: string | null;
  title: string | null;
  city: string | null;
  availability_status: string | null;
  availability_date: string | null;
  /** PLN/h; `null` także wtedy, gdy rola nie widzi finansów (patrz flaga). */
  expected_rate_hourly: number | null;
  expected_rate_redacted: boolean;
}

export interface ProposalInboxRequirement {
  id?: number | string;
  key?: string;
  name?: string;
  any_of?: string[];
  level?: string;
  status?: string;
}

/**
 * Allowlista serwera (`sanitize_evidence`): wyłącznie nazwy wymagań i liczby.
 * Cytatów z CV tu nie ma i nie będzie — wiersz żyje do usunięcia kandydata.
 */
export interface ProposalInboxEvidence {
  requirements?: ProposalInboxRequirement[];
  matched_must?: string[];
  matched_nice?: string[];
  missing_must?: string[];
  missing_nice?: string[];
  counts?: Record<string, number>;
  previously_dismissed?: boolean;
}

export interface ProposalInboxItem {
  candidate: ProposalInboxCandidate;
  /** `string` w unii: nowe źródło backendu nie może wywrócić widoku. */
  sources: Array<ProposalSource | (string & {})>;
  /** Decimal po stronie serwera — bywa serializowany jako tekst. */
  score: number | string | null;
  evidence: ProposalInboxEvidence | null;
  first_seen_at: string | null;
  last_seen_at: string | null;
  is_new: boolean;
  status: ProposalInboxStatus;
  /** Przegląd bazy, który zaproponował tę osobę (telemetria dodania). */
  run_id?: string | null;
  eligibility: MatchEligibility | null;
  /** Przepięcie (0341): skąd osoba przychodzi — rekrutacja, etap, data wysłania. */
  reassign_from?: ProposalReassignFrom | null;
}

export interface ProposalReassignFrom {
  job_id: number;
  title: string;
  reference_number: string | null;
  client_name: string | null;
  stage: string | null;
  /** ISO `YYYY-MM-DD` albo `null`. */
  sent_at: string | null;
}

export interface ProposalInboxPage {
  job_id: number;
  status: ProposalInboxStatus;
  items: ProposalInboxItem[];
  total: number;
  /** Ukryci na TEJ stronie przez globalną czarną listę — nigdy po cichu. */
  hidden_on_page: number;
  limit: number;
  offset: number;
  next_offset: number | null;
}

export interface LatestRunInfo {
  run_id: string;
  state: SearchState;
  completed_at: string | null;
  origin: "auto" | "manual" | (string & {});
  own: boolean;
}

export interface LatestRunResponse {
  job_id: number;
  /** `null` = nie było jeszcze żadnego przeglądu — poprawna odpowiedź, nie błąd. */
  run: LatestRunInfo | null;
}

export interface DismissProposalResponse {
  job_id: number;
  candidate_id: number;
  dismissed: boolean;
}

export interface RestoreProposalResponse {
  job_id: number;
  candidate_id: number;
  restored: boolean;
}

/** Historia osoby u klienta tej rekrutacji (inna jego rekrutacja). */
export interface ProposalClientHistory {
  job_id: number;
  title: string | null;
  /** Najdalszy etap „do przodu" (legacy enum). */
  furthest_stage: string;
  furthest_stage_label: string;
  outcome: "rejected" | "withdrawn" | "hired" | "in_progress" | (string & {});
  last_moved_at: string | null;
}

/** `GET /api/jobs/{id}/proposal-facts` — fakty o osobie, bez kontaktu. */
export interface ProposalFacts {
  candidate_id: number;
  title: string | null;
  company: string | null;
  years_experience: number | null;
  city: string | null;
  max_onsite_days_per_week: number | null;
  remote_modes: string[];
  availability_status: string | null;
  availability_date: string | null;
  expected_rate_hourly: number | null;
  expected_rate_currency: string | null;
  expected_rate_redacted: boolean;
  client_history: ProposalClientHistory | null;
}

/** Sufit jednego zapytania o fakty (`MAX_FACT_CANDIDATES`). */
export const PROPOSAL_FACTS_MAX_IDS = 100;

/** Sufit `limit` po stronie serwera (`Query(20, le=100)`). */
export const PROPOSAL_INBOX_MAX_LIMIT = 100;
export const PROPOSAL_INBOX_PAGE = 20;

export const jobProposalsApi = {
  inbox: (
    jobId: number,
    opts: { status?: ProposalInboxStatus; limit?: number; offset?: number } = {},
    signal?: AbortSignal,
  ): Promise<ProposalInboxPage> =>
    api
      .get<ProposalInboxPage>(`/api/jobs/${jobId}/proposal-inbox`, {
        params: {
          status: opts.status ?? "proposed",
          limit: opts.limit ?? PROPOSAL_INBOX_PAGE,
          offset: opts.offset ?? 0,
        },
        signal,
      })
      .then((r) => r.data),
  /**
   * „Pomiń" działa dla DOWOLNEJ osoby: spoza skrzynki serwer zakłada wiersz od
   * razu jako pominięty — `source` mówi mu, skąd ta osoba przyszła.
   */
  dismiss: (
    jobId: number,
    candidateId: number,
    source: ProposalSource = "full_base",
  ): Promise<DismissProposalResponse> =>
    api
      .post<DismissProposalResponse>(
        `/api/jobs/${jobId}/proposal-inbox/${candidateId}/dismiss`,
        { source },
      )
      .then((r) => r.data),
  /** „Cofnij" po „Pomiń" — osoba wraca do skrzynki całego zespołu. */
  restore: (jobId: number, candidateId: number): Promise<RestoreProposalResponse> =>
    api
      .post<RestoreProposalResponse>(
        `/api/jobs/${jobId}/proposal-inbox/${candidateId}/restore`,
      )
      .then((r) => r.data),
  /** Fakty hurtowo — najwyżej `PROPOSAL_FACTS_MAX_IDS` osób naraz. */
  facts: (
    jobId: number,
    candidateIds: readonly number[],
    signal?: AbortSignal,
  ): Promise<{ job_id: number; items: ProposalFacts[] }> =>
    api
      .get<{ job_id: number; items: ProposalFacts[] }>(`/api/jobs/${jobId}/proposal-facts`, {
        params: { candidate_ids: candidateIds },
        paramsSerializer: { indexes: null },
        signal,
      })
      .then((r) => r.data),
  latestRun: (jobId: number, signal?: AbortSignal): Promise<LatestRunResponse> =>
    api
      .get<LatestRunResponse>(`/api/candidate-search/jobs/${jobId}/latest-run`, {
        signal,
      })
      .then((r) => r.data),
};

/** Jeden prefiks = jedno unieważnienie po dodaniu/pominięciu. */
export const jobProposalsKeys = {
  all: (jobId: number) => ["job-proposals", jobId] as const,
  /**
   * Łączna liczba propozycji ze WSZYSTKICH źródeł (skrzynka, przegląd bazy,
   * podobne projekty, rekomendacje) — publikuje ją segment propozycji, czyta
   * pasek etapów. Sama skrzynka mówiła „0", gdy lista miała 35 osób.
   */
  visibleCount: (jobId: number) => ["job-proposals", jobId, "visible-count"] as const,
  inbox: (jobId: number, limit: number) =>
    ["job-proposals", jobId, "inbox", limit] as const,
  latestRun: (jobId: number) => ["job-proposals", jobId, "latest-run"] as const,
  /** Fakty o osobach — klucz zawiera posortowane id, żeby lista w innej kolejności trafiała w cache. */
  facts: (jobId: number, candidateIds: readonly number[]) =>
    ["job-proposals", jobId, "facts", [...candidateIds].sort((a, b) => a - b).join(",")] as const,
  /** Te same klucze co dotychczasowe sekcje — react-query dzieli z nimi cache. */
  similar: (jobId: number) => ["historical-candidates", jobId] as const,
  recommendations: (jobId: number) => ["proposal-latest", jobId] as const,
};
