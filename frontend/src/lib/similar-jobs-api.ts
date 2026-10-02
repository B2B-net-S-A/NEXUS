/**
 * Podobne rekrutacje, przepięcia i „Mamy championa" (backend `job_similar.py`,
 * migracja 0341).
 *
 * Połączenie rekrutacji jest symetryczne i trwałe: osoby wysłane do klienta
 * w jednej trafiają do „Do przejrzenia" drugiej od razu, a kolejne — same,
 * przy każdym ruchu na „CV wysłane" i dalej.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type { BulkProposalsResponse } from "@/lib/candidate-search-api";

export interface SimilarJobItem {
  id: number;
  title: string;
  reference_number: string | null;
  status: "draft" | "published" | "closed" | (string & {});
  closed_at: string | null;
  client_name: string | null;
  /**
   * 0–100; `null` dla rekrutacji połączonej ręcznie spoza sugestii. Przy
   * `similarity_kind: "vector"` to kosinus wektorów rekrutacji × 100.
   */
  similarity: number | null;
  /**
   * Jak serwer policzył podobieństwo (30.09.2026): `vector` — wektor
   * rekrutacji (+ premia za tego samego klienta w kolejności), `lexical` —
   * dawny wzór (must-have, tytuł), gdy rekrutacja nie ma wektora albo Qdrant
   * nie odpowiada. `null`/brak — rekrutacja spoza sugestii.
   */
  similarity_kind?: SimilarityKind | null;
  /** Ile różnych osób dotarło tam do klienta (od „CV wysłane"). */
  sent_count: number;
  /** Ilu z nich da się przepiąć tutaj (bez zatrudnionych i obecnych). */
  reassignable_count?: number;
  linked: boolean;
}

export type SimilarityKind = "vector" | "lexical";

export interface SimilarJobsPayload {
  job_id: number;
  reassigned_count: number;
  /** Różne osoby do przepięcia z niepołączonych podpowiedzi (serwer). */
  reassignable_people?: number;
  linked: SimilarJobItem[];
  suggestions: SimilarJobItem[];
}

export interface LinkSimilarResponse extends SimilarJobsPayload {
  linked_now: number;
  reassigned_now: number;
}

/** Jak skończył się proces osoby w rekrutacji źródłowej. */
export type SentOutcome =
  | "in_progress"
  | "rejected_by_client"
  | "rejected"
  | "withdrawn"
  | "hired";

/** Osoba wysłana do klienta w podobnej rekrutacji (panel przepięć). */
export interface SentPerson {
  candidate_id: number;
  name: string;
  furthest_stage: string;
  /** Data pierwszego wysłania do klienta (RRRR-MM-DD). */
  sent_at: string | null;
  outcome: SentOutcome;
  already_in_job: boolean;
  /** Serwer: nie zatrudniony w źródle i jeszcze nie w tej rekrutacji. */
  selectable: boolean;
}

export interface SimilarPeoplePayload {
  job_id: number;
  jobs: Array<{ job_id: number; people: SentPerson[] }>;
}

export interface ReassignResponse extends BulkProposalsResponse {
  /** Rekrutacje połączone TYM wywołaniem (do „Cofnij”). */
  linked_now: number[];
}

export interface SimilarPreviewInput {
  title: string;
  must_skills: string[];
  competence_category_id?: number | null;
  /** Klient szkicu — premia za tego samego klienta w rankingu wektorowym. */
  client_id?: number | null;
}

export interface ChampionFoundResponse {
  job_id: number;
  champion_found: boolean;
  champion_found_at: string | null;
  changed: boolean;
}

export const similarJobsKey = (jobId: number) => ["similar-jobs", jobId] as const;
export const similarPeopleKey = (jobId: number, otherId: number) =>
  ["similar-people", jobId, otherId] as const;
export const similarSearchKey = (jobId: number, q: string) =>
  ["similar-jobs-search", jobId, q] as const;
/** Dopasowanie jednej osoby do rekrutacji docelowej — karta podglądu osoby. */
export const similarPersonScoreKey = (jobId: number, candidateId: number) =>
  ["similar-person-score", jobId, candidateId] as const;

export const similarJobsApi = {
  get: (jobId: number) =>
    api.get<SimilarJobsPayload>(`/api/jobs/${jobId}/similar`).then((r) => r.data),
  link: (jobId: number, jobIds: number[]) =>
    api
      .post<LinkSimilarResponse>(`/api/jobs/${jobId}/similar`, { job_ids: jobIds })
      .then((r) => r.data),
  unlink: (jobId: number, otherId: number) =>
    api
      .delete<SimilarJobsPayload>(`/api/jobs/${jobId}/similar/${otherId}`)
      .then((r) => r.data),
  people: (jobId: number, otherIds: number[]) =>
    api
      .get<SimilarPeoplePayload>(`/api/jobs/${jobId}/similar/people`, {
        params: { job_ids: otherIds },
        paramsSerializer: { indexes: null },
      })
      .then((r) => r.data),
  search: (jobId: number, q: string) =>
    api
      .get<{ items: SimilarJobItem[] }>(`/api/jobs/${jobId}/similar/search`, {
        params: { q },
      })
      .then((r) => r.data.items),
  reassign: (jobId: number, jobIds: number[], candidateIds: number[]) =>
    api
      .post<ReassignResponse>(`/api/jobs/${jobId}/similar/reassign`, {
        job_ids: jobIds,
        candidate_ids: candidateIds,
      })
      .then((r) => r.data),
  preview: (input: SimilarPreviewInput) =>
    api
      .post<{ suggestions: SimilarJobItem[] }>("/api/job-similarity/preview", input)
      .then((r) => r.data.suggestions),
  setChampionFound: (jobId: number, found: boolean) =>
    api
      .post<ChampionFoundResponse>(`/api/jobs/${jobId}/champion-found`, { found })
      .then((r) => r.data),
};

