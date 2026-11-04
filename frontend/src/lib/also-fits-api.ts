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
  /** Numer u klienta przed nazwą, jak w nagłówku rekrutacji (16.10.2026). */
  client_reference?: string | null;
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
  /** R2 (22.10.2026): nasz konsultant z decyzją „przekaż do front office”. */
  source?: "our_consultant" | null;
  /** „Wraca na rynek DD.MM”; brak przy `source` = data nieznana. */
  returns_to_market_on?: string | null;
}

/**
 * „+ Dodaj inną rekrutację” (29.10.2026): otwarta rekrutacja firmy bez tej
 * osoby, wyszukana ręcznie. Bez oceny — rekruter wie, czemu dodaje.
 */
export interface AlsoFitsManualJob {
  job_id: number;
  title: string;
  client_name: string | null;
  client_reference?: string | null;
  delivery_lead_name?: string | null;
  /** Rekrutacja może wejść do tej rozmowy (reguła par „Screening dla”). */
  joinable: boolean;
  /** Patrzący naprawdę jest w jej zespole — „Twój zespół”, na górze listy. */
  in_my_team: boolean;
}

/** Od tylu znaków szukamy (lustro `SEARCH_MIN_CHARS` serwera). */
export const ALSO_FITS_SEARCH_MIN_CHARS = 2;

export const alsoFitsKeys = {
  one: (fromJobId: number, candidateId: number) =>
    ["also-fits", fromJobId, candidateId] as const,
  search: (fromJobId: number, candidateId: number, q: string) =>
    ["also-fits", fromJobId, candidateId, "search", q] as const,
};

export const alsoFitsApi = {
  get: (candidateId: number, fromJobId: number): Promise<AlsoFitsResponse> =>
    api
      .get<AlsoFitsResponse>(`/api/candidates/${candidateId}/also-fits`, {
        params: { from_job_id: fromJobId },
      })
      .then((r) => r.data),
  search: (candidateId: number, fromJobId: number, q: string): Promise<AlsoFitsManualJob[]> =>
    api
      .get<AlsoFitsManualJob[]>(`/api/candidates/${candidateId}/also-fits/search`, {
        params: { from_job_id: fromJobId, q },
      })
      .then((r) => r.data),
};
