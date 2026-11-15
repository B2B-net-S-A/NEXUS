/**
 * Zespół dla klienta od strony NEXUSA — lustro `/api/job-teams`
 * (`docs/claude/klienci/zespol-dla-klienta.md`). Zespół to kilka zwykłych
 * rekrutacji jednego klienta pod jednym zapytaniem i jednym linkiem dla klienta.
 * Osobny plik niż `clientTeamPanel.ts`, bo ten ciągnie `@/lib/api` (token użytkownika).
 */
import api from "@/lib/api";

export interface TeamMoney {
  /** Wewnętrzne API oddaje liczbę; publiczny panel stanowiska — tekst. */
  value: number | string;
  unit: string;
  currency: string;
}

export interface TeamCandidate {
  candidate_id: number;
  name: string;
  stage: string | null;
  sent_at: string | null;
  available_from: string | null;
  client_rate: TeamMoney | null;
  expected_rate: TeamMoney | null;
}

export interface TeamPositionDetail {
  job_id: number;
  title: string;
  headcount: number;
  closed: boolean;
  budget_min: number | null;
  budget_max: number | null;
  delivery_lead: { id: number; name: string } | null;
  candidates: TeamCandidate[];
}

export interface TeamSelection {
  id: number;
  created_at: string;
  author_name: string;
  author_email: string;
  note: string | null;
  picks: { job_id: number; candidates: { candidate_id: number; name: string }[] }[];
}

export interface TeamDetail {
  id: number;
  name: string;
  client_id: number;
  client_name: string | null;
  hours_per_month: number;
  positions: TeamPositionDetail[];
  panel: {
    enabled: boolean;
    show_rate: boolean;
    expires_at: string | null;
    url: string | null;
    short_url: string | null;
  };
  selections: TeamSelection[];
  /** Gotowe składy zatwierdzone przez DL-a (Z3); klient widzi tylko te. */
  variants: TeamVariantSaved[];
  variants_approved_at: string | null;
}

export interface TeamVariantPick {
  job_id: number;
  candidate_ids: number[];
}

/** Propozycja automatu: nic nie jest zapisane, dopóki DL nie zatwierdzi. */
export interface TeamVariantProposal {
  key: string;
  name: string;
  why: string;
  picks: TeamVariantPick[];
  hourly_total: number | null;
  start: string | null;
  unknown_start: number;
}

export interface TeamVariantSaved {
  key: string;
  name: string;
  why: string;
  picks: { job_id: number; candidates: { candidate_id: number; name: string }[] }[];
}

export interface TeamVariantInput {
  key: string;
  name: string;
  why: string;
  picks: TeamVariantPick[];
}

export interface TeamSummary {
  id: number;
  name: string;
  client_id: number;
  client_name: string | null;
  positions: number;
  seats: number;
}

export const jobTeamKeys = {
  detail: (id: number) => ["job-team", id] as const,
  byJob: (jobId: number) => ["job-team", "by-job", jobId] as const,
  forClient: (clientId: number) => ["job-team", "client", clientId] as const,
};

export const fetchTeam = (id: number): Promise<TeamDetail> =>
  api.get<TeamDetail>(`/api/job-teams/${id}`).then((r) => r.data);

export const fetchTeamsForClient = (clientId: number): Promise<TeamSummary[]> =>
  api.get<TeamSummary[]>("/api/job-teams", { params: { client_id: clientId } }).then((r) => r.data);

export const fetchTeamOfJob = (jobId: number): Promise<{ team: { id: number; name: string } | null }> =>
  api.get(`/api/job-teams/by-job/${jobId}`).then((r) => r.data);

export const createTeam = (body: { name: string; job_ids: number[] }): Promise<TeamDetail> =>
  api.post<TeamDetail>("/api/job-teams", body).then((r) => r.data);

export const updateTeam = (
  id: number,
  body: { name?: string; add_job_ids?: number[]; remove_job_ids?: number[] },
): Promise<TeamDetail> => api.patch<TeamDetail>(`/api/job-teams/${id}`, body).then((r) => r.data);

export const updateTeamPanel = (
  id: number,
  body: { enabled?: boolean; show_rate?: boolean },
): Promise<TeamDetail> => api.put<TeamDetail>(`/api/job-teams/${id}/panel`, body).then((r) => r.data);

export const rotateTeamLink = (id: number): Promise<TeamDetail> =>
  api.post<TeamDetail>(`/api/job-teams/${id}/panel/rotate-link`).then((r) => r.data);

export const proposeVariants = (id: number): Promise<{ variants: TeamVariantProposal[] }> =>
  api.get(`/api/job-teams/${id}/variants/proposal`).then((r) => r.data);

export const saveVariants = (id: number, variants: TeamVariantInput[]): Promise<TeamDetail> =>
  api.put<TeamDetail>(`/api/job-teams/${id}/variants`, { variants }).then((r) => r.data);
