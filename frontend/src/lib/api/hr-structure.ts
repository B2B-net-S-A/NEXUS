// „Ludzie → Struktura” (etap 2, D4 i D7, 17.10.2026) — kto komu podlega.
//
// Lustro `backend/app/api/hr_structure.py`. Serwer oddaje płaską listę kartotek
// (drzewo układa `components/hr/structure/structure-tree.ts`), zmianę
// przełożonego wielu osób naraz (od razu, bez daty „od kiedy”), piony firmy
// z headami i podpowiedzi: rozjazd z Microsoft 365, „przełożony = head pionu”.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type { Division, EmploymentStatus, EmploymentType } from "@/lib/api/hr";

export const DIVISION_LABELS: Record<Division, string> = {
  front_office: "Front office",
  back_office: "Back office",
};

/** Forma przy osobie (Struktura, Mój zespół). */
export const EMPLOYMENT_TYPE_SHORT: Record<EmploymentType, string> = {
  uop: "UoP",
  b2b: "B2B",
  zlecenie: "Zlecenie",
};

export interface ManagerWords {
  /** „przełożony”, „koordynator”, „przełożony lub koordynator”. */
  one: string;
  /** Dopełniacz: „przełożonego”, „koordynatora”, … */
  ofOne: string;
}

const SUPERVISOR: ManagerWords = { one: "przełożony", ofOne: "przełożonego" };
const COORDINATOR: ManagerWords = { one: "koordynator", ofOne: "koordynatora" };
const MIXED: ManagerWords = {
  one: "przełożony lub koordynator",
  ofOne: "przełożonego lub koordynatora",
};

/**
 * Słowo zamiast „przełożony” (decyzja Artura 17.10.2026): przy B2B i zleceniu
 * „koordynator”, przy UoP „przełożony”. Tylko etykieta — w bazie to dalej
 * `manager_user_id`. Zbiór mieszany i pusty dostaje oba słowa.
 */
export function managerWords(types: readonly (EmploymentType | null | undefined)[]): ManagerWords {
  const known = types.filter((type): type is EmploymentType => Boolean(type));
  if (known.length === 0) return MIXED;
  if (known.every((type) => type === "uop")) return SUPERVISOR;
  if (known.every((type) => type !== "uop")) return COORDINATOR;
  return MIXED;
}

export type ManagerState = "none" | "ok" | "no_profile" | "inactive";

export interface StructureLeaving {
  case_id: number;
  status: "draft" | "active";
  last_working_day: string;
  reports_receiver_user_id: number | null;
  reports_receiver_name: string | null;
  reports_handover_status: "planned" | "done" | "failed" | null;
}

export interface StructureM365Hint {
  upn: string;
  user_id: number | null;
  name: string | null;
  can_accept: boolean;
}

export interface StructurePerson {
  user_id: number;
  name: string;
  email: string;
  job_title: string | null;
  department: string | null;
  employment_type: EmploymentType;
  employment_status: EmploymentStatus;
  division: Division | null;
  manager_user_id: number | null;
  manager_name: string | null;
  manager_state: ManagerState;
  reports: number;
  leaving: StructureLeaving | null;
  m365_hint: StructureM365Hint | null;
  suggested_manager: { user_id: number; name: string } | null;
}

export interface StructureDivision {
  key: Division;
  label: string;
  head_user_id: number | null;
  head_name: string | null;
  head_active: boolean;
}

export interface OutsideManager {
  user_id: number;
  name: string | null;
  state: ManagerState;
  reports: number;
}

export interface HrStructure {
  people: StructurePerson[];
  outside_managers: OutsideManager[];
  divisions: StructureDivision[];
  total: number;
  without_manager: number;
  inactive_manager: number;
  m365_mismatches: number;
}

export interface ChangeResult {
  changed: number[];
  unchanged: number[];
}

const BASE = "/api/hr/structure";

export const structureKeys = {
  all: ["hr", "structure"] as const,
};

export function useHrStructure(enabled = true) {
  return useQuery({
    queryKey: structureKeys.all,
    queryFn: async () => (await api.get<HrStructure>(BASE)).data,
    enabled,
  });
}

function useInvalidateHr() {
  const queryClient = useQueryClient();
  // Przełożony zmienia kartotekę, „Mój zespół”, akceptacje i stan `/api/hr/config`.
  return () => queryClient.invalidateQueries({ queryKey: ["hr"] });
}

export function useReassignManager() {
  const invalidate = useInvalidateHr();
  return useMutation({
    mutationFn: async (payload: { user_ids: number[]; manager_user_id: number | null }) =>
      (await api.post<ChangeResult>(`${BASE}/reassign`, payload)).data,
    onSuccess: invalidate,
  });
}

export function useSetDivision() {
  const invalidate = useInvalidateHr();
  return useMutation({
    mutationFn: async (payload: { user_ids: number[]; division: Division | null }) =>
      (await api.post<ChangeResult>(`${BASE}/division`, payload)).data,
    onSuccess: invalidate,
  });
}

export function useSetDivisionHeads() {
  const invalidate = useInvalidateHr();
  return useMutation({
    mutationFn: async (heads: Partial<Record<Division, number | null>>) =>
      (
        await api.put<{ heads: Record<Division, number | null> }>(`${BASE}/divisions`, heads)
      ).data.heads,
    onSuccess: invalidate,
  });
}
