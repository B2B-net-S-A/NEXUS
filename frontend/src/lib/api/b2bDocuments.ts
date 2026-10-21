/**
 * Generator dokumentów pochodnych umowy B2B: aneksy, rozwiązania, umowy
 * przedwstępne. Lustro `backend/app/api/b2b_documents.py` (prefiks
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
  | "gender"
  /** Lista pozycji stawki aneksu (kwota, klient z NEXUSA, od, do). */
  | "rate_items";
export type DocumentFieldGroup = "base" | "document" | "partner" | "change";

/** Pozycja stawki aneksu — kwota jak wpisał człowiek („135,50”). */
export interface RateItemValue {
  rate: string | number | null;
  client_id?: number | null;
  /** Wyłącznie do wyświetlenia — do dokumentu serwer bierze nazwę z NEXUSA. */
  client_name?: string | null;
  from?: string | null;
  to?: string | null;
}

export type DocumentValue =
  | string
  | number
  | boolean
  | null
  | RateItemValue[];
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
  /** „Pobierz z rejestru” przy polu (NIP) — `GET /company-lookup`. */
  lookup: "registry" | null;
  /** (klucz odpowiedzi rejestru, klucz pola formularza). */
  lookup_fills: [string, string][];
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
  /** Zakładka „Generator aneksów”: przyjmuje też umowę spoza NEXUSA. */
  allows_external: boolean;
  /** Języki tylko do ponownego pobrania starych dokumentów. */
  legacy_languages: string[];
  /** Umowa przedwstępna: `cez` = tylko Centrum e-Zdrowia, `general` = inni klienci. */
  preliminary_scope?: "cez" | "general" | null;
  /** Ile dni od zawarcia obowiązuje umowa przedwstępna. */
  default_validity_days?: number | null;
  /** W ilu dniach roboczych od akceptacji Klienta zawiera się umowę B2B. */
  b2b_term_business_days?: number | null;
}

/** Umowy przedwstępne dozwolone w rekrutacji (po jej kliencie). */
export interface PreliminaryOptions {
  client_id: number | null;
  types: {
    key: string;
    label: string;
    default_validity_days: number | null;
    b2b_term_business_days: number | null;
  }[];
  default_validity_days: number | null;
  b2b_term_business_days: number | null;
}

/** Pusty wzór do umowy zlecenie (`mandate_forms.py`) — wypełnia zleceniobiorca. */
export interface MandateFormDef {
  key: string;
  label: string;
  description: string;
  download_name: string;
  format: "PDF" | "DOCX";
}

export interface DocumentTypesResponse {
  types: DocumentTypeDef[];
  ref_labels: Record<string, string>;
  ref_defaults: Record<string, string>;
  mandate_forms: MandateFormDef[];
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
  /** Generator aneksów: „§ X ust. Y” dla obu wariantów Partnera. */
  paragraph_defaults?: Partial<Record<"sole_trader" | "company", [string, string]>>;
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
  /**
   * Kontrakt aneksu bez umowy w rejestrze (umowa spoza NEXUSA, zlecenie) albo
   * kontrakt wskazany dla umowy z rejestru bez powiązania. Osobę i klienta
   * dokumentu serwer bierze z kontraktu.
   */
  contract_id?: number | null;
  /** Klient aneksu bez umowy i bez kontraktu („Bez kontraktu”). */
  client_id?: number | null;
  values: DocumentValues;
  refs?: Record<string, string> | null;
}

export type DocumentStatus = "issued" | "signed" | "cancelled";
/** `no_contract` = aneks czekający na podpis bez kontraktu, w którym podpis coś zmieni. */
export type DocumentStatusFilter = DocumentStatus | "unsigned" | "no_contract";

/**
 * Stan aneksu liczony przez serwer — jeden zamiast pary „status aneksu”
 * + „status podpisu” (przy aneksie obie osie mówią to samo).
 */
export type AnnexState = "waiting" | "signed_pending" | "in_force" | "cancelled";

export interface AnnexRateItem {
  rate: number;
  from: string | null;
  to: string | null;
  client_id?: number | null;
  client_name?: string | null;
}

