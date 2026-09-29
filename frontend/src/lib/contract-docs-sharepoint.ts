/**
 * Dokumenty kontraktów z folderu „Umowy pracowników” na SharePoincie (ticket 9).
 *
 * Typy są lustrem `backend/app/api/contract_folder_docs.py`. Funkcje czyste
 * (etykiety, grupowanie wierszy podglądu) testuje
 * `__tests__/contract-docs-sharepoint.test.ts`.
 */

import { api } from "@/lib/api";
import { getAuthenticatedRequestHeaders } from "@/lib/session";

const BASE = "/api/contract-docs-sharepoint";
const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export type RunMode =
  "listing" | "preview" | "applying" | "applied" | "rolled_back" | "failed";
export type MatchKind =
  "sure" | "uncertain" | "ambiguous" | "none" | "excluded";
export type RunItemKind = "assignment" | "contract" | "folder" | "file";

export interface SharePointStatus {
  configured: boolean;
  sync_enabled: boolean;
  health: string;
  url: string | null;
  folder_name: string | null;
  folder_label: string | null;
  folder_resolved: boolean;
  initial_import_run_id: number | null;
  last_sync_at: string | null;
  last_sync_status: "ok" | "error" | null;
  last_sync_error: string | null;
  last_sync_stats: Record<string, number>;
  review_count: number;
  push_counts: Record<string, number>;
}

export interface SharePointRun {
  id: number;
  mode: RunMode;
  source_url: string | null;
  counters: Record<string, number>;
  error: string | null;
  created_at: string | null;
  created_by_name: string | null;
  applied_at: string | null;
  rolled_back_at: string | null;
  can_rollback: boolean;
}

export interface SharePointRunItem {
  id: number;
  kind: RunItemKind;
  folder_name: string | null;
  file_name: string | null;
  size_bytes: number | null;
  doc_type: string | null;
  contract_id: number | null;
  person_name: string | null;
  match_kind: MatchKind | null;
  reasons: string[];
  note: string | null;
  selected: boolean;
  status: string;
  error: string | null;
}

export interface SharePointRunDetail extends SharePointRun {
  progress: { total: number; done: number };
  items: SharePointRunItem[];
}

export interface ReviewItem {
  item_id: string;
  folder_name: string | null;
  file_name: string;
  reasons: string[];
  proposed: { contract_id: number; person_name: string | null }[];
}

export const contractDocsSharePointApi = {
  status: () => api.get<SharePointStatus>(`${BASE}/status`).then((r) => r.data),
  runs: () => api.get<SharePointRun[]>(`${BASE}/runs`).then((r) => r.data),
  run: (id: number) =>
    api.get<SharePointRunDetail>(`${BASE}/runs/${id}`).then((r) => r.data),
  preview: (url: string, folderName: string | null) =>
    api
      .post<{ run_id: number }>(`${BASE}/preview`, {
        url,
        folder_name: folderName || null,
      })
      .then((r) => r.data),
  apply: (id: number, deselected: number[]) =>
    api
      .post(`${BASE}/runs/${id}/apply`, { deselected_item_ids: deselected })
      .then((r) => r.data),
  rollback: (id: number) =>
    api
      .post<{ removed: number; kept_referenced: number }>(
        `${BASE}/runs/${id}/rollback`,
      )
      .then((r) => r.data),
  review: () => api.get<ReviewItem[]>(`${BASE}/review`).then((r) => r.data),
  decide: (
    itemId: string,
    action: "assign" | "dismiss",
    contractIds: number[],
  ) =>
    api
      .post(`${BASE}/review/${encodeURIComponent(itemId)}`, {
        action,
        contract_ids: contractIds,
      })
      .then((r) => r.data),
  syncNow: () => api.post(`${BASE}/sync-now`).then((r) => r.data),
};

