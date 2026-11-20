/**
 * Foldery w zakładce Dokumenty kontraktu (0494, ticket Ani 21.10.2026).
 *
 * Typy są lustrem `backend/app/api/contract_document_folders.py`. Zasady:
 * - plik bez folderu = sekcja „Aktualna umowa”, zawsze na górze;
 * - folder „Zamówienia” wynika z typu dokumentu (`order`) i zbiera też PDF-y
 *   z zakładki Zamówienia (dawna sekcja „Dokumenty zamówień” pod tabelą);
 * - plik w folderze to archiwum — nie zapala alarmu „dokument wygasł”.
 */

import type { OrderDocumentItem } from "@/lib/api/dlPortal";

export interface ContractDocument {
  id: number;
  contract_id: number;
  filename: string;
  doc_type: string;
  content_type: string | null;
  size_bytes: number | null;
  expiry_date: string | null;
  uploaded_by: number | null;
  uploaded_by_email: string | null;
  created_at: string;
  // Ticket 9 (0402): pochodzenie i kopia w folderze „Umowy pracowników”.
  source?: string | null;
  sharepoint_item_id?: string | null;
  sharepoint_push_status?: string | null;
  sharepoint_push_error?: string | null;
  // 0494: folder w zakładce Dokumenty (null = „Aktualna umowa”).
  folder_id?: number | null;
}

export interface DocumentFolder {
  id: number;
  name: string;
  created_at: string;
}

export interface FolderSuggestion {
  number: string;
  folder_name: string;
  folder_id: number | null;
  document_ids: number[];
}

export interface DocumentFoldersResponse {
  folders: DocumentFolder[];
  orders_folder_name: string;
  current_contract_number: string | null;
  suggestions: FolderSuggestion[];
}

export type FileRow =
  | { kind: "doc"; key: string; doc: ContractDocument }
  | { kind: "order"; key: string; order: OrderDocumentItem };

/** „1 plik”, „3 pliki”, „5 plików”, „22 pliki”, „12 plików”. */
export function filesLabel(n: number): string {
  if (n === 1) return "1 plik";
  const last = n % 10;
  const lastTwo = n % 100;
  if (last >= 2 && last <= 4 && (lastTwo < 12 || lastTwo > 14)) {
    return `${n} pliki`;
  }
  return `${n} plików`;
}

/** Forma czasownika do liczby: (1) „wrócił”, (2–4, 22…) „wróciły”, (5…) „wróciło”. */
export function pluralForm(n: number, one: string, few: string, many: string): string {
  if (n === 1) return one;
  const last = n % 10;
  const lastTwo = n % 100;
  return last >= 2 && last <= 4 && (lastTwo < 12 || lastTwo > 14) ? few : many;
}

const GENERIC_NAMES = [
  "Poprzednia umowa",
  "Dokumenty firmy (NIP, ZUS, OC)",
  "Archiwum",
];

/**
 * Podpowiedzi w oknie „Nowy folder”: najpierw nazwy z numerów umów
 * odczytanych z plików, potem ogólne. Bez nazw, które już są na kontrakcie.
 */
export function folderNameSuggestions(
  suggestions: readonly FolderSuggestion[],
  existingNames: readonly string[],
): string[] {
  const taken = new Set(existingNames.map((n) => n.toLocaleLowerCase("pl")));
  const out: string[] = [];
  for (const name of [...suggestions.map((s) => s.folder_name), ...GENERIC_NAMES]) {
    const key = name.toLocaleLowerCase("pl");
    if (taken.has(key)) continue;
    taken.add(key);
    out.push(name);
  }
  return out;
}

/** Dokumenty, które liczą się do alarmu „dokument wygasł” — bez archiwum. */
export function complianceRelevantDocs(
  docs: readonly ContractDocument[],
): ContractDocument[] {
  return docs.filter((d) => d.folder_id == null);
}

export function formatBytes(n: number | null | undefined): string {
  if (!n) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}
