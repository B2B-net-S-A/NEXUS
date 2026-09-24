/**
 * Generator dokumentów pochodnych umowy B2B: aneksy, rozwiązania, umowa
 * przedwstępna. Lustro `backend/app/api/b2b_documents.py` (prefiks
 * `/api/b2b-generator`). Definicje typów i pól przychodzą z serwera
 * (`GET /document-types`) — front buduje z nich jeden formularz, zamiast
 * dziesięciu ręcznych.
 *
 * Pola `sensitive` (PESEL, dowód, adres zamieszkania) serwer przyjmuje
 * w żądaniu i wkłada WYŁĄCZNIE do pliku — nie zapisuje ich. Ponowne pobranie
 * takiego dokumentu wymaga podania ich jeszcze raz (`redownload`).
 */

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";

export type DocumentFamily = "annex" | "termination" | "preliminary";
export type DocumentParentKind = "b2b" | "mandate" | "none";
export type DocumentFieldKind =
  | "text"
  | "textarea"
  | "date"
  | "money"
  | "bool"
  | "select"
  | "email"
  | "gender";
export type DocumentFieldGroup = "document" | "partner" | "base";
export type DocumentValue = string | number | boolean | null;
export type DocumentValues = Record<string, DocumentValue>;

export interface DocumentFieldDef {
  key: string;
  label: string;
  kind: DocumentFieldKind;
  required: boolean;
  sensitive: boolean;
  help: string | null;
  options: [string, string][];
  /** Pole widoczne tylko, gdy `values[klucz] === wartość`. */
  show_if: [string, DocumentValue] | null;
  group: DocumentFieldGroup;
}

export interface DocumentTypeDef {
  key: string;
  label: string;
  family: DocumentFamily;
  languages: string[];
  parent: DocumentParentKind;
  fields: DocumentFieldDef[];
  effect_label: string;
  description: string;
  signatories: "both" | "company" | "partner_and_company";
  uses_refs: boolean;
}

export interface DocumentTypesResponse {
  types: DocumentTypeDef[];
  ref_labels: Record<string, string>;
  ref_defaults: Record<string, string>;
}

export interface DocumentBaseInfo {
  contract_number: string | null;
  signing_date: string | null;
  start_date: string | null;
  start_date_mode: string | null;
  client_name: string | null;
  client_legal_name: string | null;
  currency: string | null;
  template_version: string | null;
}

export interface DocumentPrefill {
  values: DocumentValues;
  base: DocumentBaseInfo;
  needs_refs: boolean;
  ref_defaults: Record<string, string>;
  languages: string[];
  default_language: string;
}

export interface DocumentRequestBody {
  document_type: string;
  language: string;
  parent_generated_contract_id?: number | null;
  candidate_id?: number | null;
  job_id?: number | null;
  values: DocumentValues;
  refs?: Record<string, string> | null;
}

export type DocumentStatus = "issued" | "signed" | "cancelled";
export type DocumentStatusFilter = DocumentStatus | "unsigned";

export interface DocumentItem {
  id: number;
  document_type: string;
  type_label: string;
  family: DocumentFamily;
  language: string;
  label: string;
  document_date: string;
  parent_generated_contract_id: number | null;
  parent_contract_number: string | null;
  contract_id: number | null;
  candidate_id: number | null;
  partner_name: string | null;
  client_name: string | null;
  status: DocumentStatus;
  signature_status: "unsigned" | "signed_both" | string;
  signed_at: string | null;
  effect_applied_at: string | null;
  effect_summary: Record<string, unknown> | null;
  created_by_name: string | null;
  created_at: string | null;
  requires_sensitive_input: boolean;
  sensitive_fields: string[];
  can_edit: boolean;
  can_delete: boolean;
  can_confirm_signed: boolean;
  cancelled_reason: string | null;
}

export interface DocumentForm {
  id: number;
  document_type: string;
  language: string;
  parent_generated_contract_id: number | null;
  candidate_id: number | null;
  job_id: number | null;
  values: DocumentValues;
  refs: Record<string, string> | null;
  base: Partial<DocumentBaseInfo>;
  sensitive_fields: string[];
}

export interface DocumentEffects {
  effect_label: string;
  changes: string[];
  warnings: string[];
  blockers: string[];
}

export interface DocumentListParams {
  parentGeneratedContractId?: number;
  documentType?: string;
  status?: DocumentStatusFilter;
  q?: string;
  limit?: number;
  offset?: number;
}

export interface PartnerNoticeBody {
  parent_generated_contract_id: number;
  delivered_on: string;
  termination_date?: string | null;
}

export interface PartnerNoticeResult {
  type: "partner_notice";
  delivered_on: string;
  termination_date: string;
  contract_id?: number;
}

/** Rozmiar strony listy dokumentów („Pokaż więcej”). */
export const B2B_DOCUMENTS_PAGE_SIZE = 50;

/** Prefiks kluczy react-query listy dokumentów (unieważnianie po zmianie). */
export const B2B_DOCUMENTS_KEY = "b2b-documents" as const;

