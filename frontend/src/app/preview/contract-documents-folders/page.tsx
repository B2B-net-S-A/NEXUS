"use client";

/**
 * Harness wizualny folderów w zakładce Dokumenty kontraktu (0494): sekcja
 * „Aktualna umowa”, foldery (w tym automatyczny „Zamówienia” z PDF-em
 * z zakładki Zamówienia), podpowiedź „Poprzednia umowa” i tryb podglądu.
 *
 * ZERO zapytań: cache react-query zasiany tymi samymi kluczami co komponent,
 * z `updatedAt` w przyszłości. Dane są fikcyjne.
 */

import { useMemo, useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ContractDocumentsTab } from "@/components/ContractDocumentsTab";
import { ToastProvider } from "@/components/Toast";
import type { OrderDocumentItem } from "@/lib/api/dlPortal";
import type {
  ContractDocument,
  DocumentFoldersResponse,
} from "@/lib/contract-document-folders";

const CONTRACT_ID = 900001;
const FUTURE = Date.now() + 365 * 24 * 3600 * 1000;

function doc(
  id: number,
  filename: string,
  doc_type: string,
  extra: Partial<ContractDocument> = {},
): ContractDocument {
  return {
    id,
    contract_id: CONTRACT_ID,
    filename,
    doc_type,
    content_type: "application/pdf",
    size_bytes: 120_000 + id * 7_300,
    expiry_date: null,
    uploaded_by: 1,
    uploaded_by_email: "anna.przykladowa@example.com",
    created_at: "2026-10-01T10:00:00Z",
    folder_id: null,
    ...extra,
  };
}

const DOCUMENTS: ContractDocument[] = [
  doc(1, "Umowa B2B nr 518-2026_Przykładowa Anna.pdf", "contract", {
    expiry_date: "2027-12-31",
  }),
  doc(2, "Aneks nr 1 do umowy 518-2026.pdf", "annex", { created_at: "2026-10-15T10:00:00Z" }),
  doc(3, "Polisa OC 2026–2027.pdf", "oc_policy", { expiry_date: "2027-02-28" }),
  doc(4, "Umowa nr 361-2019_Przykładowa Anna.pdf", "contract", {
    source: "sharepoint",
    created_at: "2026-09-30T10:00:00Z",
  }),
  doc(5, "Aneks nr 1 do umowy 361-2019.pdf", "annex", {
    source: "sharepoint",
    created_at: "2026-09-30T10:00:00Z",
  }),
  doc(6, "wypowiedzenie b2b Przykładowa Anna.pdf", "termination_notice", {
    source: "sharepoint",
    created_at: "2026-09-30T10:00:00Z",
  }),
  doc(7, "Porozumienie o rozwiązaniu umowy nr 361-2019.pdf", "termination_agreement", {
    source: "sharepoint",
    created_at: "2026-09-30T10:00:00Z",
  }),
  doc(8, "Zamówienie ZAM-2026-0801.pdf", "order", {
    source: "sharepoint",
    created_at: "2026-09-30T10:00:00Z",
  }),
  doc(9, "Zamówienie ZAM-2026-0301.pdf", "order", { created_at: "2026-03-04T10:00:00Z" }),
  doc(10, "Dokumenty firmy — NIP.pdf", "nip", {
    folder_id: 31,
    created_at: "2026-08-12T10:00:00Z",
  }),
];

const FOLDERS: DocumentFoldersResponse = {
  folders: [{ id: 31, name: "Dokumenty firmy (NIP, ZUS, OC)", created_at: "2026-10-20T09:00:00Z" }],
  orders_folder_name: "Zamówienia",
  current_contract_number: "518-2026",
  suggestions: [
    {
      number: "361-2019",
      folder_name: "Poprzednia umowa – nr 361-2019",
      folder_id: null,
      document_ids: [4, 5, 6, 7],
    },
  ],
};

const ORDER_FILES: OrderDocumentItem[] = [
  {
    order_id: 4500123456,
    client_id: 1,
    contract_id: CONTRACT_ID,
    title: "ZAM-2026-1001",
    filename: "ZAM-2026-1001.pdf",
    content_type: "application/pdf",
    size_bytes: 244_100,
    created_at: "2026-10-01T10:00:00Z",
    order_status: "active" as OrderDocumentItem["order_status"],
    uploaded_by_email: "zamowienia@example.com",
    uploaded_at: "2026-10-01T10:00:00Z",
  },
];

function seeded(): QueryClient {
  const qc = new QueryClient({
    defaultOptions: { queries: { staleTime: Infinity, retry: false } },
  });
  const opts = { updatedAt: FUTURE };
  qc.setQueryData(["contract-documents", CONTRACT_ID], DOCUMENTS, opts);
  qc.setQueryData(["contract-document-folders", CONTRACT_ID], FOLDERS, opts);
  qc.setQueryData(["order-documents", CONTRACT_ID, null], ORDER_FILES, opts);
  return qc;
}

export default function ContractDocumentsFoldersPreview() {
  const client = useMemo(seeded, []);
  const [readOnly, setReadOnly] = useState(false);
  return (
    <QueryClientProvider client={client}>
      <ToastProvider>
        <main className="min-h-dvh bg-background p-6">
          <div className="mx-auto max-w-6xl space-y-4">
            <div className="flex items-center justify-between">
              <h1 className="text-lg font-semibold">Anna Przykładowa · Bank Przykładowy</h1>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={readOnly}
                  onChange={(e) => setReadOnly(e.target.checked)}
                />
                Tryb podglądu (bez zapisu)
              </label>
            </div>
            <ContractDocumentsTab contractId={CONTRACT_ID} readOnly={readOnly} />
          </div>
        </main>
      </ToastProvider>
    </QueryClientProvider>
  );
}
