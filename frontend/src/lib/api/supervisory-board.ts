// „Rada” (/rada, R1 16.11.2026): dokumenty korporacyjne i odpis KRS spółki.
//
// Lustro `backend/app/api/supervisory_board.py`. Odczyt: Rada nadzorcza
// i admin; zapis (wgranie, poprawka, usunięcie, odczyt modelem, pobranie
// odpisu teraz) tylko admin.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";

const BASE = "/api/supervisory-board";

export type BoardDocumentCategory =
  | "statute"
  | "rules_management"
  | "rules_supervisory"
  | "minutes_general"
  | "minutes_supervisory"
  | "minutes_management"
  | "resolution_general"
  | "resolution_supervisory"
  | "resolution_management"
  | "financial_statement"
  | "other";

export type BoardOrgan = "general" | "supervisory" | "management";

export const CATEGORY_LABELS: Record<BoardDocumentCategory, string> = {
  statute: "Statut (umowa spółki)",
  rules_management: "Regulamin Zarządu",
  rules_supervisory: "Regulamin Rady",
  minutes_general: "Protokoły WZA",
  minutes_supervisory: "Protokoły Rady",
  minutes_management: "Protokoły Zarządu",
  resolution_general: "Uchwały WZA",
  resolution_supervisory: "Uchwały Rady",
  resolution_management: "Uchwały Zarządu",
  financial_statement: "Sprawozdania finansowe",
  other: "Inne",
};

export const ORGAN_LABELS: Record<BoardOrgan, string> = {
  general: "WZA",
  supervisory: "Rada",
  management: "Zarząd",
};

export interface BoardDocumentExtraction {
  version?: string;
  status?: string;
  category?: BoardDocumentCategory | null;
  organ?: BoardOrgan | null;
  number?: string | null;
  doc_date?: string | null;
  subject?: string | null;
  votes?: { for: number | null; against: number | null; abstain: number | null } | null;
}

export interface BoardDocument {
  id: number;
  category: BoardDocumentCategory;
  organ: BoardOrgan | null;
  number: string | null;
  title: string;
  subject: string | null;
  doc_date: string | null;
  source: "upload" | "krs";
  krs_entry_no: number | null;
  krs_entry_date: string | null;
  has_file: boolean;
  file_name: string | null;
  file_size: number | null;
  extraction_status: "none" | "read" | "failed" | "skipped";
  extraction: BoardDocumentExtraction;
  updated_at: string | null;
}

export interface BoardDocumentsResponse {
  categories: { key: BoardDocumentCategory; total: number; without_file: number }[];
  items: BoardDocument[];
}

export type FilingKind = "financial_statement" | "activity_report" | "audit_opinion" | "approval";

export interface KrsSnapshotView {
  krs: string;
  fetched_at: string | null;
  checked_at: string | null;
  name: string | null;
  capital: string | null;
  shares: string | null;
  entries_count: number;
  recent_entries: { number: number; date: string | null; description: string; by_court: boolean }[];
  management: { count: number; functions: string[] };
  supervisory_count: number;
  statute: {
    changes: number;
    last_act_date: string | null;
    last_entry_no: number | null;
    last_text: string | null;
  };
  filings: ({ year: number } & Partial<Record<FilingKind, string>>)[];
  missing_filings: { year: number; missing: FilingKind[] }[];
}

export interface DocumentFields {
  category: BoardDocumentCategory;
  title: string;
  organ?: BoardOrgan | null;
  number?: string | null;
  subject?: string | null;
  doc_date?: string | null;
}

export const boardKeys = {
  krs: ["supervisory-board", "krs"] as const,
  documents: (category: BoardDocumentCategory | null) =>
    ["supervisory-board", "documents", category ?? "all"] as const,
  all: ["supervisory-board"] as const,
};

export function useBoardKrs() {
  return useQuery({
    queryKey: boardKeys.krs,
    queryFn: async () =>
      (await api.get<{ snapshot: KrsSnapshotView | null }>(`${BASE}/krs`)).data,
  });
}

