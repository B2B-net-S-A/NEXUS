// Sprzedaż → Leady → Boty: cztery boty, ich stan i wstrzymanie (13.11.2026).
//
// Lustro `backend/app/api/sales_bots.py`. Odczyt „Sprzedaż: podgląd”,
// wstrzymanie i wznowienie tylko administrator (`can_pause`).

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";

export type SalesBotKey = "lists" | "leads" | "research" | "company" | "contacts" | "cognism";

export interface SalesBot {
  key: SalesBotKey;
  name: string;
  kinds: string[];
  /** `own` — własna rutyna, `shared` — wspólny webhook, `none` — brak. */
  webhook: "own" | "shared" | "none";
  /** Główny włącznik z flag środowiskowych. */
  enabled: boolean;
  paused: boolean;
  runs_7d: number;
  received_7d: number;
  failed_7d: number;
  last_received_at: string | null;
}

export interface SalesBots {
  items: SalesBot[];
  can_pause: boolean;
}

export const salesBotsKey = ["sales", "bots"] as const;

export function useSalesBots() {
  return useQuery({
    queryKey: salesBotsKey,
    queryFn: async () => (await api.get<SalesBots>("/api/sales/bots")).data,
  });
}

export function useSetBotPaused() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (vars: { bot: SalesBotKey; paused: boolean }) =>
      (await api.post<SalesBots>(`/api/sales/bots/${vars.bot}/${vars.paused ? "pause" : "resume"}`, {})).data,
    onSuccess: (data) => queryClient.setQueryData(salesBotsKey, data),
  });
}
