"use client";

import { useQuery } from "@tanstack/react-query";
import { orderMailApi } from "@/lib/api/orderMail";

/**
 * Liczba dokumentów z maila czekających na sprawdzenie („Do weryfikacji").
 * Zasila plakietkę trybu „Skrzynka zamówień" w Kontraktach i licznik przy
 * „Kontraktach" w menu — skrzynka nie ma już własnej pozycji, więc bez
 * licznika czekający dokument byłby niewidoczny.
 *
 * `undefined` = jeszcze nie wiadomo (albo błąd) — plakietka się nie pokazuje,
 * nigdy nie udaje zera.
 */
export function useOrderMailPendingCount(enabled: boolean): number | undefined {
  const query = useQuery({
    queryKey: ["order-mail", "pending-count"],
    queryFn: async () =>
      (await orderMailApi.listQueue({ outcome: "needs_review", limit: 1 })).data
        .total,
    enabled,
    staleTime: 60_000,
    refetchInterval: 5 * 60_000,
  });
  return enabled && query.isSuccess ? query.data : undefined;
}
