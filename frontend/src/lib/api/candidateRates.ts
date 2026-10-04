// „Stawka od” i historia stawek kandydata (0414, 04.10.2026).
//
// Serwer liczy najniższą stawkę z 18 miesięcy z kart rekomendacji, etapów,
// zmian profilu i zgłoszeń. Tu tylko odczyt historii i decyzja
// „Nie licz jako minimum”. Jawne minimum ustawia `updateProfileRate(…, true)`.

import { useQuery } from "@tanstack/react-query";

import api from "@/lib/api";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";

export type RateReason =
  | "minimum"
  | "counts"
  | "excluded"
  | "outside_window"
  | "superseded"
  | "not_comparable";

export interface RateObservation {
  key: string;
  amount_hourly: string | number | null;
  raw: string | null;
  at: string | null;
  source: string;
  job_id: number | null;
  job_title: string | null;
  client_name: string | null;
  author_name: string | null;
  explicit_minimum: boolean;
  reason: RateReason;
  excluded_by_name: string | null;
}

export interface PaidRate {
  kind: "contract" | "legacy";
  client_name: string | null;
  start_date: string | null;
  end_date: string | null;
  amount_hourly: string | number | null;
  redacted: boolean;
}

export interface RateFrom {
  amount: string | number;
  at: string | null;
  source: string | null;
  stale: boolean;
  key: string | null;
  job_id: number | null;
  job_title: string | null;
  client_name: string | null;
}

export interface RateOverview {
  candidate_id: number;
  enabled: boolean;
  window_start: string;
  rate_from: RateFrom | null;
  latest_amount: string | number | null;
  latest_at: string | null;
  count: number;
  observations: RateObservation[];
  paid: PaidRate[];
}

export const candidateRatesApi = {
  overview: (candidateId: number) =>
    api
      .get<RateOverview>(`/api/candidates/${candidateId}/rate-overview`)
      .then((r) => r.data),
  decide: (candidateId: number, key: string, decision: "exclude" | null) =>
    api
      .put(
        `/api/candidates/${candidateId}/rate-observations/${encodeURIComponent(key)}`,
        { decision },
      )
      .then((r) => r.data),
};

export function useRateOverview(candidateId: number, enabled = true) {
  return useQuery({
    queryKey: candidateQueryKeys.rateOverview(candidateId),
    queryFn: () => candidateRatesApi.overview(candidateId),
    enabled,
    retry: false,
  });
}