/** Raport XLSX — natywny `fetch` z tokenem (jak dokumenty kontraktu). */
export async function downloadRunReport(runId: number): Promise<void> {
  const res = await fetch(`${API_BASE}${BASE}/runs/${runId}/report.xlsx`, {
    headers: getAuthenticatedRequestHeaders(),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = `dokumenty-sharepoint-${runId}.xlsx`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export const RUN_MODE_LABEL: Record<RunMode, string> = {
  listing: "Czytam folder…",
  preview: "Podgląd — nic nie zapisano",
  applying: "Pobieram pliki…",
  applied: "Zapisano",
  rolled_back: "Cofnięty",
  failed: "Nie udało się",
};

export const DOC_TYPE_LABEL: Record<string, string> = {
  contract: "Umowa",
  annex: "Aneks",
  termination_notice: "Wypowiedzenie",
  termination_agreement: "Porozumienie",
  nda: "NDA",
  oc_policy: "Polisa OC",
  zus_certificate: "Zaświadczenie ZUS",
  other: "Inne",
};

export const REASON_LABEL: Record<string, string> = {
  diacritics: "różnica w polskich znakach",
  partial_name: "inny zapis nazwiska (drugie imię albo człon nazwiska)",
  typo: "możliwa literówka w nazwisku",
  same_name_people: "kilka rekordów kandydata o tym nazwisku",
  multiple_folders: "kilka pasujących podfolderów",
  excluded: "Filip Jabłoński — dokumenty dodaje człowiek",
};

export function reasonsText(reasons: string[]): string {
  return reasons.map((r) => REASON_LABEL[r] ?? r).join("; ");
}

/** Podsumowanie z ticketu (pkt 8) — kolejność kafli w panelu. */
export const SUMMARY_COUNTERS: { key: string; label: string }[] = [
  {
    key: "contracts_with_documents",
    label: "Kontrakty z dokumentami w folderze",
  },
  {
    key: "contracts_without_documents",
    label: "Bez podfolderu lub dokumentów",
  },
  { key: "contracts_uncertain", label: "Przypisania niepewne" },
  { key: "contracts_ambiguous", label: "Kilka pasujących folderów" },
  { key: "folders_without_contract", label: "Foldery bez kontraktu" },
  { key: "assignments", label: "Pliki do zapisania" },
  { key: "files_skipped_extension", label: "Pominięte (Word i inne)" },
  { key: "contracts_excluded", label: "Pominięte (Filip Jabłoński)" },
];

export const APPLIED_COUNTERS: { key: string; label: string }[] = [
  {
    key: "contracts_with_imported_documents",
    label: "Kontrakty z zapisanymi dokumentami",
  },
  { key: "imported", label: "Pliki zapisane" },
  { key: "skipped_existing", label: "Pominięte — już były" },
  { key: "failed", label: "Błędy pobrania" },
];

export interface ContractGroup {
  contractId: number;
  personName: string;
  folderName: string | null;
  matchKind: MatchKind | null;
  reasons: string[];
  files: SharePointRunItem[];
}

/** Przypisania pogrupowane po kontrakcie — jeden checkbox na kontrakt. */
export function groupAssignments(items: SharePointRunItem[]): ContractGroup[] {
  const groups = new Map<number, ContractGroup>();
  for (const item of items) {
    if (item.kind !== "assignment" || item.contract_id == null) continue;
    const existing = groups.get(item.contract_id);
    if (existing) {
      existing.files.push(item);
      continue;
    }
    groups.set(item.contract_id, {
      contractId: item.contract_id,
      personName: item.person_name ?? "",
      folderName: item.folder_name,
      matchKind: item.match_kind,
      reasons: item.reasons,
      files: [item],
    });
  }
  return [...groups.values()];
}

/** Kontrakty bez podfolderu albo z folderem bez PDF/JPG (ticket, pkt 8). */
export function contractsWithoutDocuments(
  items: SharePointRunItem[],
): SharePointRunItem[] {
  return items.filter(
    (i) =>
      i.kind === "contract" &&
      i.match_kind !== "ambiguous" &&
      i.match_kind !== "excluded",
  );
}

/** Do weryfikacji: niepewne przypisania i kontrakty z kilkoma folderami. */
export function uncertainGroups(items: SharePointRunItem[]): {
  uncertain: ContractGroup[];
  ambiguous: SharePointRunItem[];
} {
  return {
    uncertain: groupAssignments(items).filter(
      (g) => g.matchKind === "uncertain",
    ),
    ambiguous: items.filter(
      (i) => i.kind === "contract" && i.match_kind === "ambiguous",
    ),
  };
}

/** Id wierszy do pominięcia przy zapisie, gdy admin odznaczył kontrakty. */
export function deselectedItemIds(
  groups: ContractGroup[],
  unchecked: ReadonlySet<number>,
): number[] {
  return groups
    .filter((g) => unchecked.has(g.contractId))
    .flatMap((g) => g.files.map((f) => f.id));
}

/** „1 plik”, „3 pliki”, „5 plików”, „22 pliki”, „12 plików”. */
export function filesLabel(count: number): string {
  if (count === 1) return "1 plik";
  const lastTwo = count % 100;
  const last = count % 10;
  if (last >= 2 && last <= 4 && (lastTwo < 12 || lastTwo > 14))
    return `${count} pliki`;
  return `${count} plików`;
}

/** Stan kopii dokumentu w SharePoincie — plakietka w zakładce Dokumenty. */
export function sharePointBadge(doc: {
  source?: string | null;
  sharepoint_item_id?: string | null;
  sharepoint_push_status?: string | null;
  sharepoint_push_error?: string | null;
}): {
  label: string;
  tone: "neutral" | "success" | "warning";
  title?: string;
} | null {
  if (doc.source === "sharepoint" || doc.source === "sharepoint_import") {
    return { label: "z SharePointa", tone: "neutral" };
  }
  if (doc.sharepoint_item_id)
    return { label: "w SharePoincie", tone: "success" };
  if (
    doc.sharepoint_push_status === "skipped" ||
    doc.sharepoint_push_status === "failed"
  ) {
    return {
      label: "nie wysłano do SharePointa",
      tone: "warning",
      title: doc.sharepoint_push_error ?? undefined,
    };
  }
  return null;
}
