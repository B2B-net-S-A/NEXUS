/**
 * Wzory własne Generatora Umów B2B (asystent prawny, część B, 25.11.2026).
 * Lustro `backend/app/api/custom_document_templates.py` (prefiks
 * `/api/b2b-generator/custom-templates`). Zatwierdzone wzory przychodzą też
 * w `GET /document-types` jako `custom_types` (`useDocumentTypes`).
 */

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";

export type CustomFieldKind =
  | "text"
  | "textarea"
  | "date"
  | "money"
  | "bool"
  | "select"
  | "email"
  | "gender"
  | "list";
export type CustomFieldSource = "candidate" | "ceidg" | "clients" | "manual";
export type CustomTemplateKind = "contract" | "preliminary" | "annex" | "letter";
export type CustomVersionStatus = "draft" | "pending" | "approved" | "withdrawn";
export type CustomTemplateOrigin = "base" | "upload" | "brief";

export interface CustomFieldDef {
  key: string;
  label: string;
  kind: CustomFieldKind;
  group: string;
  source: CustomFieldSource;
  source_label: string;
  required: boolean;
  sensitive: boolean;
  help: string | null;
  options: [string, string][];
  item_keys: { key: string; label: string }[];
}

export interface CustomCheck {
  key: string;
  state: "ok" | "warn" | "block";
  text: string;
  cite: string;
  cite_kind: string;
  /** Stan cytatu z weryfikatora asystenta: `unverified` = „do sprawdzenia”. */
  cite_state: "ok" | "missing" | "mismatch" | "unverified";
}

export interface CustomChange {
  op: "replace" | "insert_after" | "delete";
  i: number;
  before: string;
  after: string;
  context: string;
  reason: string;
}

export interface CustomVersion {
  id: number;
  version_no: number;
  status: CustomVersionStatus;
  status_label: string;
  name: string;
  kind: CustomTemplateKind;
  kind_label: string;
  description: string;
  client_scope: "all" | "selected";
  client_ids: number[];
  signatories: "both" | "company" | "partner_and_company";
  signature_form: "any" | "written";
  origin: CustomTemplateOrigin;
  base_key: string | null;
  instruction: string | null;
  ai_used: boolean;
  created_by_name: string | null;
  created_at: string | null;
  submitted_by_name: string | null;
  submitted_at: string | null;
  reviewed_by_name: string | null;
  reviewed_at: string | null;
  review_note: string | null;
  fields: CustomFieldDef[];
  changes?: CustomChange[];
  warnings?: string[];
  checks?: CustomCheck[];
  problems?: string[];
  unused_fields?: string[];
  preview_html?: string;
}

export interface CustomTemplateDetail {
  id: number;
  withdrawn_at: string | null;
  withdrawn_by_name: string | null;
  withdrawn_reason: string | null;
  working: CustomVersion | null;
  active: CustomVersion | null;
  history: CustomVersion[];
  can_edit: boolean;
  can_review: boolean;
  can_withdraw: boolean;
  can_new_version: boolean;
  /** Komunikat po szkicu, gdy asystent nie pomógł (szkic bez zmian). */
  message?: string | null;
}

export interface CustomTemplateRow {
  id: number;
  name: string;
  kind: CustomTemplateKind;
  kind_label: string;
  description: string;
  withdrawn: boolean;
  active_version_no: number | null;
  active_approved_at: string | null;
  working_status: CustomVersionStatus | null;
  working_status_label: string | null;
  working_version_no: number | null;
  author_name: string | null;
}

export interface CustomTemplatesList {
  templates: CustomTemplateRow[];
  is_admin: boolean;
}

/** Zatwierdzony wzór w „Nowy dokument” (`GET /document-types` → `custom_types`). */
export interface CustomDocumentType {
  key: string;
  template_id: number;
  version_id: number;
  version_no: number;
  label: string;
  description: string;
  kind: CustomTemplateKind;
  kind_label: string;
  client_scope: "all" | "selected";
  client_ids: number[];
  signatories: string;
  signature_form: string;
  approved_at: string | null;
  fields: CustomFieldDef[];
}

export interface CustomTemplateBase {
  key: string;
  label: string;
  description: string;
}

export type CustomValue = string | number | boolean | null | Record<string, string>[] | string[];
export type CustomValues = Record<string, CustomValue>;

export interface CustomSettingsBody {
  name?: string;
  description?: string;
  kind?: CustomTemplateKind;
  client_scope?: "all" | "selected";
  client_ids?: number[];
  signatories?: CustomVersion["signatories"];
  signature_form?: CustomVersion["signature_form"];
  fields?: Omit<CustomFieldDef, "source_label">[];
}

export interface CustomDocumentBody {
  values: CustomValues;
  candidate_id?: number | null;
  job_id?: number | null;
  client_id?: number | null;
}

