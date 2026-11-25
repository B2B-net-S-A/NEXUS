// Źródła asystenta prawnego (25.11.2026, część H planu): karta w Przepisach →
// „Źródła i boty”. Lustro `GET /api/legal/sources` (`backend/app/api/legal.py`):
// korpus prawa (akty, wersje, data stanu) i liczniki pozostałych źródeł.
// Bramka trasy: Generator umów B2B za sekcją Sourcing — osoba z dostępem do
// Przepisów bez Generatora dostaje 403 i karta mówi to wprost.

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";

export type LegalActSource = "eli" | "eurlex";
export type LegalFetchStatus = "pending" | "ok" | "failed";

export interface LegalActVersionStatus {
  ident: string;
  valid_from: string;
  published_on: string | null;
  url: string;
  format: string;
  provisions: number;
  vectors: number;
  /** Zmiany ogłoszone po dacie stanu tekstu jednolitego (tekst ich nie obejmuje). */
  amendments_after: { id: string; date: string }[];
}

export interface LegalActStatus {
  key: string;
  short_name: string;
  title: string;
  source: LegalActSource;
  ident: string;
  in_registry: boolean;
  fetch_status: LegalFetchStatus;
  fetch_error: string | null;
  checked_at: string | null;
  versions: number;
  current: LegalActVersionStatus | null;
}

export interface LegalDocumentsStatus {
  case_law: { count: number; latest_fetched_at: string | null };
  templates: { repo: number; client_clauses: number; custom_approved: number };
  framework_contracts: { contracts: number; amendments: number };
}

export interface LegalTemplateReviewStatus {
  open: number;
  last_created_at: string | null;
}

export interface LegalSources {
  acts: LegalActStatus[];
  acts_total: number;
  acts_ready: number;
  provisions_total: number;
  embeddings_enabled: boolean;
  documents: LegalDocumentsStatus;
  template_review: LegalTemplateReviewStatus;
}

export const legalSourcesKey = ["legal", "sources"] as const;

export function useLegalSources() {
  return useQuery({
    queryKey: legalSourcesKey,
    queryFn: async () => (await api.get<LegalSources>("/api/legal/sources")).data,
    staleTime: 5 * 60 * 1000,
  });
}