export function useBoardDocuments(category: BoardDocumentCategory | null) {
  return useQuery({
    queryKey: boardKeys.documents(category),
    queryFn: async () =>
      (
        await api.get<BoardDocumentsResponse>(`${BASE}/documents`, {
          params: category ? { category } : undefined,
        })
      ).data,
    placeholderData: (previous) => previous,
  });
}

function useInvalidate() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: boardKeys.all });
}

function toForm(fields: DocumentFields, file?: File | null): FormData {
  const form = new FormData();
  form.set("category", fields.category);
  form.set("title", fields.title);
  if (fields.organ) form.set("organ", fields.organ);
  if (fields.number) form.set("number", fields.number);
  if (fields.subject) form.set("subject", fields.subject);
  if (fields.doc_date) form.set("doc_date", fields.doc_date);
  if (file) form.set("file", file);
  return form;
}

export function useCreateBoardDocument() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async ({ fields, file }: { fields: DocumentFields; file?: File | null }) =>
      (
        await api.post<BoardDocument>(`${BASE}/documents`, toForm(fields, file), {
          headers: { "Content-Type": "multipart/form-data" },
        })
      ).data,
    onSuccess: invalidate,
  });
}

export function useAttachBoardFile() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async ({ id, file }: { id: number; file: File }) => {
      const form = new FormData();
      form.set("file", file);
      return (
        await api.post<BoardDocument>(`${BASE}/documents/${id}/file`, form, {
          headers: { "Content-Type": "multipart/form-data" },
        })
      ).data;
    },
    onSuccess: invalidate,
  });
}

export function useUpdateBoardDocument() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async ({ id, patch }: { id: number; patch: Partial<DocumentFields> }) =>
      (await api.patch<BoardDocument>(`${BASE}/documents/${id}`, patch)).data,
    onSuccess: invalidate,
  });
}

export function useDeleteBoardDocument() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async (id: number) => {
      await api.delete(`${BASE}/documents/${id}`);
    },
    onSuccess: invalidate,
  });
}

export function useReadBoardDocument() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async (id: number) =>
      (await api.post<BoardDocument>(`${BASE}/documents/${id}/read`)).data,
    onSuccess: invalidate,
  });
}

export function useRefreshBoardKrs() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async () =>
      (
        await api.post<{
          changed: boolean;
          new_entries: number;
          documents_created: number;
          snapshot: KrsSnapshotView | null;
        }>(`${BASE}/krs/refresh`)
      ).data,
    onSuccess: invalidate,
  });
}

export function boardDocumentFilePath(id: number): string {
  return `${BASE}/documents/${id}/file`;
}

// ── Pulpit (R2) ──────────────────────────────────────────────────────────────

export interface BoardYear {
  year: number;
  sales: number | null;
  costs: number | null;
  result: number | null;
  result_pct: number | null;
  complete: boolean;
  /** Rok bieżący: wynik tylko z miesięcy z pełnymi kosztami (I–n). */
  result_months?: number;
}

export interface BoardSummary {
  source: { kind: "invoices"; first_date: string | null; last_date: string | null };
  years: BoardYear[];
  months: { year: number; month: number; sales: number | null; costs: number | null; costs_complete: boolean }[];
  ytd: {
    sales_months: number;
    sales?: number | null;
    sales_previous?: number | null;
    result_months: number;
    result?: number | null;
    result_pct?: number | null;
    result_previous?: number | null;
    result_previous_pct?: number | null;
  };
  top_clients: { year: number; items: { name: string; sales: number | null; share: number }[] };
  orders: {
    active: number;
    ending: number;
    potential_month: number | null;
    ending_potential_month: number | null;
    without_rate: number;
    year_end: string;
  };
  krs_missing: { year: number; missing: FilingKind[] }[];
  documents_without_file: number;
}

export function useBoardSummary() {
  return useQuery({
    queryKey: ["supervisory-board", "summary"] as const,
    queryFn: async () => (await api.get<BoardSummary>(`${BASE}/summary`)).data,
    staleTime: 5 * 60 * 1000,
  });
}
