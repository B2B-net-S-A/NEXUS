// Nocny raport: stawka z kontraktu a stawka linii zamówienia MD (audyt A5).
// Lustro `backend/app/services/rate_divergence_report.py`. Kwoty jako tekst dziesiętny.

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";

export type RateDivergence = {
  person: string;
  client_name: string;
  order_number: string;
  leg: "revenue" | "cost";
  leg_label: string;
  month: string;
  currency: string;
  contract_rate: string;
  order_rate: string;
  difference: string;
  md: string | null;
  effect: string | null;
  rounding: boolean;
  link: string;
};

export type RateDivergenceReport = {
  generated_at: string | null;
  month: string | null;
  checked_lines: number;
  skipped: { no_contract_rate: number; other_currency: number };
  rows: RateDivergence[];
};

export function useRateDivergences() {
  return useQuery({
    queryKey: ["finance", "rate-divergences"],
    queryFn: async () =>
      (await api.get<RateDivergenceReport>("/api/finance/rate-divergences")).data,
  });
}
