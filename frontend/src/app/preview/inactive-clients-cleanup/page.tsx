"use client";

/**
 * Harness designu jednorazowego czyszczenia „Nieaktywnych klientów".
 *
 * Renderuje PRAWDZIWE widoki z `InactiveClientsCleanupDialog` (podgląd,
 * stopkę z potwierdzeniem i raport), ale bez okna i bez react-query — dane są
 * stałymi poniżej, więc strona nie wysyła ANI JEDNEGO zapytania. To warunek
 * wejścia do `PUBLIC_PATHS` w middleware.ts.
 *
 * Stany obok siebie, bo ich różnice łatwo zepsuć niezauważenie: podgląd
 * (nic jeszcze nie zmieniono, przycisk usunięcia wymaga zgody) i raport
 * (lista A: usunięci, lista B: wstrzymani z powodem).
 */

import { useState } from "react";

import {
  InactiveCleanupConfirm,
  InactiveCleanupPreviewView,
  InactiveCleanupReportView,
} from "@/components/clients/InactiveClientsCleanupDialog";
import type {
  InactiveCleanupPreview,
  InactiveCleanupReport,
} from "@/lib/api";

const SOURCE_LABELS = {
  active_projects: "Aktywne projekty",
  closed_projects: "Zamknięte projekty",
  archived_consultants: "Archiwalni konsultanci",
  orders: "Zamówienia",
  contracts: "Umowy / kontrakty",
  notes: "Notatki w profilu",
  sales_materials: "Materiały sprzedażowe",
  cooperation_stats: "Statystyki współpracy",
};

const HELD = [
  {
    client_id: 204,
    name: "Grupa Przykładowa S.A.",
    nip: "1234567890",
    external_source: "traffit",
    external_id: "1187",
    sources: [],
    reasons: [
      {
        code: "foreign_key",
        label: "Kontakty (osoby po stronie klienta)",
        count: 3,
        table: "contacts",
        effect: "blokują usunięcie",
      },
      {
        code: "foreign_key",
        label: "Przypisani TAC",
        count: 1,
        table: "client_tac_assignments",
        effect: "zostałyby usunięte razem z klientem",
      },
    ],
  },
  {
    client_id: 311,
    name: "Fabryka Testowa Sp. z o.o.",
    sources: [],
    reasons: [
      {
        code: "activity",
        label: "Wpisy w dzienniku aktywności klienta",
        count: 2,
        details: ["usunięcie one-pagera", "wgranie wymaganego dokumentu"],
        effect: "zostałyby w dzienniku bez klienta",
      },
    ],
  },
  {
    client_id: 412,
    name: "Holding Dwie Zakładki",
    sources: [],
    reasons: [
      {
        code: "other_portfolio_tab",
        label: "Klient ma też zakres w zakładce: Aktywni",
        count: 1,
        effect: "zniknąłby także z tamtej zakładki",
      },
    ],
  },
];

const PREVIEW: InactiveCleanupPreview = {
  evaluated_at: "2026-09-10T10:00:00+00:00",
  candidates_count: 9,
  to_delete: [
    {
      client_id: 101,
      name: "Pusty Klient Sp. z o.o.",
      external_source: "traffit",
      external_id: "1043",
      sources: [],
      reasons: [],
    },
    {
      client_id: 102,
      name: "Stary Prospekt S.A.",
      nip: "9876543210",
      sources: [],
      reasons: [],
    },
    {
      client_id: 103,
      name: "Zapomniana Firma",
      sources: [],
      reasons: [],
    },
  ],
  held: HELD,
  kept: [
    {
      client_id: 501,
      name: "Bank Historyczny S.A.",
      sources: [
        { code: "closed_projects", label: "Zamknięte projekty", count: 14 },
        { code: "contracts", label: "Umowy / kontrakty", count: 6 },
      ],
      reasons: [],
    },
    {
      client_id: 502,
      name: "Ubezpieczenia Dawne",
      sources: [{ code: "notes", label: "Notatki w profilu", count: 1 }],
      reasons: [],
    },
    {
      client_id: 503,
      name: "Telekom Archiwalny",
      sources: [
        { code: "orders", label: "Zamówienia", count: 2 },
        { code: "archived_consultants", label: "Archiwalni konsultanci", count: 2 },
      ],
      reasons: [],
    },
  ],
  kept_by_source: {
    active_projects: 0,
    closed_projects: 1,
    archived_consultants: 1,
    orders: 1,
    contracts: 1,
    notes: 1,
    sales_materials: 0,
    cooperation_stats: 0,
  },
  source_labels: SOURCE_LABELS,
};

const REPORT: InactiveCleanupReport = {
  run_id: 1,
  executed_at: "2026-09-10T10:05:00+00:00",
  executed_by_name: "Administrator Portfela",
  candidates_count: 9,
  kept_count: 3,
  deleted_count: 3,
  held_count: 3,
  deleted: PREVIEW.to_delete.map((client) => ({
    client_id: client.client_id,
    name: client.name,
    nip: client.nip ?? null,
    external_source: client.external_source ?? null,
    external_id: client.external_id ?? null,
    purged_at: "2026-09-10T10:05:00+00:00",
  })),
  held: HELD,
  summary: {},
};

export default function InactiveClientsCleanupPreviewPage() {
  const [acknowledged, setAcknowledged] = useState(false);
  return (
    <main className="min-h-screen bg-background p-6">
      <h1 className="mb-1 text-xl font-bold text-foreground">
        Czyszczenie nieaktywnych klientów — harness
      </h1>
      <p className="mb-6 text-sm text-muted-foreground">
        Te same widoki co w oknie z zakładki „Nieaktywni klienci”, bez sieci.
      </p>
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <section
          aria-label="Podgląd"
          className="flex flex-col rounded-xl border border-border bg-card"
        >
          <h2 className="border-b border-border px-6 py-4 text-base font-semibold text-foreground">
            1. Podgląd (nic jeszcze nie zmieniono)
          </h2>
          <div className="px-6 py-4">
            <InactiveCleanupPreviewView preview={PREVIEW} />
          </div>
          <div className="mt-auto flex flex-wrap items-center justify-end gap-2 border-t border-border px-6 py-4">
            <InactiveCleanupConfirm
              deleteCount={PREVIEW.to_delete.length}
              acknowledged={acknowledged}
              executing={false}
              onAcknowledgedChange={setAcknowledged}
              onCancel={() => setAcknowledged(false)}
              onExecute={() => undefined}
            />
          </div>
        </section>
        <section
          aria-label="Raport"
          className="rounded-xl border border-border bg-card"
        >
          <h2 className="border-b border-border px-6 py-4 text-base font-semibold text-foreground">
            2. Raport po wykonaniu
          </h2>
          <div className="px-6 py-4">
            <InactiveCleanupReportView report={REPORT} />
          </div>
        </section>
      </div>
    </main>
  );
}
