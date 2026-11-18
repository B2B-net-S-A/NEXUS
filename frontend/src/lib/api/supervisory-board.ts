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

// ── Budżet (R3) ──────────────────────────────────────────────────────────────

export interface BudgetMonthView {
  month: number;
  plan_sales: number | null;
  plan_costs: number | null;
  kind: "actual" | "forecast";
  sales: number | null;
  costs: number | null;
  costs_complete: boolean;
  potential: number | null;
  potential_renewed: number | null;
  business_days: number;
}

export interface BudgetView {
  year: number;
  budget: {
    status: "draft" | "adopted";
    resolution_document_id: number | null;
    note: string | null;
    updated_at: string | null;
  } | null;
  months: BudgetMonthView[];
  realization: number | null;
  realization_months: string[];
  cost_share: number | null;
  contracts: number;
}

export interface BudgetPutBody {
  status: "draft" | "adopted";
  resolution_document_id: number | null;
  note: string | null;
  months: { month: number; sales: number | null; costs: number | null }[];
}

export function useBoardBudget(year: number) {
  return useQuery({
    queryKey: ["supervisory-board", "budget", year] as const,
    queryFn: async () => (await api.get<BudgetView>(`${BASE}/budget/${year}`)).data,
    placeholderData: (previous) => previous,
  });
}

export function useSaveBoardBudget(year: number) {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async (body: BudgetPutBody) =>
      (await api.put<BudgetView>(`${BASE}/budget/${year}`, body)).data,
    onSuccess: invalidate,
  });
}

// ── Analiza finansowa (R4) ───────────────────────────────────────────────────

export type StatementSource = "xml" | "xml_prev" | "manual" | "ledger";

export type StatementAmounts = Record<string, number | null>;

export interface StatementMetrics {
  ebitda: number | null;
  financial_debt: number | null;
  net_debt: number | null;
  current_ratio: number | null;
  quick_ratio: number | null;
  cash_ratio: number | null;
  debt_ratio: number | null;
  equity_ratio: number | null;
  net_debt_ebitda: number | null;
  dso: number | null;
  dpo: number | null;
  ebitda_margin: number | null;
  net_margin: number | null;
  roe: number | null;
  roa: number | null;
}

export interface StatementYear {
  year: number;
  source: StatementSource;
  source_label: string;
  period_start: string | null;
  period_end: string | null;
  document_id: number | null;
  schema_name: string | null;
  note: string | null;
  amounts: StatementAmounts;
  raw_count: number;
  /** Rok z księgi w trakcie: liczba miesięcy od stycznia. */
  partial_months: number | null;
  updated_at: string | null;
  metrics: StatementMetrics;
  growth: { revenue: number | null; ebitda: number | null; net_profit: number | null };
}

export interface RatioNorm {
  label: string;
  formula: string;
  good: [number, number];
}

export interface AnalysisView {
  fields: { key: string; label: string; group: "income" | "assets" | "liabilities" }[];
  norms: Record<string, RatioNorm>;
  defaults: {
    debt_to_ebitda: number;
    factoring_share: number;
    financial_multiple: number;
    financial_range: [number, number];
    strategic_multiple: number;
    strategic_range: [number, number];
  };
  years: StatementYear[];
  expected_years: number[];
}

export interface StatementImportResult {
  year: number;
  fields_found: number;
  fields_total: number;
  raw_count: number;
  previous_year_filled: boolean;
  document_id: number;
}

export function useBoardAnalysis() {
  return useQuery({
    queryKey: [...boardKeys.all, "analysis"] as const,
    queryFn: async () => (await api.get<AnalysisView>(`${BASE}/analysis`)).data,
  });
}

export function useSaveBoardStatement() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async ({ year, amounts, note }: { year: number; amounts: StatementAmounts; note: string | null }) =>
      (await api.put<AnalysisView>(`${BASE}/statements/${year}`, { amounts, note })).data,
    onSuccess: invalidate,
  });
}

export function useDeleteBoardStatement() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async (year: number) => {
      await api.delete(`${BASE}/statements/${year}`);
    },
    onSuccess: invalidate,
  });
}

export function useImportBoardStatement() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async (file: File) => {
      const form = new FormData();
      form.set("file", file);
      return (
        await api.post<StatementImportResult>(`${BASE}/statements/import`, form, {
          headers: { "Content-Type": "multipart/form-data" },
        })
      ).data;
    },
    onSuccess: invalidate,
  });
}

// ── Posiedzenia (R5) ─────────────────────────────────────────────────────────

export type MeetingKind = "meeting" | "remote" | "circular";
export type MeetingStatus = "planned" | "held" | "cancelled";

export const MEETING_KIND_LABELS: Record<MeetingKind, string> = {
  meeting: "Posiedzenie",
  remote: "Zdalnie",
  circular: "Tryb pisemny",
};

export const MEETING_STATUS_LABELS: Record<MeetingStatus, string> = {
  planned: "zaplanowane",
  held: "odbyte",
  cancelled: "odwołane",
};

export interface AgendaItem {
  title: string;
  document_ids: number[];
}

export interface BoardMeeting {
  id: number;
  held_on: string;
  kind: MeetingKind;
  status: MeetingStatus;
  title: string;
  place: string | null;
  agenda: AgendaItem[];
  note: string | null;
  minutes_document_id: number | null;
  pack_frozen_at: string | null;
  has_pack: boolean;
}

