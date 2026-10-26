// „Kończą u klientów” w „Moich ludziach” Delivery Leada (decyzja Artura 25.10.2026).
//
// Lustro `GET /api/contracts/ending-consultants` (`backend/app/api/contracts.py`):
// konsultanci u klientów DL z umową kończącą się w N dni, bez potwierdzonych
// przedłużeń i bez kwot. Zakres klientów liczy serwer.

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";

export type ProlongationStatus = "unknown" | "yes" | "no" | "negotiate";

export interface EndingConsultant {
  contract_id: number;
  candidate_id: number;
  candidate_name: string | null;
  client_id: number | null;
  client_name: string | null;
  job_title: string | null;
  end_date: string;
  prolongation_status: ProlongationStatus | null;
}

export const ENDING_WINDOW_DAYS = 60;

export const PROLONGATION_LABELS: Record<ProlongationStatus, string> = {
  unknown: "przedłużenie: nie wiadomo",
  yes: "przedłużenie potwierdzone",
  no: "bez przedłużenia",
  negotiate: "przedłużenie w negocjacjach",
};

export const endingConsultantsQueryKey = ["contracts", "ending-consultants"] as const;

export const endingConsultantsApi = {
  list: async (days = ENDING_WINDOW_DAYS) =>
    (
      await api.get<EndingConsultant[]>("/api/contracts/ending-consultants", {
        params: { days },
      })
    ).data,
};

export function useEndingConsultants(enabled: boolean) {
  return useQuery({
    queryKey: endingConsultantsQueryKey,
    queryFn: () => endingConsultantsApi.list(),
    enabled,
    staleTime: 5 * 60_000,
  });
}
