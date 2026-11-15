// Cennik umowy ramowej klienta, dopłaty za technologie i kategoria na kontrakcie
// (F1, 15.11.2026). Backend: `app/api/framework_rates.py`.
//
// Dopłata NIE zmienia zamówienia (COA) ani stawki przychodowej — podnosi tylko
// limit z umowy ramowej (decyzja Artura z 15.11.2026). Kwoty widzi DL swojego
// klienta i Finanse; 403 dla pozostałych, więc wołający pyta za `enabled`.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";

export interface FrameworkCard {
  id: number;
  label: string;
  role: string;
  seniority: string | null;
  rate_max: number | null;
  valid_from: string | null;
  valid_to: string | null;
  /** „Kafka 20%” — dopłaty dozwolone w tej kategorii. */
  addons: string[];
}

export interface FrameworkAdder {
  id: number;
  technology: string;
  percent: string;
  eligible: { role: string; seniority: string | null }[];
  valid_from: string | null;
  valid_to: string | null;
  notes: string | null;
}

export interface FrameworkTerms {
  client_id: number;
  cards: FrameworkCard[];
  adders: FrameworkAdder[];
}

export type FrameworkStatus = "in" | "in_addon" | "over" | "no_limit";

export interface FrameworkCategory {
  contract_id: number;
  client_id: number;
  rate_client: string | null;
  framework_limit: string | null;
  gap: string | null;
  status: FrameworkStatus;
  card: FrameworkCard | null;
  source: "coa" | "dl" | null;
  coa_label: string | null;
  addon: {
    technology: string;
    percent: string;
    confirmed_by: string | null;
    confirmed_on: string | null;
    evidence: string | null;
  } | null;
  cards: FrameworkCard[];
}

export interface FrameworkCategoryInput {
  rate_card_id: number;
  addon_technology: string | null;
  confirmed_by: string | null;
  confirmed_on: string | null;
  evidence: string | null;
  effective_from: string | null;
}

export interface FrameworkImportResult {
  applied: boolean;
  rates: { label: string; rate: string; action: "create" | "update" | "unchanged" }[];
  adders: { technology: string; percent: string; eligible: string[]; action: "create" | "update" | "unchanged" }[];
  warnings: string[];
}

export interface FrameworkRecomputeRow {
  contract_id: number;
  outcome: string;
  coa_label: string | null;
  category_before: string | null;
  category_after: string | null;
  limit_before: string | null;
  limit_after: string | null;
}

export interface FrameworkRecomputeResult {
  rows: FrameworkRecomputeRow[];
  next_after_id: number | null;
}

export const frameworkKeys = {
  terms: (clientId: number) => ["framework-terms", clientId] as const,
  category: (contractId: number) => ["framework-category", contractId] as const,
};

/** „Kafka 20%” z listy dopłat karty → technologia („Kafka”). */
export function addonTechnology(label: string): string {
  return label.replace(/\s+\d+(?:[.,]\d+)?%$/, "");
}

export function useFrameworkTerms(clientId: number, enabled: boolean) {
  return useQuery({
    queryKey: frameworkKeys.terms(clientId),
    queryFn: async () => (await api.get<FrameworkTerms>(`/api/clients/${clientId}/framework-terms`)).data,
    enabled,
  });
}

export function useFrameworkCategory(contractId: number, enabled: boolean) {
  return useQuery({
    queryKey: frameworkKeys.category(contractId),
    queryFn: async () =>
      (await api.get<FrameworkCategory>(`/api/contracts/${contractId}/framework-category`)).data,
    enabled,
  });
}

export function useSaveFrameworkCategory(contractId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: FrameworkCategoryInput) =>
      (await api.put<FrameworkCategory>(`/api/contracts/${contractId}/framework-category`, input)).data,
    onSuccess: (data) => {
      queryClient.setQueryData(frameworkKeys.category(contractId), data);
      void queryClient.invalidateQueries({ queryKey: ["contract", String(contractId)] });
      void queryClient.invalidateQueries({ queryKey: ["contract", contractId] });
    },
  });
}

export async function importFrameworkTerms(
  clientId: number,
  file: File,
  apply: boolean,
  validFrom: string | null,
): Promise<FrameworkImportResult> {
  const form = new FormData();
  form.append("file", file);
  form.append("apply", apply ? "true" : "false");
  if (validFrom) form.append("valid_from", validFrom);
  // Bez jawnego multipartu axios zserializowałby FormData do JSON-a (422).
  return (
    await api.post<FrameworkImportResult>(`/api/clients/${clientId}/framework-terms/import`, form, {
      headers: { "Content-Type": "multipart/form-data" },
    })
  ).data;
}

export async function recomputeFrameworkCategories(
  clientId: number,
  afterId: number,
  apply: boolean,
): Promise<FrameworkRecomputeResult> {
  return (
    await api.post<FrameworkRecomputeResult>(
      `/api/clients/${clientId}/framework-categories/recompute`,
      null,
      { params: { after_id: afterId, apply } },
    )
  ).data;
}
