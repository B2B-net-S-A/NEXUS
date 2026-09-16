/**
 * Struktura umów Centrum e-Zdrowia (ticket 09.2026): umowa ramowa = część
 * (cz. I/II/IV/V/VI) → 0..N umów wykonawczych. Konsultant, zamówienie i karta
 * MD są przypisywane do KONKRETNEJ umowy wykonawczej, nie do części.
 *
 * Typy są lustrem `backend/app/schemas/client_executive_contract.py`.
 * Bramka po `isEzdrowieClient(clientId)` (lib/ezdrowie.ts) — u innych
 * klientów backend odpowiada 422 i żaden hook nie powinien tam pytać.
 */

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { isEzdrowieClient } from "@/lib/ezdrowie";

export type ExecutiveContractStatus = "active" | "ended";

export interface ExecutiveContractBrief {
  id: number;
  number: string;
  status: ExecutiveContractStatus;
  framework_contract_id: number;
  /** Część umowy ramowej, pod którą wisi umowa (`cz1`…`cz6`). */
  project_part: string | null;
}

export interface ExecutiveContractRead extends ExecutiveContractBrief {
  notes: string | null;
  consultants_count: number;
  created_at: string | null;
}

/** Umowa ramowa będąca częścią (`project_part` ustawione). */
export interface FrameworkPartRead {
  id: number;
  name: string;
  project_part: string;
  status: string;
  executive_contracts: ExecutiveContractRead[];
}

export interface ContractStructureResponse {
  /** W kolejności części: cz1, cz2, cz4, cz5, cz6. */
  framework_contracts: FrameworkPartRead[];
}

export interface ExecutiveContractCreateInput {
  framework_contract_id: number;
  number: string;
  notes?: string | null;
}

export interface ExecutiveContractUpdateInput {
  number?: string;
  status?: ExecutiveContractStatus;
  notes?: string | null;
}

export interface ExecutiveContractReviewRow {
  contract_id: number;
  candidate: { id: number | null; name: string };
  start_date: string | null;
  bucket: "active" | "planned";
  /** Dotychczasowa część (`project_part`) — tylko informacyjnie. */
  legacy_project_part: string | null;
  representative_order_id: number | null;
  /** Umowa ramowa o tej samej części — WYŁĄCZNIE podświetlenie nagłówka,
   *  nigdy preselekcja (ticket: bez automatycznego przypisania). */
  suggested_framework_contract_id: number | null;
}

export interface ExecutiveContractReviewResponse {
  rows: ExecutiveContractReviewRow[];
  total: number;
}

export interface ExecutiveContractAssignmentInput {
  contract_id: number;
  executive_contract_id: number;
}

export interface ExecutiveContractAssignmentResponse {
  contract_id: number;
  order_id: number;
  executive_contract: ExecutiveContractBrief;
  created_draft: boolean;
}

export const executiveContractsApi = {
  structure: async (clientId: number) =>
    (
      await api.get<ContractStructureResponse>(
        `/api/clients/${clientId}/contract-structure`,
      )
    ).data,
  create: async (clientId: number, payload: ExecutiveContractCreateInput) =>
    (
      await api.post<ExecutiveContractRead>(
        `/api/clients/${clientId}/executive-contracts`,
        payload,
      )
    ).data,
  update: async (
    clientId: number,
    executiveContractId: number,
    payload: ExecutiveContractUpdateInput,
  ) =>
    (
      await api.patch<ExecutiveContractRead>(
        `/api/clients/${clientId}/executive-contracts/${executiveContractId}`,
        payload,
      )
    ).data,
  review: async (clientId: number) =>
    (
      await api.get<ExecutiveContractReviewResponse>(
        `/api/clients/${clientId}/executive-contracts/review`,
      )
    ).data,
  assign: async (clientId: number, payload: ExecutiveContractAssignmentInput) =>
    (
      await api.post<ExecutiveContractAssignmentResponse>(
        `/api/clients/${clientId}/executive-contracts/assignments`,
        payload,
      )
    ).data,
};

export const contractStructureQueryKey = (clientId: number) =>
  ["contract-structure", clientId] as const;

export const executiveContractReviewQueryKey = (clientId: number) =>
  ["executive-contract-review", clientId] as const;