/** Skrót zmiany z aneksu. Kwoty tylko dla osób, które widzą stawki. */
export type AnnexChange =
  | { kind: "rate"; hidden: true }
  | {
      kind: "rate";
      hidden: false;
      currency: string;
      items: AnnexRateItem[];
      /** Stawki sprzed aneksu; puste, gdy nieznane albo niewidoczne. */
      before: AnnexRateItem[];
    }
  | { kind: "start_date"; before: string | null; after: string | null }
  | { kind: "party"; legal_name: string | null; nip: string | null }
  | { kind: "delegate"; name: string | null }
  | {
      kind: "mandate";
      period_from: string | null;
      period_to: string | null;
      rate_changed: boolean;
    };

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
  // Rejestr aneksów (13.10.2026). Opcjonalne, bo starszy backend (wycofane
  // wdrożenie jednej strony) ich nie odda — lista ma wtedy działać dalej.
  client_id?: number | null;
  /** Osoba z kontraktu albo umowy; inaczej imię i nazwisko z formularza. */
  person_name?: string | null;
  partner_legal_name?: string | null;
  partner_nip?: string | null;
  /** Aneks bez umowy w rejestrze (umowa spoza NEXUSA, zlecenie). */
  external?: boolean;
  effective_date?: string | null;
  state?: AnnexState;
  change?: AnnexChange | null;
  can_restore?: boolean;
  can_link_contract?: boolean;
  /** Skan podpisanego aneksu w Dokumentach kontraktu. */
  signed_scan_document_id?: number | null;
}

/** Zdarzenie z historii dokumentu (`GET /documents/{id}/history`). */
export interface DocumentHistoryEntry {
  action:
    | "generated"
    | "regenerated"
    | "cancelled"
    | "restored"
    | "contract_linked"
    | "signed_effect_applied"
    | "signed_scan_attached"
    | string;
  at: string | null;
  by_name: string | null;
  /** Powód anulowania. */
  note: string | null;
}

/** Kontrakt do wskazania przy umowie z rejestru bez powiązania. */
export interface DocumentSubjectContract {
  contract_id: number;
  status: string;
  start_date: string | null;
}

/**
 * Pozycja wyszukiwania „Dla kogo jest aneks?”: umowa z rejestru albo kontrakt
 * bez umowy w rejestrze (umowa spoza NEXUSA, zlecenie). Bez kwot.
 */
export interface DocumentSubject {
  kind: "agreement" | "contract";
  parent_generated_contract_id: number | null;
  contract_number: string | null;
  source: string | null;
  agreement_status: string | null;
  contract_id: number | null;
  contract_status: string | null;
  contract_start_date: string | null;
  contract_options: DocumentSubjectContract[];
  candidate_id: number | null;
  person_name: string | null;
  partner_name: string | null;
  partner_nip: string | null;
  client_id: number | null;
  client_name: string | null;
}

