// „Moi ludzie" — lista rekrutera, która buduje się sama.
//
// Typy są lustrem `backend/app/api/my_people.py`. Lista wylicza się na
// serwerze z historii pipeline'u: osoby, które rekruter zweryfikował jako
// pierwszy i które potem poszły do klienta. Front niczego nie liczy poza
// grupowaniem po kategorii — kto jest „mój", rozstrzyga backend.

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type { MatchEligibility } from "@/lib/api";
import { WS_BACKED_SAFETY_POLL_MS } from "@/lib/polling";

export type SnoozeReason = "found_job" | "not_interested" | "no_contact" | "other";

export const SNOOZE_REASON_LABELS: Record<SnoozeReason, string> = {
  found_job: "Znalazł pracę",
  not_interested: "Nie jest zainteresowany",
  no_contact: "Brak kontaktu",
  other: "Inny powód",
};

export interface MyPeopleRow {
  candidate_id: number;
  full_name: string;
  category_id: number | null;
  /** Najdalszy etap, na jaki osoba kiedykolwiek doszła w Twoich rekrutacjach. */
  furthest_stage: string | null;
  last_sent_at: string | null;
  last_sent_job_title: string | null;
  last_sent_client_name: string | null;
  /** W ilu rekrutacjach osoba poszła do klienta (Twoje pary). */
  sent_count: number;
  days_since_last_send: number | null;
  expected_rate_hourly: number | null;
  availability_status: string | null;
  city: string | null;
  source: "auto" | "pinned";
  /** Ile opublikowanych rekrutacji trzyma osobę dziś na etapie niekońcowym. */
  active_processes: number;
  /** Żywa umowa — osoba pracuje, grupa „Pracują". */
  working: boolean;
  snoozed: boolean;
  snooze_reason: SnoozeReason | null;
  snoozed_at: string | null;
  /** Nieobejrzane dopasowania do nowych rekrutacji. */
  new_matches: number;
}

export interface MyPeopleResponse {
  rows: MyPeopleRow[];
  total: number;
  active_count: number;
  working_count: number;
  snoozed_count: number;
  truncated: boolean;
}

export interface UnseenMatch {
  job_id: number;
  job_title: string;
  candidate_id: number;
  full_name: string;
  score: number | null;
  created_at: string;
}

export interface MyPeopleSummary {
  total: number;
  new_matches: number;
  jobs_with_matches: number;
  latest_matches: UnseenMatch[];
  idle_count: number;
  idle_top: { candidate_id: number; full_name: string; days_since_last_send: number }[];
  idle_days: number;
}

export interface ForJobRow {
  candidate_id: number;
  full_name: string;
  category_id: number | null;
  /** Kanoniczny fit 0-100; `null` = niepoliczony (patrz `measurement`), nie 0. */
  score: number | null;
  measurement: string;
  eligibility: MatchEligibility | null;
  sent_to_client_at: string | null;
  last_sent_client_name: string | null;
  days_since_last_send: number | null;
  expected_rate_hourly: number | null;
  active_processes: number;
}

export interface ForJobResponse {
  job_id: number;
  job_title: string;
  rows: ForJobRow[];
  in_job_count: number;
  /** Wektory/dostawca niedostępne — wyniki niepoliczone, to NIE „nikt nie pasuje". */
  degraded: boolean;
}

export const myPeopleApi = {
  list: async () => (await api.get<MyPeopleResponse>("/api/my-people")).data,
  summary: async () => (await api.get<MyPeopleSummary>("/api/my-people/summary")).data,
  forJob: async (jobId: number) =>
    (await api.get<ForJobResponse>(`/api/my-people/for-job/${jobId}`)).data,
  snooze: async (candidateId: number, reason: SnoozeReason) => {
    await api.post(`/api/my-people/${candidateId}/snooze`, { reason });
  },
  unsnooze: async (candidateId: number) => {
    await api.delete(`/api/my-people/${candidateId}/snooze`);
  },
  pin: async (candidateId: number) => {
    await api.post(`/api/my-people/${candidateId}/pin`);
  },
  unpin: async (candidateId: number) => {
    await api.delete(`/api/my-people/${candidateId}/pin`);
  },
  markSeen: async (jobId?: number) => {
    await api.post("/api/my-people/matches/seen", { job_id: jobId ?? null });
  },
};

export const myPeopleQueryKey = ["my-people", "list"] as const;
export const myPeopleSummaryQueryKey = ["my-people", "summary"] as const;
export const myPeopleForJobQueryKey = (jobId: number) =>
  ["my-people", "for-job", jobId] as const;
/** Prefiks unieważniający wszystkie trzy (po ruchu w pipeline, uśpieniu itd.). */
export const MY_PEOPLE_QUERY_PREFIX = ["my-people"] as const;

export function useMyPeople(enabled = true) {
  return useQuery({
    queryKey: myPeopleQueryKey,
    queryFn: myPeopleApi.list,
    enabled,
    staleTime: 60_000,
  });
}

export function useMyPeopleSummary(enabled = true) {
  return useQuery({
    queryKey: myPeopleSummaryQueryKey,
    queryFn: myPeopleApi.summary,
    enabled,
    staleTime: 60_000,
    // Dzwonek `my_people_match` przychodzi WebSocketem i unieważnia ten klucz;
    // odpytywanie to wyłącznie siatka bezpieczeństwa (lib/polling.ts).
    refetchInterval: WS_BACKED_SAFETY_POLL_MS,
    refetchIntervalInBackground: false,
  });
}

export function useMyPeopleForJob(jobId: number | null, enabled = true) {
  return useQuery({
    queryKey: myPeopleForJobQueryKey(jobId ?? 0),
    queryFn: () => myPeopleApi.forJob(jobId as number),
    enabled: enabled && jobId != null,
    staleTime: 60_000,
  });
}
