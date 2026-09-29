// „Champion po ludzku”, ściąga do rozmowy, biblioteka ról i słowniczek
// (kontrakt: `docs/champion-plain-brief-contract.md`).
//
// Typy są lustrem kontraktu backendu. Klucze zapytań są EKSPORTOWANYMI
// funkcjami: harness `/preview/plain-brief` zasiewa cache tymi samymi
// funkcjami, więc zmiana klucza w hooku nie rozjedzie się z zasiewem
// (niezasiany klucz = zapytanie w harnessie).

import { useEffect, useRef } from "react";
import {
  keepPreviousData,
  useIsMutating,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import api from "@/lib/api";
import { SLOW_ENDPOINT_TIMEOUT_MS } from "@/lib/http-timeouts";

// ── Typy ─────────────────────────────────────────────────────────────────

export interface PlainSource {
  url: string;
  title: string | null;
}

export type PlainBriefStatus = "none" | "ready" | "failed";
export type PlainOrigin = "seed" | "ai" | "manual";
export type PlainResearchStatus = "ready" | "researching" | "failed";

export type CandidateQaKey =
  | "client"
  | "rate"
  | "work"
  | "mode"
  | "start"
  | "process"
  | "team";

export interface CandidateQa {
  key: CandidateQaKey | string;
  question: string;
  /** `null` = profil tego nie mówi. */
  answer: string | null;
  source: string | null;
}

export interface ScreeningPlain {
  question_id: string;
  question: string;
  why: string | null;
  good: string | null;
  /** `null`, gdy profil nie ma powodu odrzucenia. */
  reject: string | null;
  original: { ideal_answer: string | null; deal_breaker: string | null } | null;
}

export type GlossaryLevel = "must" | "nice" | "experience";
export type GlossaryStatus = "ready" | "researching" | "failed" | "missing";

export interface GlossaryTerm {
  term_key: string;
  display_name: string;
  level: GlossaryLevel;
  level_label: string;
  status: GlossaryStatus;
  summary: string | null;
  does: string | null;
  cv_hints: string[];
  confused_with: string | null;
  in_this_project: string | null;
  sources: PlainSource[];
  origin: PlainOrigin | null;
}

export interface HiredTitle {
  title: string;
  count: number;
}

export interface RoleStats {
  jobs: number;
  clients: number;
  hires: number;
  /** Puste, gdy zatrudnionych jest mniej niż 3. */
  hired_titles: HiredTitle[];
}

export interface RoleProfile {
  id: number;
  slug: string;
  name: string;
  summary: string | null;
  example: string | null;
  day_to_day: string[];
  candidate_questions: string[];
  typical_skills: string[];
  sources: PlainSource[];
  origin: PlainOrigin;
  status: PlainResearchStatus;
  stats: RoleStats;
}

export interface BriefRole extends RoleProfile {
  assignment: "auto" | "manual";
}

export interface BriefClient {
  id: number;
  name: string;
  about: string | null;
  origin: "manual" | "web" | null;
  sources: PlainSource[];
}

export interface PlainBrief {
  job_id: number;
  status: PlainBriefStatus;
  stale: boolean;
  is_open: boolean;
  can_refresh: boolean;
  can_change_role: boolean;
  generated_at: string | null;
  message: string | null;
  one_liner: string | null;
  example: string | null;
  day_to_day: string[];
  pitch: string | null;
  candidate_qa: CandidateQa[];
  screening_plain: ScreeningPlain[];
  glossary: GlossaryTerm[];
  role: BriefRole | null;
  client: BriefClient | null;
}

export interface RoleProfileListItem {
  id: number;
  slug: string;
  name: string;
  summary: string | null;
  origin: PlainOrigin;
  status: PlainResearchStatus;
  jobs: number;
  updated_at: string | null;
}

export interface ChangeHistoryEntry {
  created_at: string;
  user_name: string | null;
  changes: Record<string, { old: unknown; new: unknown }>;
}

export interface RoleProfileDetail extends RoleProfile {
  history: ChangeHistoryEntry[];
}

export interface RoleProfilePayload {
  name: string;
  summary: string;
  example: string;
  day_to_day: string[];
  candidate_questions: string[];
  typical_skills: string[];
}

export type PlainTermScope = "all" | "dictionary" | "outside";

export interface PlainTerm {
  id: number;
  term_key: string;
  display_name: string;
  summary: string | null;
  does: string | null;
  cv_hints: string[];
  confused_with: string | null;
  sources: PlainSource[];
  origin: PlainOrigin | null;
  status: PlainResearchStatus;
  in_dictionary: boolean;
  updated_at: string | null;
  updated_by_name: string | null;
}

export interface PlainTermPayload {
  display_name: string;
  summary: string;
  does: string;
  cv_hints: string[];
  confused_with: string;
}

// ── Klucze ───────────────────────────────────────────────────────────────

export function plainBriefQueryKey(jobId: number) {
  return ["plain-brief", jobId] as const;
}

export function plainBriefRefreshMutationKey(jobId: number) {
  return ["plain-brief-refresh", jobId] as const;
}

export function roleProfilesQueryKey(q = "") {
  return ["role-profiles", "list", q] as const;
}

export function roleProfileQueryKey(id: number) {
  return ["role-profiles", "detail", id] as const;
}

export function plainTermsQueryKey(params: { q?: string; scope?: PlainTermScope } = {}) {
  return ["plain-terms", "list", params.scope ?? "all", params.q ?? ""] as const;
}

export function plainTermHistoryQueryKey(id: number) {
  return ["plain-terms", "history", id] as const;
}

// ── API ──────────────────────────────────────────────────────────────────

const asArray = <T,>(value: unknown): T[] => (Array.isArray(value) ? (value as T[]) : []);

/**
 * Odpowiedź API sprawdzana na granicy: kształt spoza kontraktu (inna trasa, stary
 * backend, pusta odpowiedź) daje `null` zamiast wywracać dok osoby i Podgląd
 * Championa na `undefined.length`. Listy zawsze są tablicami.
 */
export function normalizePlainBrief(raw: unknown): PlainBrief | null {
  if (!raw || typeof raw !== "object") return null;
  const data = raw as Record<string, unknown>;
  if (typeof data.job_id !== "number" || typeof data.status !== "string") return null;
  return {
    ...(data as unknown as PlainBrief),
    day_to_day: asArray<string>(data.day_to_day),
    candidate_qa: asArray<CandidateQa>(data.candidate_qa),
    screening_plain: asArray<ScreeningPlain>(data.screening_plain),
    glossary: asArray<GlossaryTerm>(data.glossary),
  };
}

export const plainKnowledgeApi = {
  brief: (jobId: number) =>
    api.get<PlainBrief>(`/api/jobs/${jobId}/plain-brief`).then((r) => normalizePlainBrief(r?.data)),
  // Generacja tekstów + research brakujących terminów — do ~60 s po stronie
  // serwera, więc długi sufit (`lib/http-timeouts.ts`).
  refresh: (jobId: number) =>
    api
      .post<PlainBrief>(`/api/jobs/${jobId}/plain-brief/refresh`, undefined, {
        timeout: SLOW_ENDPOINT_TIMEOUT_MS,
      })
      .then((r) => normalizePlainBrief(r?.data)),
  setRole: (jobId: number, roleProfileId: number | null) =>
    api
      .put<PlainBrief>(`/api/jobs/${jobId}/role-profile`, { role_profile_id: roleProfileId })
      .then((r) => normalizePlainBrief(r?.data)),
  roles: (q = "") =>
    api
      .get<{ items: RoleProfileListItem[] }>("/api/role-profiles", { params: q ? { q } : undefined })
      .then((r) => r.data),
  role: (id: number) =>
    api.get<RoleProfileDetail>(`/api/role-profiles/${id}`).then((r) => r.data),
  updateRole: (id: number, payload: RoleProfilePayload) =>
    api.put<RoleProfileDetail>(`/api/role-profiles/${id}`, payload).then((r) => r.data),
  terms: (params: { q?: string; scope?: PlainTermScope }) =>
    api
      .get<{ items: PlainTerm[] }>("/api/skills-admin/plain-terms", {
        params: { q: params.q || undefined, scope: params.scope ?? "all" },
      })
      .then((r) => r.data),
  updateTerm: (id: number, payload: PlainTermPayload) =>
    api.put<PlainTerm>(`/api/skills-admin/plain-terms/${id}`, payload).then((r) => r.data),
  // Kontrakt: „jak historia roli” — lista wpisów; przyjmujemy też opakowanie.
  termHistory: (id: number) =>
    api
      .get<ChangeHistoryEntry[] | { items?: ChangeHistoryEntry[]; history?: ChangeHistoryEntry[] }>(
        `/api/skills-admin/plain-terms/${id}/history`,
      )
      .then((r) =>
        Array.isArray(r.data) ? r.data : (r.data.items ?? r.data.history ?? []),
      ),
};

// ── Reguły ───────────────────────────────────────────────────────────────

/**
 * Czy otwarcie ekranu ma samo przygotować wyjaśnienie. Tylko otwarta
 * rekrutacja z nieaktualnym (albo jeszcze nieprzygotowanym) wyjaśnieniem
 * i tylko wtedy, gdy wolno odświeżać (w „podglądzie jako” nie wolno).
 * Zamknięta rekrutacja dostaje przycisk — generacja kosztuje, a nikt jej
 * tam nie potrzebuje na co dzień.
 */
export function shouldAutoRefresh(
  brief: Pick<PlainBrief, "status" | "stale" | "is_open" | "can_refresh"> | null | undefined,
): boolean {
  if (!brief) return false;
  return (brief.stale || brief.status === "none") && brief.is_open && brief.can_refresh;
}

/** Czy w wyjaśnieniu jest cokolwiek do pokazania. */
export function briefHasContent(brief: PlainBrief | null | undefined): boolean {
  if (!brief) return false;
  return Boolean(
    brief.one_liner ||
      brief.example ||
      brief.pitch ||
      brief.day_to_day.length ||
      brief.candidate_qa.length ||
      brief.screening_plain.length ||
      brief.glossary.length,
  );
}

// ── Hooki ────────────────────────────────────────────────────────────────

/** Co ile dociągać widok, gdy hasła słowniczka są jeszcze w researchu (w tle). */
export const RESEARCH_POLL_MS = 10_000;
/** Najwyżej tyle dociągnięć na jedno otwarcie (~5 min) — research, który utknął,
 *  nie może odpytywać bez końca. */
export const RESEARCH_POLL_LIMIT = 30;

export function researchPollInterval(
  brief: PlainBrief | null | undefined,
  polls: number,
): number | false {
  if (!brief || polls >= RESEARCH_POLL_LIMIT) return false;
  return brief.glossary.some((term) => term.status === "researching") ? RESEARCH_POLL_MS : false;
}

export function usePlainBrief(jobId: number) {
  return useQuery({
    queryKey: plainBriefQueryKey(jobId),
    queryFn: () => plainKnowledgeApi.brief(jobId),
    staleTime: 60_000,
    refetchInterval: (query) =>
      researchPollInterval(query.state.data, query.state.dataUpdateCount),
  });
}

export function useRefreshPlainBrief(jobId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationKey: plainBriefRefreshMutationKey(jobId),
    mutationFn: () => plainKnowledgeApi.refresh(jobId),
    onSuccess: (data) => {
      qc.setQueryData(plainBriefQueryKey(jobId), data);
    },
  });
}

