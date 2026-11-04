"use client";

/**
 * Harness panelu „Dokumenty kontraktów z SharePointa” (ticket 9).
 *
 * Renderuje prawdziwy widok przebiegu (`ContractDocsRunView`) z danymi
 * fikcyjnymi — bez react-query i bez ani jednego zapytania. `?state=applied`
 * pokazuje przebieg po zapisie (raport, „Cofnij zapis”).
 */

import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { ContractDocsRunView } from "@/components/settings/ContractDocsSharePointPanel";
import type {
  SharePointRunDetail,
  SharePointRunItem,
} from "@/lib/contract-docs-sharepoint";

let nextId = 1;
function item(partial: Partial<SharePointRunItem>): SharePointRunItem {
  return {
    id: nextId++,
    kind: "assignment",
    folder_name: null,
    file_name: null,
    size_bytes: 120_000,
    doc_type: "other",
    contract_id: null,
    person_name: null,
    match_kind: "sure",
    reasons: [],
    note: null,
    selected: true,
    status: "pending",
    error: null,
    ...partial,
  };
}

const ITEMS: SharePointRunItem[] = [
  item({
    contract_id: 501,
    person_name: "Anna Przykładowa",
    folder_name: "Przykładowa Anna",
    file_name: "1401-2026 B2B 04.05.2026.pdf",
    doc_type: "contract",
  }),
  item({
    contract_id: 501,
    person_name: "Anna Przykładowa",
    folder_name: "Przykładowa Anna",
    file_name: "Aneks nr 1.pdf",
    doc_type: "annex",
  }),
  item({
    contract_id: 502,
    person_name: "Anna Przykładowa",
    folder_name: "Przykładowa Anna",
    file_name: "1401-2026 B2B 04.05.2026.pdf",
    doc_type: "contract",
  }),
  item({
    contract_id: 503,
    person_name: "Lukasz Testowy",
    folder_name: "Testowy Łukasz",
    file_name: "NDA.pdf",
    doc_type: "nda",
    match_kind: "uncertain",
    reasons: ["diacritics"],
  }),
  item({
    contract_id: 504,
    person_name: "Ewa Próbna",
    folder_name: "Próbna-Wzorcowa Ewa",
    file_name: "Polisa OC 2026.jpg",
    doc_type: "oc_policy",
    match_kind: "uncertain",
    reasons: ["partial_name"],
  }),
  item({
    kind: "contract",
    contract_id: 505,
    person_name: "Marek Fikcyjny",
    match_kind: "none",
    note: "Nie znaleziono podfolderu „Nazwisko Imię”.",
  }),
  item({
    kind: "contract",
    contract_id: 506,
    person_name: "Piotr Wzorcowy",
    match_kind: "ambiguous",
    reasons: ["multiple_folders"],
    note: "Kilka pasujących podfolderów: Wzorcowy Piotr, Wzorcowy Piotr (2).",
  }),
  item({
    kind: "folder",
    folder_name: "Nieistniejący Jan",
    match_kind: "none",
    note: "Brak kontraktu tej osoby w NEXUSIE — pliki nie zostały przypisane.",
  }),
  item({
    kind: "file",
    folder_name: "Przykładowa Anna",
    file_name: "umowa.docx",
    match_kind: null,
    note: "Pominięty: import bierze tylko PDF i JPG.",
  }),
];

function run(state: string | null): SharePointRunDetail {
  const applied = state === "applied";
  return {
    id: 12,
    mode: applied ? "applied" : "preview",
    source_url: "https://example.sharepoint.com/sites/Przyklad",
    counters: {
      contracts_with_documents: 4,
      contracts_without_documents: 1,
      contracts_uncertain: 2,
      contracts_ambiguous: 1,
      folders_without_contract: 1,
      assignments: 5,
      files_skipped_extension: 1,
      contracts_excluded: 0,
      contracts_with_imported_documents: 4,
      imported: 5,
      skipped_existing: 0,
      failed: 0,
    },
    error: null,
    created_at: "2026-09-29T10:00:00Z",
    created_by_name: "Admin Przykładowy",
    applied_at: applied ? "2026-09-29T10:05:00Z" : null,
    rolled_back_at: null,
    can_rollback: applied,
    progress: { total: 5, done: applied ? 5 : 0 },
    items: applied
      ? ITEMS.map((i) =>
          i.kind === "assignment" ? { ...i, status: "done" } : i,
        )
      : ITEMS,
  };
}

function Harness() {
  const params = useSearchParams();
  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-4 p-4">
      <h1 className="text-xl font-semibold">
        Dokumenty kontraktów z SharePointa
      </h1>
      <ContractDocsRunView
        run={run(params.get("state"))}
        busy={false}
        onApply={() => undefined}
        onRollback={() => undefined}
      />
    </div>
  );
}

export default function ContractDocsSharePointPreview() {
  return (
    <Suspense>
      <Harness />
    </Suspense>
  );
}
