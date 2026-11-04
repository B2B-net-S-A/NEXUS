// Stawki z rekrutacji w zamówieniu i umowie (D7, 08.10.2026).
//
// Backend: `services/recruitment_rates.py`. Stawka do klienta (za nią Delivery
// Lead wysłał osobę) jest punktem odniesienia dla przychodu w zamówieniu,
// stawka kandydata — dla kosztu w zamówieniu i umowie. Stawka do klienta
// przychodzi pusta z `client_rate_redacted = true` dla ról, które jej nie
// widzą w rekrutacji.

import { api } from "@/lib/api";

export interface RecruitmentRate {
  candidate_id: number;
  job_id: number;
  job_title: string | null;
  client_rate_value: number | string | null;
  client_rate_unit: string | null;
  client_rate_currency: string | null;
  client_rate_at: string | null;
  client_rate_by_name: string | null;
  client_rate_redacted: boolean;
  candidate_rate_value: number | string | null;
  candidate_rate_unit: string | null;
  candidate_rate_currency: string | null;
  candidate_rate_at: string | null;
}

export interface RecruitmentRateLookup {
  rate: RecruitmentRate | null;
  amounts_redacted: boolean;
}

/** Podpowiedź dla „Nowy kontraktor / zamówienie” — para z formularza albo najnowsza u klienta. */
export async function fetchRecruitmentRates(
  clientId: number,
  candidateId: number,
  jobId?: number | null,
): Promise<RecruitmentRateLookup> {
  const { data } = await api.get<RecruitmentRateLookup>(
    `/api/clients/${clientId}/recruitment-rates`,
    {
      params: jobId ? { candidate_id: candidateId, job_id: jobId } : { candidate_id: candidateId },
    },
  );
  return data;
}
