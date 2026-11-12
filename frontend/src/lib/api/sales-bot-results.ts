// Sprzedaż → wyniki zadań bota do decyzji handlowca (0684, decyzje Artura 12.11.2026).
//
// Lustro `backend/app/api/sales_bot_results.py`. Odczyt: „Sprzedaż: podgląd”,
// decyzje: „Sprzedaż: edycja”. Z wyłączonym `SALES_BOT_TASKS_ENABLED` lista mówi
// `enabled: false`. Klucze zaczynają się od „sales”, więc zapis w Sprzedaży je odświeża.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";

import type { Ref } from "./sales";

export type BotResultKind = "discovery";
export type BotResultStatus = "new" | "accepted" | "rejected" | "partial";

export interface BotResult {
  id: number;
  kind: string;
  company: Ref | null;
  status: BotResultStatus;
  payload: Record<string, unknown>;
  created_at: string;
  run_id: number;
  /** Opiekun karty firmy i czy pracuje w Sprzedaży. */
  owner?: Ref | null;
  owner_in_sales?: boolean;
}

export interface BotResults {
  enabled: boolean;
  items: BotResult[];
}

export interface BotResultFilters {
  kind: BotResultKind;
  limit?: number;
}

/** Pozycja „Nowe centra IT” zapisana przez serwer w `payload`. */
export interface NewFirmPayload {
  company: string;
  domain: string | null;
  city: string;
  what: string;
  scale: string;
  why: string;
  url: string;
  published: string | null;
  /** Jak rozpoznano kartę: domena, nazwa, marka; `null` = karty nie ma. */
  match: "domain" | "name" | "brand" | null;
}

export function newFirmPayload(result: Pick<BotResult, "payload">): NewFirmPayload {
  const raw = result.payload ?? {};
  const text = (key: string) => (typeof raw[key] === "string" ? (raw[key] as string) : "");
  const match = text("match");
  return {
    company: text("company"),
    domain: text("domain") || null,
    city: text("city"),
    what: text("what"),
    scale: text("scale"),
    why: text("why"),
    url: text("url"),
    published: text("published") || null,
    match: match === "domain" || match === "name" || match === "brand" ? match : null,
  };
}

export function useBotResults(filters: BotResultFilters) {
  return useQuery({
    queryKey: ["sales", "bot-results", filters] as const,
    queryFn: async () =>
      (await api.get<BotResults>("/api/sales/bot-results", { params: { limit: 200, ...filters } })).data,
  });
}

function useInvalidate() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: ["sales"] });
}

export interface AcceptNewFirm {
  opportunity_id: number;
  company_id: number;
  company_created: boolean;
  /** Karta miała już otwarte konto w Fabrykach IT: wynik wskazuje istniejące. */
  existed: boolean;
}

export function useAcceptBotResult() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async (id: number) =>
      (await api.post<AcceptNewFirm>(`/api/sales/bot-results/${id}/accept`, {})).data,
    onSuccess: invalidate,
  });
}

export function useRejectBotResult() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async (input: { id: number; reason?: string }) =>
      (await api.post<BotResult>(`/api/sales/bot-results/${input.id}/reject`, { reason: input.reason })).data,
    onSuccess: invalidate,
  });
}