/**
 * Jedno automatyczne odświeżenie na zamontowanie — nigdy w pętli. Gdy inny
 * widok już odświeża tę rekrutację (dok i Podgląd), nie dublujemy żądania.
 */
export function useAutoRefreshPlainBrief(
  jobId: number,
  brief: PlainBrief | null | undefined,
  refresh: { mutate: () => void },
): void {
  const fired = useRef(false);
  const running = useIsMutating({ mutationKey: plainBriefRefreshMutationKey(jobId) });
  const want = shouldAutoRefresh(brief);
  const { mutate } = refresh;
  useEffect(() => {
    if (!want || fired.current || running > 0) return;
    fired.current = true;
    mutate();
  }, [want, running, mutate]);
}

export function useSetJobRoleProfile(jobId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (roleProfileId: number | null) => plainKnowledgeApi.setRole(jobId, roleProfileId),
    onSuccess: (data) => {
      qc.setQueryData(plainBriefQueryKey(jobId), data);
    },
  });
}

export function useRoleProfiles(q = "", options: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: roleProfilesQueryKey(q),
    queryFn: () => plainKnowledgeApi.roles(q),
    staleTime: 60_000,
    placeholderData: keepPreviousData,
    enabled: options.enabled ?? true,
  });
}

export function useRoleProfile(id: number | null) {
  return useQuery({
    queryKey: roleProfileQueryKey(id ?? 0),
    queryFn: () => plainKnowledgeApi.role(id as number),
    enabled: id != null,
  });
}

export function useUpdateRoleProfile(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: RoleProfilePayload) => plainKnowledgeApi.updateRole(id, payload),
    onSuccess: (data) => {
      qc.setQueryData(roleProfileQueryKey(id), data);
      void qc.invalidateQueries({ queryKey: ["role-profiles", "list"] });
      // Wyjaśnienia rekrutacji czytają rolę z biblioteki.
      void qc.invalidateQueries({ queryKey: ["plain-brief"] });
    },
  });
}

export function usePlainTerms(params: { q?: string; scope?: PlainTermScope }) {
  return useQuery({
    queryKey: plainTermsQueryKey(params),
    queryFn: () => plainKnowledgeApi.terms(params),
    staleTime: 60_000,
    placeholderData: keepPreviousData,
  });
}

export function useUpdatePlainTerm(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: PlainTermPayload) => plainKnowledgeApi.updateTerm(id, payload),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["plain-terms"] });
      void qc.invalidateQueries({ queryKey: ["plain-brief"] });
    },
  });
}

export function usePlainTermHistory(id: number, enabled = true) {
  return useQuery({
    queryKey: plainTermHistoryQueryKey(id),
    queryFn: () => plainKnowledgeApi.termHistory(id),
    enabled,
  });
}
