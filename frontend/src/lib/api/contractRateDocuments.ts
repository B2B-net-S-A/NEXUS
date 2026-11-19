// Stawka Partnera z umów i aneksów kontraktu (0739).
//
// Backend: `services/contract_rate_documents`. Każdy plik umowy i aneksu czyta
// model, a kod liczy różnicę z harmonogramem stawki kandydata. Kwoty i cytat
// przychodzą tylko pod bramką kwot kontraktu (`amounts_visible`).

import { api } from "@/lib/api";

export interface RateDocumentStep {
  from: string | null;
  to: string | null;
  rate?: number;
  nexus_rate?: number | null;
  condition?: string | null;
}

export interface RateDocumentItem {
  id: number;
  document_id: number;
  filename: string | null;
  kind: "contract" | "annex" | "termination" | "other" | null;
  document_date: string | null;
  category: "auto" | "review" | null;
  reasons: string[];
  decision: "applied" | "auto_applied" | "dismissed" | "undone" | null;
  decided_at: string | null;
  undo_until: string | null;
  read_at: string | null;
  steps: RateDocumentStep[];
  quote: string | null;
}

export interface RateDocumentList {
  items: RateDocumentItem[];
  amounts_visible: boolean;
  /** „Wprowadź” i „Cofnij”: zmiana kwot albo Delivery Lead tego klienta (liczy serwer). */
  can_apply: boolean;
}

/** Wiersz listy kontraktów: pierwszy krok otwartej różnicy (redagowany z kwotami). */
export interface RateDocumentChange {
  from: string;
  rate: number | null;
  kind: string | null;
  category: "auto" | "review" | null;
  count: number;
}

export type RateDocumentAction = "apply" | "dismiss" | "undo";

export async function fetchContractRateDocuments(
  contractId: number,
): Promise<RateDocumentList> {
  const { data } = await api.get<RateDocumentList>(
    `/api/contracts/${contractId}/rate-documents`,
  );
  return data;
}

export async function decideContractRateDocument(
  contractId: number,
  readId: number,
  action: RateDocumentAction,
): Promise<RateDocumentItem> {
  const { data } = await api.post<RateDocumentItem>(
    `/api/contracts/${contractId}/rate-documents/${readId}/${action}`,
  );
  return data;
}
