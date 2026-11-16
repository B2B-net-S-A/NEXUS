// Archiwum dokumentów z eBI24 (E5) — lustro `backend/app/api/finance_archive.py`
// (`/api/finance/archive-ebi24`). Kwoty jako tekst dziesiętny z kropką.

import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";

const BASE = "/api/finance/archive-ebi24";

export type ArchiveKind = "sale" | "cost" | "other";

export interface ArchiveDocument {
  id: number;
  source_id: string;
  kind: ArchiveKind;
  kind_label: string;
  schema_name: string;
  invoice_number: string | null;
  issue_date: string | null;
  due_date: string | null;
  partner_name: string | null;
  partner_id: string | null;
  currency: string | null;
  net: string | null;
  gross: string | null;
  gross_pln: string | null;
  paid: boolean | null;
  ksef_number: string | null;
  folder: string | null;
  file_type: "ebi" | "pdf" | "html" | "xml" | "image" | "other";
  file_name: string | null;
  file_size: number;
}

export interface ArchiveSummary {
  total: number;
  years: { year: string; sale: number; cost: number; other: number }[];
  last_import_at: string | null;
}

export interface ArchiveFilters {
  q: string;
  kind: ArchiveKind | "";
  year: string;
  month: string;
  page: number;
}

export const PAGE_SIZE = 50;

export const archivePaths = {
  file: (id: number) => `${BASE}/${id}/file`,
};

export function useArchiveSummary() {
  return useQuery({
    queryKey: ["finance-archive", "summary"],
    queryFn: async () => (await api.get<ArchiveSummary>(`${BASE}/summary`)).data,
  });
}

export function useArchiveList(filters: ArchiveFilters) {
  return useQuery({
    queryKey: ["finance-archive", "list", filters],
    queryFn: async () =>
      (
        await api.get<{ total: number; documents: ArchiveDocument[] }>(BASE, {
          params: {
            ...(filters.q.trim() ? { q: filters.q.trim() } : {}),
            ...(filters.kind ? { kind: filters.kind } : {}),
            ...(filters.year ? { year: Number(filters.year) } : {}),
            ...(filters.year && filters.month ? { month: Number(filters.month) } : {}),
            limit: PAGE_SIZE,
            offset: filters.page * PAGE_SIZE,
          },
        })
      ).data,
    placeholderData: keepPreviousData,
  });
}
