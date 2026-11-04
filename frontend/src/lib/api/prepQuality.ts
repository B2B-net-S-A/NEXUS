// Insights → Wyniki → „Jakość prepów" (0370, prepy w Teams).
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

/**
 * 0482: rozmowy u klienta osoby (właściciel rozmowy = rekruter) bez Prepu 2
 * w ostatnich `skip_days` dniach.
 */
export interface Prep2SkipRow {
  person: { id: number; name: string };
  interviews: number;
  /** Bez Prepu 2 z zapisanym powodem i telefonem przed rozmową. */
  with_reason: number;
  /** Rozmowa się odbyła, prepów było mniej niż dwa, a powodu nikt nie zapisał. */
  silent: number;
  /**
   * Rozmowa zapisana w NEXUSIE dopiero po swoim starcie (pytania z datą wstecz,
   * import z notatek) — osobno, nie „bez słowa” (audyt 22.10, F28). Starszy serwer = brak.
   */
  after_the_fact?: number;
  /** `with_reason / interviews` (0..1). */
  share: number;
  /** Ponad próg i co najmniej dwie rozmowy — Head of Recruitment dostał dzwonek. */
  over_threshold: boolean;
  reasons: Record<string, number>;
}

export interface PrepQualityResponse {
  days: number;
  rows: PrepQualityRow[];
  /** Rozmowy u klienta w oknie (bez zapisanych po fakcie). */
  interviews: number;
  /** …z których przed rozmową odbyły się oba prepy. */
  interviews_with_two_preps: number;
  /** Rozmowy zapisane po fakcie — poza linią o dwóch prepach (audyt 22.10, F28). */
  interviews_after_the_fact?: number;
  /** 0482; starszy serwer = brak. */
  skip_days?: number;
  skip_threshold?: number;
  skip_rows?: Prep2SkipRow[];
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