export function useSimilarJobs(jobId: number, enabled = true) {
  return useQuery({
    queryKey: similarJobsKey(jobId),
    queryFn: () => similarJobsApi.get(jobId),
    enabled: enabled && Number.isFinite(jobId) && jobId > 0,
    staleTime: 30_000,
  });
}

/** Po połączeniu odśwież to, co pokazuje przepięcia i podobne rekrutacje. */
function invalidateAfterLink(qc: ReturnType<typeof useQueryClient>, jobId: number) {
  qc.invalidateQueries({ queryKey: similarJobsKey(jobId) });
  qc.invalidateQueries({ queryKey: ["jobs-v2"] });
  // Połączenie jest symetryczne — przepięcia zmieniają skrzynki obu stron.
  qc.invalidateQueries({ queryKey: ["job-proposals"] });
}

export function useLinkSimilarJobs(jobId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (jobIds: number[]) => similarJobsApi.link(jobId, jobIds),
    onSuccess: (data) => {
      qc.setQueryData(similarJobsKey(jobId), data);
      invalidateAfterLink(qc, jobId);
    },
  });
}

export function useUnlinkSimilarJob(jobId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (otherId: number) => similarJobsApi.unlink(jobId, otherId),
    onSuccess: (data) => {
      qc.setQueryData(similarJobsKey(jobId), data);
      invalidateAfterLink(qc, jobId);
    },
  });
}

/** Ludzie wysłani do klienta w jednej podobnej rekrutacji (na kliknięcie). */
export function useSimilarPeople(jobId: number, otherId: number, enabled = true) {
  return useQuery({
    queryKey: similarPeopleKey(jobId, otherId),
    queryFn: () =>
      similarJobsApi.people(jobId, [otherId]).then((data) => data.jobs[0]?.people ?? []),
    enabled: enabled && jobId > 0 && otherId > 0,
    staleTime: 30_000,
  });
}

/**
 * Przepięcie jednym kliknięciem: połącz rekrutacje i dodaj wskazanych do
 * „Nowych”. Odświeża tablicę (oba klucze kanbana — liczbowy i tekstowy),
 * skrzynkę propozycji i podobne rekrutacje.
 */
export function useReassignFromSimilar(jobId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ jobIds, candidateIds }: { jobIds: number[]; candidateIds: number[] }) =>
      similarJobsApi.reassign(jobId, jobIds, candidateIds),
    onSuccess: () => {
      invalidateAfterLink(qc, jobId);
      qc.invalidateQueries({ queryKey: ["similar-people", jobId] });
      qc.invalidateQueries({ queryKey: ["kanban", String(jobId)] });
      qc.invalidateQueries({ queryKey: ["kanban", jobId] });
      qc.invalidateQueries({ queryKey: ["pipeline-scores"] });
    },
  });
}

/**
 * Podobieństwo do wyświetlenia: „≈ 72%” dla wektora rekrutacji (to nie wynik
 * wzoru, tylko bliskość treści), „72%” dla dawnego wzoru leksykalnego.
 * `null`, gdy serwer nie podał podobieństwa (rekrutacja spoza sugestii).
 */
export function similarityLabel(
  item: Pick<SimilarJobItem, "similarity" | "similarity_kind">,
): string | null {
  if (item.similarity == null) return null;
  return item.similarity_kind === "vector" ? `≈ ${item.similarity}%` : `${item.similarity}%`;
}

/** Podpowiedź (atrybut `title`) mówiąca, skąd liczba. */
export function similarityHint(
  item: Pick<SimilarJobItem, "similarity" | "similarity_kind">,
): string | undefined {
  if (item.similarity == null) return undefined;
  return item.similarity_kind === "vector"
    ? "Podobieństwo treści rekrutacji (wektor). Ten sam klient jest wyżej na liście."
    : "Wspólne must-have, słowa stanowiska i kategoria/klient.";
}

/** Ile osób przepnie zaznaczenie (górna granica — serwer pomija już obecnych). */
export function selectedSentCount(
  items: readonly SimilarJobItem[],
  selected: ReadonlySet<number>,
): number {
  return items.filter((i) => selected.has(i.id)).reduce((sum, i) => sum + i.sent_count, 0);
}