const BASE = "/api/b2b-generator/custom-templates";
/** Klient `api` ma domyślnie JSON — formularz z plikiem musi to nadpisać. */
const MULTIPART = { headers: { "Content-Type": "multipart/form-data" } };

export const CUSTOM_TEMPLATES_KEY = "b2b-custom-templates" as const;

export const customTemplatesKeys = {
  all: () => [CUSTOM_TEMPLATES_KEY] as const,
  list: () => [CUSTOM_TEMPLATES_KEY, "list"] as const,
  bases: () => [CUSTOM_TEMPLATES_KEY, "bases"] as const,
  detail: (id: number) => [CUSTOM_TEMPLATES_KEY, "detail", id] as const,
  prefill: (id: number, candidateId: number | null, jobId: number | null) =>
    [CUSTOM_TEMPLATES_KEY, "prefill", id, candidateId ?? 0, jobId ?? 0] as const,
};

export const customTemplatesApi = {
  bases: () =>
    api
      .get<{ bases: CustomTemplateBase[]; model_available: boolean }>(`${BASE}/bases`)
      .then((r) => r.data),
  list: () => api.get<CustomTemplatesList>(BASE).then((r) => r.data),
  detail: (id: number) => api.get<CustomTemplateDetail>(`${BASE}/${id}`).then((r) => r.data),
  create: (body: {
    origin: CustomTemplateOrigin;
    name?: string;
    baseKey?: string | null;
    instruction?: string | null;
    file?: File | null;
  }) => {
    const form = new FormData();
    form.append("origin", body.origin);
    if (body.name) form.append("name", body.name);
    if (body.baseKey) form.append("base_key", body.baseKey);
    if (body.instruction) form.append("instruction", body.instruction);
    if (body.file) form.append("file", body.file);
    return api
      .post<CustomTemplateDetail>(BASE, form, MULTIPART)
      .then((r) => r.data);
  },
  redraft: (id: number, instruction: string) =>
    api.post<CustomTemplateDetail>(`${BASE}/${id}/draft`, { instruction }).then((r) => r.data),
  upload: (id: number, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return api
      .post<CustomTemplateDetail>(`${BASE}/${id}/upload`, form, MULTIPART)
      .then((r) => r.data);
  },
  update: (id: number, body: CustomSettingsBody) =>
    api.patch<CustomTemplateDetail>(`${BASE}/${id}`, body).then((r) => r.data),
  discard: (id: number) => api.delete(`${BASE}/${id}/draft`),
  /** Próbny DOCX z danymi fikcyjnymi — `saveDocx(res, …)`. */
  sample: (id: number) => api.post(`${BASE}/${id}/sample`, {}, { responseType: "blob" }),
  submit: (id: number) =>
    api.post<CustomTemplateDetail>(`${BASE}/${id}/submit`, {}).then((r) => r.data),
  approve: (id: number, note?: string) =>
    api.post<CustomTemplateDetail>(`${BASE}/${id}/approve`, { note }).then((r) => r.data),
  returnToAuthor: (id: number, reason: string) =>
    api.post<CustomTemplateDetail>(`${BASE}/${id}/return`, { reason }).then((r) => r.data),
  withdraw: (id: number, reason: string) =>
    api.post<CustomTemplateDetail>(`${BASE}/${id}/withdraw`, { reason }).then((r) => r.data),
  newVersion: (id: number) =>
    api.post<CustomTemplateDetail>(`${BASE}/${id}/new-version`, {}).then((r) => r.data),
  prefill: (id: number, candidateId: number | null, jobId: number | null) =>
    api
      .get<{ values: CustomValues }>(`${BASE}/${id}/prefill`, {
        params: {
          ...(candidateId ? { candidate_id: candidateId } : {}),
          ...(jobId ? { job_id: jobId } : {}),
        },
      })
      .then((r) => r.data),
  preview: (id: number, body: CustomDocumentBody) =>
    api
      .post<{ html: string; missing: string[] }>(`${BASE}/${id}/preview`, body)
      .then((r) => r.data),
  /** DOCX w odpowiedzi; `X-Document-Id` = wiersz w rejestrze dokumentów. */
  createDocument: (id: number, body: CustomDocumentBody) =>
    api.post(`${BASE}/${id}/documents`, body, { responseType: "blob" }),
};

export function useCustomTemplates() {
  return useQuery({
    queryKey: customTemplatesKeys.list(),
    queryFn: customTemplatesApi.list,
    staleTime: 30_000,
  });
}

export function useCustomTemplateBases() {
  return useQuery({
    queryKey: customTemplatesKeys.bases(),
    queryFn: customTemplatesApi.bases,
    staleTime: 10 * 60_000,
  });
}

export function useCustomTemplate(id: number | null) {
  return useQuery({
    queryKey: customTemplatesKeys.detail(id ?? 0),
    queryFn: () => customTemplatesApi.detail(id as number),
    enabled: id !== null,
    staleTime: 0,
  });
}
