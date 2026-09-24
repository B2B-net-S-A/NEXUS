// Insights → Wyniki → „Jakość prepów" (0369, prepy w Teams).
//
// Typy są lustrem `GET /api/interview-cycle/prep-quality`
// (`backend/app/api/prep_meetings.py`). Raport ocenia pracę konkretnych osób,
// więc serwer wpuszcza wyłącznie admina i Head of Recruitment (403 dla reszty).

import { useQuery } from "@tanstack/react-query";

import api from "@/lib/api";

export interface PrepQualityRow {
  organizer: { id: number; name: string };
  preps: number;
  recorded: number;
  unrecorded: number;
  good: number;
  ok: number;
  weak: number;
  /** Udział kandydata w rozmowie (0..1) ze wszystkich transkryptów; `null` = brak nagrań. */
  avg_talk_share: number | null;
}

export interface PrepQualityResponse {
  days: number;
  rows: PrepQualityRow[];
  /** Rozmowy u klienta w oknie. */
  interviews: number;
  /** …z których przed rozmową odbyły się oba prepy. */
  interviews_with_two_preps: number;
}

export const PREP_QUALITY_DEFAULT_DAYS = 90;

export const prepQualityQueryKey = (days: number) =>
  ["insights", "prep-quality", days] as const;

export function fetchPrepQuality(days: number): Promise<PrepQualityResponse> {
  return api
    .get<PrepQualityResponse>("/api/interview-cycle/prep-quality", {
      params: { days },
    })
    .then((r) => r.data);
}

export function usePrepQuality(
  days: number = PREP_QUALITY_DEFAULT_DAYS,
  enabled = true,
) {
  return useQuery({
    queryKey: prepQualityQueryKey(days),
    queryFn: () => fetchPrepQuality(days),
    enabled,
  });
}

/** „42%" albo „—" — brak nagrań to „nie wiadomo", nigdy „0%". */
export function formatTalkShare(value: number | null): string {
  return value === null ? "—" : `${Math.round(value * 100)}%`;
}
