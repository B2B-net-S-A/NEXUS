// Sprzedaż → Leady: lista osób z researchu do map decyzyjnych Fabryk IT (10.11.2026).
//
// Lustro `backend/app/api/sales_research_import.py`. Plik nie jest nigdzie
// przechowywany: przegląd odsyła wiersze, a akceptacja wysyła je z powrotem.
// Zapis odświeża wszystko pod kluczem „sales” (lista kont, kolejka, karta szansy)
// oraz liczniki „Kogo znamy”, bo akceptacja zakłada konta nowym firmom.

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";

import { salesKeys } from "./sales";
import type { FactoryClient } from "./sales-factories";

export type ResearchCompanyState =
  | "account"
  | "card"
  | "choose"
  | "no_card"
  | "client"
  | "blocked"
  | "own_company";

export type ResearchConfidence = "confirmed" | "to_verify";

export interface ResearchAccount {
  opportunity_id: number;
  title: string;
  stage_name: string;
  status: string;
  map_total: number;
  map_contacted: number;
}

export interface ResearchCard {
  id: number;
  name: string;
  /** Nazwa karty to dokładnie nazwa z pliku; pozostałe karty to ta sama marka. */
  exact: boolean;
  contacts: number;
  account: ResearchAccount | null;
  /** Konto w lejku jest tylko w archiwum: akceptacja założy nowe. */
  archived_account: boolean;
  client: FactoryClient | null;
  /** Firma „Nie kontaktować”: tej karty nie da się wybrać. */
  blocked: boolean;
  /** `null`: licznika nie udało się policzyć albo karta jest poza skanem. */
  known_current: number | null;
  known_past: number | null;
}

export interface ResearchCompany {
  key: string;
  name: string;
  state: ResearchCompanyState;
  /** Karta wybrana samoczynnie; przy `choose` wskazuje ją człowiek. */
  company_id: number | null;
  cards: ResearchCard[];
  client: FactoryClient | null;
}

export interface ResearchRow {
  line: number;
  company_key: string;
  company: string;
  name: string;
  role_in_company: string | null;
  email: string | null;
  phone: string | null;
  linkedin_url: string | null;
  source_url: string | null;
  domain: string | null;
  notes: string | null;
  confidence: ResearchConfidence;
  decision_level: number;
  /** Pola opcjonalne, które odpadły przy odczycie pliku. */
  warnings: string[];
  /** `on_map`: osoba jest już na mapie; `repeated`: drugi raz w tym pliku. */
  person: "new" | "on_map" | "repeated";
  on_map_opportunity_id: number | null;
}

export interface ResearchPreview {
  companies: ResearchCompany[];
  rows: ResearchRow[];
  skipped: { line: number; reason: string }[];
  /** Skan „Znamy teraz” się nie udał: liczniki są puste, reszta przeglądu działa. */
  known_failed: boolean;
  known_truncated: boolean;
  /** „Cognism” dla eksportu z Cognism; zwykła lista z researchu nie ma wartości. */
  origin?: string | null;
}

/** Wiersz przeglądu odesłany do zapisu, z poziomem i kartą wskazanymi na ekranie. */
export type ResearchPersonInput = Pick<
  ResearchRow,
  | "line"
  | "company"
  | "name"
  | "role_in_company"
  | "email"
  | "phone"
  | "linkedin_url"
  | "source_url"
  | "domain"
  | "notes"
  | "confidence"
  | "decision_level"
> & {
  /** `null`: jedyna karta o tej nazwie albo nowa karta, gdy żadnej nie ma. */
  company_id: number | null;
};

export interface ResearchAcceptInput {
  source_label: string;
  owner_user_id: number | null;
  people: ResearchPersonInput[];
}

export type ResearchResult =
  | "added"
  | "on_map"
  | "client"
  | "blocked"
  | "own_company"
  | "choose_card"
  | "card_missing"
  | "error";

export interface ResearchOutcome {
  line: number;
  result: ResearchResult;
  detail: string | null;
  company_id: number | null;
  opportunity_id: number | null;
  created_company: boolean;
  created_account: boolean;
  client: FactoryClient | null;
}

export interface ResearchAccepted {
  outcomes: ResearchOutcome[];
  added: number;
  created_companies: number;
  created_accounts: number;
}

const URL = "/api/sales/it-factories/research-import";

export function usePreviewResearchList() {
  return useMutation({
    mutationFn: async (file: File) => {
      const form = new FormData();
      form.append("file", file);
      return (
        await api.post<ResearchPreview>(`${URL}/preview`, form, {
          headers: { "Content-Type": "multipart/form-data" },
        })
      ).data;
    },
  });
}

export function useAcceptResearchPeople() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: ResearchAcceptInput) =>
      (await api.post<ResearchAccepted>(`${URL}/people`, input)).data,
    onSuccess: (data) => {
      void queryClient.invalidateQueries({ queryKey: salesKeys.all });
      if (data.created_accounts > 0) {
        void queryClient.invalidateQueries({ queryKey: ["it-factories-known-people"] });
      }
    },
  });
}
