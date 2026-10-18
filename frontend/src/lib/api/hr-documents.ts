// „Ludzie w NEXUSIE” — dokumenty osoby, e-teczka (etap 5, E4, 18.10.2026).
//
// Lustro `backend/app/api/hr_documents.py` (prefiks `/api/hr/documents`,
// moduł `people`). Kadry i admin widzą całą e-teczkę; osoba, Płace i recepcja
// — dokumenty ze swoim znacznikiem; przełożony nic (serwer: 404). Protokoły
// sprzętu to odnośniki z modułu sprzętu (`protocols`, `null` = nie dla tej osoby).
// Słownik rodzajów jest lustrem `services/hr/documents_rules.KIND_LABELS`
// (test `backend/tests/test_hr_documents_labels_mirror.py`).

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { fetchAuthenticatedDownload, downloadBlob } from "@/lib/authenticated-files";

const BASE = "/api/hr/documents";

export type DocumentKind =
  | "contract"
  | "annex"
  | "statement"
  | "certificate"
  | "protocol"
  | "other";
export type DocumentPurpose = "student_status";
export type DocumentSource = "upload" | "agreement";

export const DOCUMENT_KINDS: DocumentKind[] = [
  "contract",
  "annex",
  "statement",
  "certificate",
  "protocol",
  "other",
];

export const DOCUMENT_KIND_LABELS: Record<DocumentKind, string> = {
  contract: "umowa",
  annex: "aneks",
  statement: "oświadczenie",
  certificate: "zaświadczenie",
  protocol: "protokół",
  other: "inne",
};

/** Domyślny krąg poza Kadrami — to samo co `DEFAULT_AUDIENCE` na serwerze. */
export const DEFAULT_AUDIENCE: Record<DocumentKind, DocumentAudience> = {
  contract: { person: true, payroll: true, equipment: false },
  annex: { person: true, payroll: true, equipment: false },
  statement: { person: true, payroll: true, equipment: false },
  certificate: { person: true, payroll: true, equipment: false },
  protocol: { person: true, payroll: false, equipment: true },
  other: { person: true, payroll: false, equipment: false },
};

export interface DocumentAudience {
  person: boolean;
  payroll: boolean;
  equipment: boolean;
}

export interface PersonDocument {
  id: number;
  user_id: number;
  kind: DocumentKind;
  purpose: DocumentPurpose | null;
  title: string;
  source: DocumentSource;
  source_ref: string | null;
  file_name: string | null;
  mime: string;
  size_bytes: number;
  sha256: string;
  valid_until: string | null;
  audience: DocumentAudience;
  added_by_name: string | null;
  created_at: string;
  deleted: boolean;
  /** Tylko dla Kadr: ślad usunięcia. */
  deleted_at?: string | null;
  deletion_reason?: "retention" | "mistake" | null;
  deleted_by_name?: string | null;
}

export type ProtocolStatus = "oczekuje" | "podpisany" | "potwierdzony";

export interface PersonProtocol {
  id: number;
  number: string;
  kind: "wydanie" | "zwrot";
  protocol_date: string;
  status: ProtocolStatus;
  signed_at: string | null;
  has_signed_file: boolean;
}

export interface PersonDocuments {
  user_id: number;
  can_manage: boolean;
  documents: PersonDocument[];
  protocols: PersonProtocol[] | null;
}

export type ProfileSyncStatus =
  | "updated"
  | "kept_earlier"
  | "not_zlecenie"
  | "past"
  | "no_profile";

export interface ProfileSync {
  status: ProfileSyncStatus;
  until: string | null;
}

export interface DocumentSaved {
  document: PersonDocument;
  profile_sync: ProfileSync | null;
}

export interface UploadInput {
  file: File;
  kind: DocumentKind;
  title: string;
  valid_until?: string | null;
  purpose?: DocumentPurpose | null;
  audience: DocumentAudience;
}

export interface DocumentPatch {
  title?: string;
  valid_until?: string | null;
  audience?: DocumentAudience;
}

export interface RetentionEntry {
  kind: DocumentKind;
  label: string;
  years: number;
  default_years: number;
}

export interface RetentionDueItem {
  id: number;
  user_id: number;
  person_name: string;
  kind: DocumentKind;
  title: string;
  source: DocumentSource;
  created_at: string;
  last_day: string;
  delete_from: string;
}

export interface RetentionDue {
  items: RetentionDueItem[];
  retention: RetentionEntry[];
}

export interface RetentionDeleteResult {
  deleted: number[];
  skipped: { id: number; reason: "not_due" }[];
}

export const documentKeys = {
  all: ["hr", "documents"] as const,
  person: (userId: number) => ["hr", "documents", "person", userId] as const,
  retention: ["hr", "documents", "retention"] as const,
  retentionSettings: ["hr", "documents", "retention-settings"] as const,
};