export const b2bDocumentsKeys = {
  types: () => ["b2b-document-types"] as const,
  list: (filters: {
    documentType: string;
    status: string;
    q: string;
  }) =>
    [
      B2B_DOCUMENTS_KEY,
      "list",
      filters.documentType,
      filters.status,
      filters.q,
    ] as const,
  prefill: (
    documentType: string,
    parentId: number | null,
    candidateId: number | null,
    jobId: number | null = null,
  ) =>
    [
      B2B_DOCUMENTS_KEY,
      "prefill",
      documentType,
      parentId ?? 0,
      candidateId ?? 0,
      jobId ?? 0,
    ] as const,
  effects: (id: number) => [B2B_DOCUMENTS_KEY, "effects", id] as const,
};

export const b2bDocumentsApi = {
  types: () =>
    api
      .get<DocumentTypesResponse>("/api/b2b-generator/document-types")
      .then((r) => r.data),
  prefill: (params: {
    documentType: string;
    parentGeneratedContractId?: number | null;
    candidateId?: number | null;
    /** Wymagane przy kandydacie bez umowy bazowej — dostęp idzie przez rekrutację. */
    jobId?: number | null;
  }) =>
    api
      .get<DocumentPrefill>("/api/b2b-generator/documents/prefill", {
        params: {
          document_type: params.documentType,
          ...(params.parentGeneratedContractId
            ? { parent_generated_contract_id: params.parentGeneratedContractId }
            : {}),
          ...(params.candidateId ? { candidate_id: params.candidateId } : {}),
          ...(params.jobId ? { job_id: params.jobId } : {}),
        },
      })
      .then((r) => r.data),
  preview: (body: DocumentRequestBody) =>
    api
      .post<{ html: string; missing: string[] }>(
        "/api/b2b-generator/documents/preview",
        body,
      )
      .then((r) => r.data),
  /** DOCX w odpowiedzi; `X-Document-Id` = id zapisanego wiersza. */
  create: (body: DocumentRequestBody) =>
    api.post("/api/b2b-generator/documents", body, { responseType: "blob" }),
  list: (params: DocumentListParams = {}) =>
    api
      .get<DocumentItem[]>("/api/b2b-generator/documents", {
        params: {
          limit: params.limit ?? B2B_DOCUMENTS_PAGE_SIZE,
          ...(params.offset ? { offset: params.offset } : {}),
          ...(params.parentGeneratedContractId
            ? { parent_generated_contract_id: params.parentGeneratedContractId }
            : {}),
          ...(params.documentType ? { document_type: params.documentType } : {}),
          ...(params.status ? { status: params.status } : {}),
          ...(params.q?.trim() ? { q: params.q.trim() } : {}),
        },
      })
      .then((r) => r.data),
  form: (id: number) =>
    api
      .get<DocumentForm>(`/api/b2b-generator/documents/${id}/form`)
      .then((r) => r.data),
  /** Ponowne pobranie; `values` = tylko pola wrażliwe (nie przechowujemy ich). */
  redownload: (id: number, values: DocumentValues = {}) =>
    api.post(
      `/api/b2b-generator/documents/${id}/docx`,
      { values },
      { responseType: "blob" },
    ),
  rerender: (id: number, body: DocumentRequestBody) =>
    api.post(`/api/b2b-generator/documents/${id}/rerender`, body, {
      responseType: "blob",
    }),
  effects: (id: number) =>
    api
      .get<DocumentEffects>(`/api/b2b-generator/documents/${id}/effects`)
      .then((r) => r.data),
  confirmSigned: (id: number) =>
    api
      .post<DocumentItem>(`/api/b2b-generator/documents/${id}/confirm-signed`)
      .then((r) => r.data),
  cancel: (id: number, reason: string) =>
    api
      .post<DocumentItem>(`/api/b2b-generator/documents/${id}/cancel`, {
        reason,
      })
      .then((r) => r.data),
  remove: (id: number) =>
    api.delete(`/api/b2b-generator/documents/${id}`).then(() => undefined),
  partnerNotice: (body: PartnerNoticeBody) =>
    api
      .post<PartnerNoticeResult>(
        "/api/b2b-generator/documents/partner-notice",
        body,
      )
      .then((r) => r.data),
  // Kandydat i rekrutacja umowy przedwstępnej — te same trasy, z których
  // korzysta formularz Generatora Umów (bramka generatora, nie listy kandydatów).
  searchCandidates: (q: string) =>
    api
      .get<DocumentCandidateOption[]>("/api/cv-generator/candidates", {
        params: { q, limit: 20 },
      })
      .then((r) => r.data),
  candidateRecruitments: (candidateId: number) =>
    api
      .get<DocumentRecruitmentOption[]>(
        `/api/cv-generator/candidates/${candidateId}/recruitments`,
      )
      .then((r) => r.data),
  /** Imię i nazwisko osoby z kontraktu — do znalezienia umowy w rejestrze. */
  contractCandidateName: (contractId: number) =>
    api
      .get<{ candidate_name?: string | null }>(`/api/contracts/${contractId}`)
      .then((r) => r.data.candidate_name ?? null),
};

export interface DocumentCandidateOption {
  id: number;
  name: string;
  lastname: string;
  full_name: string;
  email?: string | null;
}

export interface DocumentRecruitmentOption {
  stage_id: number;
  job_id: number;
  job_title: string;
  stage: string;
}

/** Definicje typów — stałe dla wdrożenia, więc długo w cache. */
export function useDocumentTypes() {
  return useQuery({
    queryKey: b2bDocumentsKeys.types(),
    queryFn: b2bDocumentsApi.types,
    staleTime: 10 * 60_000,
  });
}
