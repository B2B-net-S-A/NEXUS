"use client";

/**
 * Harness wizualny Finanse → „Zamówienia PDF".
 *
 * Renderuje produkcyjny `OrderPdfsPanel` na zahardkodowanych danych — bez
 * react-query i bez żadnego zapytania, więc strona może stać w
 * `PUBLIC_PATHS`. Dane są fikcyjne; „Pobierz" i ZIP-y niczego nie pobierają,
 * a podgląd czyta plik statyczny harnessu `/preview/cv-search` (nie API).
 */

import { useState } from "react";

import { OrderPdfsPanel } from "@/components/finance/OrderPdfsPanel";
import type { OrderPdfClient, OrderPdfMonth } from "@/lib/api/finance";

const MONTHS: OrderPdfMonth[] = [
  { month: "2026-10", clients: 1, files: 1 },
  { month: "2026-09", clients: 2, files: 4 },
  { month: "2026-08", clients: 3, files: 7 },
];

const CLIENTS: Record<string, OrderPdfClient[]> = {
  "2026-09": [
    {
      client_id: 1,
      client_name: "Bank Przykładowy S.A.",
      files: [
        {
          kind: "order",
          id: 11,
          download_name: "zamowienie_alior_Nowak_15.09.2026-31.12.2026.pdf",
          original_name: "zamowienie_alior.pdf",
          consultant_name: "Jan Nowak",
          start: "2026-09-15",
          end: "2026-12-31",
          entry_type: "new",
          status: "active",
          order_number: "OIT/0189/2026",
          uploaded_at: "2026-09-10T09:00:00Z",
          downloaded_at: null,
          pending_change: true,
        },
        {
          kind: "group",
          id: 21,
          download_name: "PO_445_01.09.2026-30.11.2026.pdf",
          original_name: "PO_445.pdf",
          consultant_name: null,
          start: "2026-09-01",
          end: "2026-11-30",
          entry_type: "extension",
          status: "active",
          order_number: "445",
          uploaded_at: "2026-09-02T09:00:00Z",
          downloaded_at: "2026-09-22T08:30:00Z",
        },
        {
          kind: "amendment",
          id: 31,
          download_name: "aneks_2_Kowalska_01.09.2026-bezterminowo.pdf",
          original_name: "aneks_2.pdf",
          consultant_name: "Anna Kowalska",
          start: "2026-09-01",
          end: null,
          entry_type: "amendment",
          status: null,
          order_number: null,
          uploaded_at: "2026-08-28T09:00:00Z",
        },
      ],
    },
    {
      client_id: 2,
      client_name: "Telekom Demo",
      files: [
        {
          kind: "order",
          id: 12,
          download_name: "zlecenie_Wiśniewski_01.09.2026-31.10.2026.pdf",
          original_name: "zlecenie.pdf",
          consultant_name: "Piotr Wiśniewski",
          start: "2026-09-01",
          end: "2026-10-31",
          entry_type: "new",
          status: "draft",
          order_number: "SAP 4500123456",
          uploaded_at: "2026-08-30T09:00:00Z",
        },
      ],
    },
  ],
};

export default function FinanceOrderPdfsPreview() {
  const [month, setMonth] = useState<string>("2026-09");
  const [clientId, setClientId] = useState<number | null>(1);

  return (
    <div className="mx-auto max-w-[1400px] space-y-4 p-4 sm:p-6">
      <h1 className="text-lg font-semibold">Zamówienia PDF — podgląd</h1>
      <OrderPdfsPanel
        months={MONTHS}
        month={month}
        onMonthChange={(next) => {
          setMonth(next);
          setClientId(null);
        }}
        clients={CLIENTS[month] ?? []}
        clientId={clientId}
        onClientChange={setClientId}
        onDownload={() => undefined}
        downloadingKey={null}
        onDownloadMonth={() => undefined}
        onDownloadClient={() => undefined}
        onDownloadFiles={() => undefined}
        zipBusy={null}
        loadPdf={async () => {
          const response = await fetch("/preview/cv-search/cv-tekst.pdf");
          if (!response.ok) throw new Error("brak pliku");
          return response.blob();
        }}
      />
    </div>
  );
}