/** Druga linia przy oświadczeniu studenta po zapisie — co stało się w kartotece. */
export function profileSyncMessage(sync: ProfileSync | null): string | null {
  if (!sync) return null;
  switch (sync.status) {
    case "updated":
      return "W kartotece zapisano zwolnienie ze składek do tej daty — Płace dostaną przypomnienie 30 dni wcześniej.";
    case "kept_earlier":
      return "W kartotece zostaje wcześniejsza data końca zwolnienia ze składek (wpisana przez Kadry).";
    case "not_zlecenie":
      return "Zwolnienie ze składek dotyczy tylko umowy zlecenie — kartoteka bez zmian.";
    case "past":
      return "Oświadczenie jest już nieważne — kartoteka bez zmian.";
    default:
      return null;
  }
}

/** Kto widzi dokument — słowami, jak w makiecie („osoba, Kadry, Płace”). */
export function audienceLabel(audience: DocumentAudience): string {
  const parts: string[] = [];
  if (audience.person) parts.push("osoba");
  parts.push("Kadry");
  if (audience.payroll) parts.push("Płace");
  if (audience.equipment) parts.push("recepcja");
  return parts.join(", ");
}

export function usePersonDocuments(userId: number, enabled = true) {
  return useQuery({
    queryKey: documentKeys.person(userId),
    queryFn: async () =>
      (await api.get<PersonDocuments>(`${BASE}/people/${userId}`)).data,
    enabled: enabled && Number.isFinite(userId) && userId > 0,
    staleTime: 30_000,
  });
}

function useInvalidatePerson(userId: number) {
  const client = useQueryClient();
  return () => {
    void client.invalidateQueries({ queryKey: documentKeys.person(userId) });
    // Oświadczenie studenta zmienia kartotekę (data końca zwolnienia).
    void client.invalidateQueries({ queryKey: ["hr", "people", userId] });
  };
}

export function useUploadDocument(userId: number) {
  const invalidate = useInvalidatePerson(userId);
  return useMutation({
    mutationFn: async (input: UploadInput) => {
      const form = new FormData();
      form.append("file", input.file);
      form.append("kind", input.kind);
      form.append("title", input.title);
      if (input.valid_until) form.append("valid_until", input.valid_until);
      if (input.purpose) form.append("purpose", input.purpose);
      form.append("visible_to_person", String(input.audience.person));
      form.append("visible_to_payroll", String(input.audience.payroll));
      form.append("visible_to_equipment", String(input.audience.equipment));
      return (
        await api.post<DocumentSaved>(`${BASE}/people/${userId}`, form, {
          headers: { "Content-Type": "multipart/form-data" },
        })
      ).data;
    },
    onSuccess: invalidate,
  });
}

export function useUpdateDocument(userId: number) {
  const invalidate = useInvalidatePerson(userId);
  return useMutation({
    mutationFn: async ({ id, patch }: { id: number; patch: DocumentPatch }) =>
      (await api.patch<DocumentSaved>(`${BASE}/${id}`, patch)).data,
    onSuccess: invalidate,
  });
}

export function useRemoveDocument(userId: number) {
  const invalidate = useInvalidatePerson(userId);
  return useMutation({
    mutationFn: async ({ id, note }: { id: number; note: string }) =>
      (await api.post<{ id: number; deleted: true }>(`${BASE}/${id}/remove`, { note })).data,
    onSuccess: invalidate,
  });
}

/** Pobiera plik dokumentu z tokenem (bez surowego `<a href>` do API). */
export async function downloadDocument(document: PersonDocument): Promise<void> {
  const { blob, filename } = await fetchAuthenticatedDownload(`${BASE}/${document.id}/file`);
  downloadBlob(blob, filename ?? document.file_name ?? document.title);
}

export async function downloadProtocol(userId: number, protocol: PersonProtocol): Promise<void> {
  const { blob, filename } = await fetchAuthenticatedDownload(
    `${BASE}/people/${userId}/protocols/${protocol.id}/file`,
  );
  downloadBlob(blob, filename ?? `Protokol_${protocol.number.replace(/\//g, "_")}.pdf`);
}

export function useRetentionDue(enabled = true) {
  return useQuery({
    queryKey: documentKeys.retention,
    queryFn: async () => (await api.get<RetentionDue>(`${BASE}/retention`)).data,
    enabled,
  });
}

export function useDeleteRetentionDue() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (documentIds: number[]) =>
      (
        await api.post<RetentionDeleteResult>(`${BASE}/retention/delete`, {
          document_ids: documentIds,
          confirm: true,
        })
      ).data,
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: documentKeys.all });
    },
  });
}

export function useSaveRetention() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (years: Partial<Record<DocumentKind, number>>) =>
      (
        await api.put<{ retention: RetentionEntry[] }>(`${BASE}/settings/retention`, {
          years,
        })
      ).data,
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: documentKeys.retention });
    },
  });
}
