// Finanse → „Do korekty po zmianie stawki” (0741). Lustro
// `backend/app/api/finance.py` (`/order-cost-corrections`) i
// `backend/app/services/order_cost_steps.py`. Kwoty jako tekst dziesiętny.

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";

export type CostPart = { from: string; to: string | null; rate: string };

export type CostCorrectionMonth = {
  month: string;
  in_order: string;
  in_contract: string;
  diff: string;
};

export type OrderCostCorrection = {
  order_id: number;
  client_id: number;
  client_name: string;
  contract_id: number;
  person: string;
  order_number: string;
  start_date: string;
  end_date: string;
  unit: string;
  currency: string;
  in_order: CostPart[];
  in_contract: CostPart[];
  months: CostCorrectionMonth[];
  estimate: string;
};

export type CostCorrectionDecision = "apply" | "dismiss";

export const ORDER_COST_CORRECTIONS_KEY = ["finance", "order-cost-corrections"] as const;

export function useOrderCostCorrections() {
  return useQuery({
    queryKey: ORDER_COST_CORRECTIONS_KEY,
    queryFn: async () =>
      (await api.get<{ rows: OrderCostCorrection[] }>("/api/finance/order-cost-corrections"))
        .data,
  });
}

export async function decideOrderCostCorrection(
  orderId: number,
  decision: CostCorrectionDecision,
): Promise<void> {
  await api.post(`/api/finance/order-cost-corrections/${orderId}/${decision}`);
}