export interface DocumentForm {
  id: number;
  document_type: string;
  language: string;
  parent_generated_contract_id: number | null;
  candidate_id: number | null;
  job_id: number | null;
  /** Aneks bez umowy w rejestrze: kontrakt i klient z zapisu. */
  contract_id?: number | null;
  client_id?: number | null;
  client_name?: string | null;
  external?: boolean;
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
  /** Rodziny dokumentów: rejestr aneksów pyta o `annex`, „Dokumenty” o resztę. */
  family?: readonly DocumentFamily[];
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
  /** Umowa bez powiązania — kontrakt dopasowany po osobie u klienta umowy. */
  contract_matched_by_person?: boolean;
  /** Zmienił się tylko rejestr (brak trwającego kontraktu osoby u klienta). */
  contract_warning?: string | null;
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
    family?: readonly DocumentFamily[];
  }) =>
    [
      B2B_DOCUMENTS_KEY,
      "list",
      filters.documentType,
      filters.status,
      filters.q,
      (filters.family ?? []).join(","),
    ] as const,
  prefill: (
    documentType: string,
    parentId: number | null,
    candidateId: number | null,
    jobId: number | null = null,
    contractId: number | null = null,
  ) =>
    [
      B2B_DOCUMENTS_KEY,
      "prefill",
      documentType,
      parentId ?? 0,
      candidateId ?? 0,
      jobId ?? 0,
      contractId ?? 0,
    ] as const,
  effects: (id: number) => [B2B_DOCUMENTS_KEY, "effects", id] as const,
  history: (id: number) => [B2B_DOCUMENTS_KEY, "history", id] as const,
  preliminaryOptions: (candidateId: number, jobId: number) =>
    [B2B_DOCUMENTS_KEY, "preliminary-options", candidateId, jobId] as const,
  subjects: (documentType: string, q: string, contractId: number | null = null) =>
    [B2B_DOCUMENTS_KEY, "subjects", documentType, q, contractId ?? 0] as const,
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
    /** Aneks do kontraktu bez umowy w rejestrze — dane Partnera z kontraktu. */
    contractId?: number | null;
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
          ...(params.contractId ? { contract_id: params.contractId } : {}),
        },
      })
      .then((r) => r.data),
  /**
   * „Dla kogo jest aneks?” — umowy z rejestru i kontrakty bez umowy w jednym
   * wyniku. `contractId` = wejście z modułu Kontrakty (podmiot tego kontraktu).
   */
  subjects: (params: {
    documentType: string;
    q?: string;
    contractId?: number | null;
  }) =>
    api
      .get<DocumentSubject[]>("/api/b2b-generator/documents/subjects", {
        params: {
          document_type: params.documentType,
          ...(params.q?.trim() ? { q: params.q.trim() } : {}),
          ...(params.contractId ? { contract_id: params.contractId } : {}),
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
          ...(params.family?.length ? { family: [...params.family] } : {}),
          ...(params.q?.trim() ? { q: params.q.trim() } : {}),
        },
        // FastAPI czyta listę wyłącznie jako powtórzony parametr; domyślne
        // `family[]=` to po stronie serwera inna nazwa pola i filtr by przepadł.
        paramsSerializer: { indexes: null },
      })
      .then((r) => r.data),
  form: (id: number) =>
    api
      .get<DocumentForm>(`/api/b2b-generator/documents/${id}/form`)
      .then((r) => r.data),
  mandateForm: (key: string) =>
    api.get(`/api/b2b-generator/mandate-forms/${encodeURIComponent(key)}`, {
      responseType: "blob",
    }),
  /** Ponowne pobranie; `values` = tylko pola wrażliwe (nie przechowujemy ich). */
  redownload: (id: number, values: DocumentValues = {}) =>
    api.post(
      `/api/b2b-generator/documents/${id}/docx`,
      { values },
      { responseType: "blob" },
    ),
  /** PDF wydanego dokumentu (ten sam plik Word co DOCX); 503 = PDF chwilowo niedostępny. */
  pdf: (id: number, values: DocumentValues = {}) =>
    api.post(
      `/api/b2b-generator/documents/${id}/pdf`,
      { values },
      { responseType: "blob" },
    ),
  /**
   * Umowy przedwstępne dla klienta rekrutacji: Centrum e-Zdrowia — własny
   * wzór, inni klienci — umowa o udziale w procesie rekrutacyjnym.
   */
  preliminaryOptions: (candidateId: number, jobId: number) =>
    api
      .get<PreliminaryOptions>("/api/b2b-generator/documents/preliminary-options", {
        params: { candidate_id: candidateId, job_id: jobId },
      })
      .then((r) => r.data),
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
  /** Anulowany dokument wraca na „czeka na podpis”. */
  restore: (id: number) =>
    api
      .post<DocumentItem>(`/api/b2b-generator/documents/${id}/restore`)
      .then((r) => r.data),
  /** Powiąż niepodpisany aneks z kontraktem, w którym podpis ma coś zmienić. */
  linkContract: (id: number, contractId: number) =>
    api
      .post<DocumentItem>(`/api/b2b-generator/documents/${id}/link-contract`, {
        contract_id: contractId,
      })
      .then((r) => r.data),
  history: (id: number) =>
    api
      .get<DocumentHistoryEntry[]>(`/api/b2b-generator/documents/${id}/history`)
      .then((r) => r.data),
  /** Skan podpisanego aneksu (PDF, JPG, PNG) → Dokumenty kontraktu. */
  uploadSignedScan: (id: number, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return api
      .post<DocumentItem>(
        `/api/b2b-generator/documents/${id}/signed-scan`,
        form,
        { headers: { "Content-Type": "multipart/form-data" } },
      )
      .then((r) => r.data);
  },
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
