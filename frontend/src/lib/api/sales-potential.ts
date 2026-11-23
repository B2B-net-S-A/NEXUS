// Sprzedaż → ocena potencjału firmy i baza wiedzy oceny (decyzja Artura 23.11.2026).
//
// Lustro `backend/app/api/sales_potential.py`. Z wyłączoną flagą
// `SALES_BOT_TASKS_ENABLED` odczyt oceny mówi `enabled: false` i ekrany jej nie
// pokazują. Bieg bota i ocena trwają kilka minut, więc w trakcie zapytanie
// odświeża się samo. Reguły: docs/claude/sprzedaz/ocena-potencjalu.md.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";

const POLL_MS = 20_000;

export type ReferenceKind = "list" | "realizacja" | "logo";
export type PotentialVerdict = "NISKI" | "ŚREDNI" | "WYSOKI";

export interface KnowledgeReference {
  id: string;
  client: string;
  kind: ReferenceKind;
  sectors: string[];
  services: string[];
  scope: string;
  since: string;
  letter_date: string | null;
  valid_until: string | null;
  signed_by: string;
  quote: string;
  public_tender: boolean;
  note: string;
  /** Aktualność listu; `null` dla realizacji i logo. */
  fresh?: boolean | null;
  /** Aktywne kontrakty klienta w NEXUSIE; `null` = takiego klienta nie ma. */
  nexus_active?: number | null;
}

export interface KnowledgeHistory {
  at: string;
  by_name: string;
  summary: string;
}

export interface Knowledge {
  offer: string;
  references: KnowledgeReference[];
  history: KnowledgeHistory[];
  updated_at: string | null;
  can_edit: boolean;
}

export interface ResearchEvent {
  date: string;
  text: string;
  url: string;
  line: string | null;
}

export interface ResearchJob {
  title: string;
  tech: string;
  contract: string;
  published: string | null;
  url: string;
  active: boolean | null;
}

export interface Research {
  pkd?: string | null;
  employees?: string;
  revenue?: string;
  group?: string;
  facts_url?: string | null;
  events?: ResearchEvent[];
  jobs?: ResearchJob[];
  stack?: { text: string; url: string }[];
}

export interface KscTest {
  result: "PRAWDOPODOBNIE TAK" | "MOŻLIWE" | "PRAWDOPODOBNIE NIE";
  entity: "kluczowy" | "ważny" | null;
  sector: string | null;
  why: string;
}

export interface FitLine {
  line: string;
  score: number;
  need: string;
  service: string;
  horizon: string;
}

export interface Assessment {
  verdict: PotentialVerdict;
  summary: string;
  land: { title: string; why: string };
  expand: string[];
  fit: FitLine[];
  references: { id: string; why: string }[];
  questions: { group: string; text: string }[];
  verify: string[];
  risks: string[];
  opening: string;
}

export interface PotentialResult {
  id: number;
  state: "pending" | "ready" | "failed";
  error: string | null;
  created_at: string;
  assessed_at: string | null;
  research: Research;
  ksc: KscTest | null;
  assessment: Assessment | null;
  references: { reference: KnowledgeReference; why: string }[];
}

export interface Potential {
  enabled: boolean;
  lines: Record<string, string>;
  run: { id: number; status: string; started_at: string } | null;
  result: PotentialResult | null;
}

export const potentialKeys = {
  company: (companyId: number) => ["sales", "potential", companyId] as const,
  knowledge: ["sales", "potential-knowledge"] as const,
};

/** Bieg bota albo ocena modelu wciąż trwają. */
export function potentialInProgress(data: Potential | undefined): boolean {
  if (!data) return false;
  return data.run?.status === "started" || data.result?.state === "pending";
}

export function useCompanyPotential(companyId: number, enabled = true) {
  return useQuery({
    queryKey: potentialKeys.company(companyId),
    queryFn: async () =>
      (await api.get<Potential>(`/api/sales/companies/${companyId}/potential`)).data,
    enabled: enabled && Number.isFinite(companyId) && companyId > 0,
    refetchInterval: (query) => (potentialInProgress(query.state.data) ? POLL_MS : false),
  });
}

export function useStartPotential(companyId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () =>
      (await api.post<Potential>(`/api/sales/companies/${companyId}/potential`)).data,
    onSuccess: (data) => queryClient.setQueryData(potentialKeys.company(companyId), data),
  });
}

export function useKnowledge() {
  return useQuery({
    queryKey: potentialKeys.knowledge,
    queryFn: async () => (await api.get<Knowledge>("/api/sales/potential-knowledge")).data,
  });
}

export type KnowledgeReferenceIn = Omit<KnowledgeReference, "fresh" | "nexus_active">;

export function toReferenceIn(ref: KnowledgeReference): KnowledgeReferenceIn {
  const { fresh: _fresh, nexus_active: _active, ...rest } = ref;
  return rest;
}

export function useSaveKnowledge() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: { offer: string; references: KnowledgeReferenceIn[] }) =>
      (await api.put<Knowledge>("/api/sales/potential-knowledge", body)).data,
    onSuccess: (data) => queryClient.setQueryData(potentialKeys.knowledge, data),
  });
}

export function useParseReferenceTable() {
  return useMutation({
    mutationFn: async (text: string) =>
      (
        await api.post<{ references: KnowledgeReference[] }>(
          "/api/sales/potential-knowledge/parse-table",
          { text },
        )
      ).data.references,
  });
}
