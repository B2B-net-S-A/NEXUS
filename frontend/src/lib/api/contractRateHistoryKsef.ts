// Historia stawek kontraktu z faktur KSeF (0781).
//
// Backend: `services/contract_rate_history`. Reguła porównuje cenę z faktur
// sprzedaży i netto faktur konsultanta ÷ godziny z harmonogramem kontraktu.
// Kwoty i skutek przychodzą tylko pod bramką kwot kontraktu (`amounts_visible`).

import { api } from "@/lib/api";

export type RateHistoryLeg = "client" | "cost";

export interface RateHistoryStep {
  leg: RateHistoryLeg;
  from: string;
  months: string[];
  evidence: string[];
  reasons: string[];
  /** Krok od startu kontraktu z dotychczasową stawką (bez niego miesiące przed historią zmieniłyby stawkę). */
  baseline: boolean;
  rate?: number;
  nexus_rate?: number | null;
  impact?: number;
}

export type RateHistoryCategory =
  | "brak_historii"
  | "rozjazd_biezacy"
  | "rozjazd_w_przeszlosci"
  | "zgodne";

export interface RateHistoryItem {
  id: number;
  contract_id: number;
  category: RateHistoryCategory;
  automatic: boolean;
  status: "open" | "auto_applied" | "applied" | "dismissed" | "undone" | "resolved";
  reasons: string[];
  decided_at: string | null;
  undo_until: string | null;
  steps: RateHistoryStep[];
}

export interface RateHistoryCard {
  item: RateHistoryItem | null;
  amounts_visible: boolean;
  /** „Wprowadź” i „Cofnij”: zmiana kwot albo Delivery Lead tego klienta (liczy serwer). */
  can_apply: boolean;
}

/** Wiersz listy kontraktów: pierwszy krok podpowiedzi (redagowany z kwotami). */
export interface RateHistoryChange {
  from: string;
  leg: RateHistoryLeg;
  rate: number | null;
  category: RateHistoryCategory;
  count: number;
}

export type RateHistoryAction = "apply" | "dismiss" | "undo";

export async function fetchContractRateHistoryKsef(
  contractId: number,
): Promise<RateHistoryCard> {
  const { data } = await api.get<RateHistoryCard>(
    `/api/contracts/${contractId}/rate-history-ksef`,
  );
  return data;
}

export async function decideContractRateHistoryKsef(
  contractId: number,
  action: RateHistoryAction,
): Promise<RateHistoryItem> {
  const { data } = await api.post<RateHistoryItem>(
    `/api/contracts/${contractId}/rate-history-ksef/${action}`,
  );
  return data;
}
