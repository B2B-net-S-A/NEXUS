// Dane firm z umów — do potwierdzenia (E5a, 0755).
//
// Backend: `services/contract_partner_reads`. Model czyta podpisaną umowę
// aktywnych kontraktów B2B bez danych firmy w Generatorze; człowiek potwierdza
// każdą propozycję. „Zastosuj” wpisuje do profilu kandydata tylko puste pola,
// chyba że zaznaczono „Nadpisz”.

import { api } from "@/lib/api";

export type PartnerReadState = "open" | "failed" | "applied" | "dismissed";

export type PartnerFieldName =
  | "gender"
  | "partner_name"
  | "partner_legal_name"
  | "partner_entity_type"
  | "partner_nip"
  | "partner_regon"
  | "partner_business_address"
  | "partner_correspondence_address"
  | "partner_email"
  | "partner_phone"
  | "partner_krs"
  | "partner_seat"
  | "partner_registry_court"
  | "partner_share_capital"
  | "partner_representative_name"
  | "partner_representative_function"
  | "partner_representation";

export interface PartnerReadField {
  name: PartnerFieldName;
  value: string | null;
  quote: string | null;
  /** `false` = cytatu nie ma w tekście pliku; `null` = skan, nie sprawdzono. */
  quote_found: boolean | null;
  /** Kolumna kandydata, do której trafia pole, albo `null` (tylko nowa umowa). */
  column: string | null;
  current: string | null;
}

export interface PartnerReadIssue {
  field: string;
  message: string;
}

export interface RegistryComparison {
  field: PartnerFieldName;
  read: string | null;
  registry: string;
  same: boolean;
}

export interface PartnerReadVerification {
  status: "verified" | "unverified";
  registry: string | null;
  checked_at: string | null;
  message: string | null;
  warnings: { code?: string; message?: string }[];
  comparison: RegistryComparison[];
}

export type CandidateChangeAction =
  | "written"
  | "same"
  | "kept"
  | "taken"
  | "no_value";

export interface PartnerRead {
  id: number;
  contract_id: number;
  document_id: number;
  filename: string | null;
  status: "read" | "failed" | "skipped";
  mode: "text" | "pdf" | "image" | null;
  read_at: string | null;
  document_kind: string | null;
  agreement_number: string | null;
  document_date: string | null;
  contract_variant: "jdg" | "company" | null;
  client_name: string | null;
  contract_status: string | null;
  candidate_id: number | null;
  candidate_name: string | null;
  fields: PartnerReadField[];
  issues: PartnerReadIssue[];
  decision: "applied" | "dismissed" | null;
  decided_at: string | null;
  /** Dane potwierdzone przy „Zastosuj” (z poprawkami) — do nowej umowy. */
  confirmed: {
    fields: Partial<Record<PartnerFieldName, string | null>>;
    corrected: PartnerFieldName[];
  } | null;
  candidate_changes: Record<string, { action: CandidateChangeAction }> | null;
  verification: PartnerReadVerification | null;
  verified_at: string | null;
}

export interface PartnerReadCounts {
  open: number;
  failed: number;
  applied: number;
  dismissed: number;
  to_read: number;
  without_file: number;
  eligible: number;
}

export interface PartnerReadList {
  state: PartnerReadState;
  items: PartnerRead[];
  total: number;
  counts: PartnerReadCounts;
}

/** Poprawki człowieka: pole → wartość (pusta = „brak w umowie”). */
export type PartnerReadValues = Partial<Record<PartnerFieldName, string | null>>;

export async function fetchPartnerReads(
  state: PartnerReadState,
  offset = 0,
  limit = 20,
): Promise<PartnerReadList> {
  const { data } = await api.get<PartnerReadList>("/api/contract-partner-reads", {
    params: { state, offset, limit },
  });
  return data;
}

export async function applyPartnerRead(
  readId: number,
  body: { overwrite: boolean; values: PartnerReadValues },
): Promise<PartnerRead> {
  const { data } = await api.post<PartnerRead>(
    `/api/contract-partner-reads/${readId}/apply`,
    body,
  );
  return data;
}

export async function dismissPartnerRead(readId: number): Promise<PartnerRead> {
  const { data } = await api.post<PartnerRead>(
    `/api/contract-partner-reads/${readId}/dismiss`,
  );
  return data;
}

export async function verifyPartnerRead(
  readId: number,
  values: PartnerReadValues,
): Promise<PartnerRead> {
  const { data } = await api.post<PartnerRead>(
    `/api/contract-partner-reads/${readId}/verify`,
    { values },
  );
  return data;
}
