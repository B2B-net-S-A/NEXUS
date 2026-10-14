/**
 * „Pasuje też do” (14.10.2026, decyzje Artura D1–D2) — inne rekrutacje w pracy,
 * do których pasuje osoba dodana właśnie do tej rekrutacji. Serwer liczy to tą
 * samą regułą co automaty i „Moi ludzie” (`backend/app/services/also_fits.py`):
 * bramka „Wymagane (krytyczne)”, dopasowanie ≥ 70, najwyżej 3.
 */

import { api } from "@/lib/api";

export interface AlsoFitsJob {
  job_id: number;
  title: string;
  client_name: string | null;
  /** Ta sama liczba, którą rekrutacja pokazuje w „Szukaj w bazie”. */
  score: number;
  matching_must: string[];
  gap_must: string[];
}

export interface AlsoFitsResponse {
  candidate_id: number;
  from_job_id: number;
  /** `unavailable` = nie udało się sprawdzić (awaria wyszukiwania), nie „nic nie pasuje”. */
  status: "ok" | "unavailable";
  jobs: AlsoFitsJob[];
}

export const alsoFitsKeys = {
  one: (fromJobId: number, candidateId: number) =>
    ["also-fits", fromJobId, candidateId] as const,
};

export const alsoFitsApi = {
  get: (candidateId: number, fromJobId: number): Promise<AlsoFitsResponse> =>
    api
      .get<AlsoFitsResponse>(`/api/candidates/${candidateId}/also-fits`, {
        params: { from_job_id: fromJobId },
      })
      .then((r) => r.data),
};