/**
 * Struktura umów klienta. `enabled` tylko dla Centrum e-Zdrowia — u innych
 * klientów backend odpowiada 422, a pusty wynik czytałby się jak brak danych.
 */
export function useContractStructure(clientId: number | null | undefined) {
  return useQuery({
    queryKey: contractStructureQueryKey(clientId ?? 0),
    enabled: isEzdrowieClient(clientId),
    queryFn: () => executiveContractsApi.structure(clientId as number),
    staleTime: 60 * 1000,
  });
}

/** Grupa opcji selektu: nagłówek części + aktywne umowy wykonawcze pod nią. */
export interface ExecutiveContractOptionGroup {
  framework_contract_id: number;
  project_part: string;
  /** Np. „Cz. II — CeZ/145/2025". */
  label: string;
  options: ExecutiveContractBrief[];
}

const ROMAN_BY_PART: Record<string, string> = {
  cz1: "I",
  cz2: "II",
  cz4: "IV",
  cz5: "V",
  cz6: "VI",
};

/** Nagłówek części do filtra i `<optgroup>`: „Cz. II — CeZ/145/2025". */
export function frameworkPartHeader(fc: {
  name: string;
  project_part: string | null;
}): string {
  const roman = fc.project_part ? ROMAN_BY_PART[fc.project_part] : undefined;
  // Nazwa zasiewu ma postać „CeZ/145/2025 – cz. II"; do nagłówka bierzemy
  // numer sprzed myślnika. Ręcznie nazwana umowa bez myślnika idzie w całości.
  const number = fc.name.split(/\s+[–-]\s+/)[0]?.trim() || fc.name;
  return roman ? `Cz. ${roman} — ${number}` : number;
}

/**
 * Opcje selektu umów wykonawczych pogrupowane pod nagłówkami części.
 * Domyślnie tylko `active` (zakończonej umowy nie da się wybrać — backend
 * odmawia 422). Część bez aktywnej umowy wykonawczej NIE ma grupy w selekcie —
 * zgodnie z ticketem nie da się do niej przypisać konsultanta.
 */
export function executiveContractOptionGroups(
  structure: ContractStructureResponse | undefined,
  opts: { includeEnded?: boolean } = {},
): ExecutiveContractOptionGroup[] {
  if (!structure) return [];
  return structure.framework_contracts
    .map((fc) => ({
      framework_contract_id: fc.id,
      project_part: fc.project_part,
      label: frameworkPartHeader(fc),
      options: fc.executive_contracts.filter(
        (ec) => opts.includeEnded || ec.status === "active",
      ),
    }))
    .filter((group) => group.options.length > 0);
}

/**
 * Opcje selektu Z BIEŻĄCĄ umową zamówienia, nawet gdy jest zakończona.
 * Zakończonej umowy nie da się WYBRAĆ (backend 422), ale zamówienie już do
 * niej przypisane musi ją w selekcie pokazać — inaczej select renderował
 * „— uzupełnij —" mimo przypisania, a zapis bez zmiany zdejmował umowę
 * (przegląd adwersarialny 09.2026). Inne zakończone umowy nadal odpadają.
 */
export function executiveContractSelectGroups(
  structure: ContractStructureResponse | undefined,
  currentId: number | null | undefined,
): ExecutiveContractOptionGroup[] {
  return executiveContractOptionGroups(structure, { includeEnded: true })
    .map((group) => ({
      ...group,
      options: group.options.filter(
        (ec) => ec.status === "active" || (currentId != null && ec.id === currentId),
      ),
    }))
    .filter((group) => group.options.length > 0);
}

/** Etykieta opcji selektu — zakończona (tylko bieżąca) z dopiskiem. */
export function executiveContractOptionLabel(ec: ExecutiveContractBrief): string {
  return ec.status === "ended" ? `${ec.number} (zakończona)` : ec.number;
}

/** Hook dla selektów w formularzach zamówień (4 dialogi + karta MD).
 *  `currentId` = umowa już przypisana do edytowanego/przedłużanego
 *  zamówienia — zostaje w opcjach także po zakończeniu. */
export function useExecutiveContractOptions(
  clientId: number | null | undefined,
  currentId: number | null | undefined = null,
) {
  const query = useContractStructure(clientId);
  return {
    ...query,
    groups: executiveContractSelectGroups(query.data, currentId),
  };
}