export interface MeetingPackDocument {
  id: number;
  category: BoardDocumentCategory;
  organ: BoardOrgan | null;
  number: string | null;
  title: string;
  doc_date: string | null;
  has_file: boolean;
}

/** Zamrożony obraz liczb na dzień wysłania pakietu (kwoty pulpitu i budżetu w mln, sprawozdania w zł). */
export interface MeetingPack {
  version: number;
  as_of: string;
  since: string;
  previous_meeting: { id: number; held_on: string } | null;
  summary: BoardSummary;
  budget: BudgetView;
  statement: StatementYear | null;
  documents: MeetingPackDocument[];
  krs_entries: { number: number; day: string | null; description: string }[];
}

export interface BoardMeetingDetail extends BoardMeeting {
  pack: MeetingPack | null;
}

export type ObligationStatus = "done" | "soon" | "overdue" | "pending";

export interface BoardObligation {
  key: string;
  label: string;
  legal: string;
  due: string;
  done: boolean;
  status: ObligationStatus;
  evidence: string;
}

export interface MeetingsResponse {
  items: BoardMeeting[];
  obligations: BoardObligation[];
}

export interface MeetingBody {
  held_on: string;
  kind: MeetingKind;
  status: MeetingStatus;
  title: string;
  place: string | null;
  agenda: AgendaItem[];
  note: string | null;
  minutes_document_id: number | null;
}

export function useBoardMeetings() {
  return useQuery({
    queryKey: [...boardKeys.all, "meetings"] as const,
    queryFn: async () => (await api.get<MeetingsResponse>(`${BASE}/meetings`)).data,
  });
}

export function useBoardMeeting(id: number | null) {
  return useQuery({
    queryKey: [...boardKeys.all, "meetings", id] as const,
    queryFn: async () => (await api.get<BoardMeetingDetail>(`${BASE}/meetings/${id}`)).data,
    enabled: id !== null,
  });
}

export function useSaveBoardMeeting() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async ({ id, body }: { id: number | null; body: MeetingBody }) =>
      id === null
        ? (await api.post<BoardMeeting>(`${BASE}/meetings`, body)).data
        : (await api.put<BoardMeeting>(`${BASE}/meetings/${id}`, body)).data,
    onSuccess: invalidate,
  });
}

export function useDeleteBoardMeeting() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async (id: number) => {
      await api.delete(`${BASE}/meetings/${id}`);
    },
    onSuccess: invalidate,
  });
}

export function useFreezeMeetingPack() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async (id: number) =>
      (await api.post<BoardMeetingDetail & { notified: number }>(`${BASE}/meetings/${id}/pack`)).data,
    onSuccess: invalidate,
  });
}

// ── Uchwały w trybie pisemnym (R6) ───────────────────────────────────────────

export type VoteChoice = "for" | "against" | "abstain";
export type VoteStatus = "open" | "closed" | "withdrawn";

export const VOTE_CHOICE_LABELS: Record<VoteChoice, string> = {
  for: "Za",
  against: "Przeciw",
  abstain: "Wstrzymuję się",
};

export interface VoteTally {
  members: number;
  voted: number;
  for: number;
  against: number;
  abstain: number;
  quorum: number;
  quorum_met: boolean;
  tie_broken_by_chair: boolean;
  passed: boolean;
}

export interface BoardVote {
  id: number;
  number: string | null;
  title: string;
  draft: string;
  document_id: number | null;
  meeting_id: number | null;
  deadline: string;
  status: VoteStatus;
  accepting: boolean;
  chair_user_id: number | null;
  members: { id: number; name: string; choice: VoteChoice | null }[];
  tally: VoteTally;
  result: VoteTally | null;
  resolution_document_id: number | null;
  my_choice: VoteChoice | null;
  can_vote: boolean;
  /** Po terminie albo gdy zagłosowali wszyscy ze składu. */
  closable: boolean;
  created_at: string | null;
  closed_at: string | null;
}

export interface VotesResponse {
  items: BoardVote[];
  board: { id: number; name: string }[];
  excluded_matters: string[];
}

export interface VoteCreateBody {
  number: string | null;
  title: string;
  draft: string;
  document_id: number | null;
  meeting_id: number | null;
  deadline: string;
  chair_user_id: number | null;
  not_excluded_matter: boolean;
}

export function useBoardVotes() {
  return useQuery({
    queryKey: [...boardKeys.all, "votes"] as const,
    queryFn: async () => (await api.get<VotesResponse>(`${BASE}/votes`)).data,
  });
}

export function useCreateBoardVote() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async (body: VoteCreateBody) => (await api.post<BoardVote>(`${BASE}/votes`, body)).data,
    onSuccess: invalidate,
  });
}

export function useCastBoardBallot() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async ({ id, choice }: { id: number; choice: VoteChoice }) =>
      (await api.post<BoardVote>(`${BASE}/votes/${id}/ballot`, { choice })).data,
    onSuccess: invalidate,
  });
}

export function useCloseBoardVote() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async ({ id, action }: { id: number; action: "close" | "withdraw" }) =>
      (await api.post<BoardVote>(`${BASE}/votes/${id}/${action}`)).data,
    onSuccess: invalidate,
  });
}
