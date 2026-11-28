/**
 * Polecenia inżynierów ze strony B2B Network (0806, `/api/candidate-referrals`).
 *
 * Rekruter prowadzi status i kwotę premii (1–5 tys. zł), „Wypłacona” oznacza
 * moduł Finanse osobną trasą.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";

const BASE = "/api/candidate-referrals";

export type ReferralStatus = "new" | "contacted" | "started" | "paid" | "rejected";

export interface CandidateReferral {
  id: number;
  referrer_name: string;
  referrer_email: string;
  referrer_candidate_id: number | null;
  /** Polecający ma działający kontrakt: premię dopisze do faktury. */
  referrer_contract_id: number | null;
  referred_name: string;
  referred_email: string | null;
  referred_linkedin: string | null;
  referred_role: string | null;
  candidate_id: number | null;
  submission_id: number | null;
  was_in_database: boolean;
  statement_text: string;
  status: ReferralStatus;
  /** Kwota jako tekst z dwoma miejscami po przecinku, np. "2500.00". */
  bonus_amount: string | null;
  status_note: string;
  status_changed_at: string | null;
  created_at: string;
}

export interface ReferralChange {
  status?: Exclude<ReferralStatus, "paid">;
  bonus_amount?: string | null;
  note?: string;
}

export const referralKeys = {
  list: ["candidate-referrals"] as const,
};

export function useCandidateReferrals(enabled = true) {
  return useQuery({
    queryKey: referralKeys.list,
    queryFn: async () =>
      (await api.get<{ referrals: CandidateReferral[] }>(BASE)).data.referrals,
    enabled,
    retry: false,
  });
}

export function useUpdateReferral() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, change }: { id: number; change: ReferralChange }) =>
      (await api.patch<{ referral: CandidateReferral }>(`${BASE}/${id}`, change)).data
        .referral,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: referralKeys.list }),
  });
}

export function useMarkReferralPaid() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) =>
      (await api.post<{ referral: CandidateReferral }>(`${BASE}/${id}/paid`)).data.referral,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: referralKeys.list }),
  });
}
