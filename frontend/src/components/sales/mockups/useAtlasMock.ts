"use client";

import { useQuery } from "@tanstack/react-query";

/**
 * MAKIETA (28.10.2026): dane z `custom_fields.atlas`, których API Sprzedaży
 * dziś nie zwraca. Pliki leżą w `public/__mock__/` (wykluczone z gita),
 * wyliczone zapytaniem read-only z kopii produkcji na stagingu.
 */
export interface DecisionMapEntry {
  name: string;
  role_in_company?: string | null;
  our_role?: string | null;
  decision_level?: number | null;
  contact_status?: string | null;
  last_contact_at?: string | null;
  notes?: string | null;
  email?: string | null;
  phone?: string | null;
  contact_id?: string | null;
}

export interface ItFactory {
  decision_map?: DecisionMapEntry[];
  purchasing_process?: {
    description?: string | null;
    decision_cycle_months?: number | null;
    rfp_frequency?: string | null;
    vendor_entry_requirements?: string | null;
    milestones?: Record<string, string | null>;
  };
  next_step?: string | null;
  next_step_due?: string | null;
  updated_at?: string | null;
}

interface OppMotion {
  it_factory?: ItFactory | null;
  products?: string[] | null;
}

interface OppMotionFile {
  opportunities: Record<string, OppMotion>;
  contacts: Record<string, number> | null;
}

export function useOppMotionMock() {
  return useQuery({
    queryKey: ["mock", "opp-motion"],
    queryFn: async (): Promise<OppMotionFile> => (await fetch("/__mock__/opp-motion.json")).json(),
    staleTime: Infinity,
  });
}

export function useCompanyOwnersMock() {
  return useQuery({
    queryKey: ["mock", "company-owners"],
    queryFn: async (): Promise<Record<string, string>> =>
      (await fetch("/__mock__/company-owners.json")).json(),
    staleTime: Infinity,
  });
}

interface OwnersFile {
  accounts: { id: number; name: string; companies: number }[];
  historical: { name: string; companies: number }[];
  review: number;
  archived: number;
}

export function useOwnersMock() {
  return useQuery({
    queryKey: ["mock", "owners"],
    queryFn: async (): Promise<OwnersFile> => (await fetch("/__mock__/owners.json")).json(),
    staleTime: Infinity,
  });
}
