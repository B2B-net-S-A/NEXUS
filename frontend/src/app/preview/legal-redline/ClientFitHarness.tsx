"use client";

/**
 * Sekcja harnessu asystenta prawnego: panel „Sprawdzone z umową ramową
 * <klient> i przepisami” (część G) we wszystkich stanach i okno szczegółów.
 * ZERO zapytań: własny QueryClient z zasianymi odpowiedziami, świeżymi na
 * zawsze; „Dodaj do treści aneksu” dopisuje do lokalnej listy zmian.
 * Limit harnessów (`preview-harness-limit.test.ts`) nie pozwala na osobną
 * stronę, więc sekcja stoi pod „Popraw dokument”.
 */

import { useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ClientFitPanel } from "@/components/legal-assistant/client-fit/ClientFitPanel";
import type { AnnexChangeRow } from "@/lib/api/b2bDocuments";
import { legalClientFitKeys } from "@/lib/api/legalClientFit";
import { annexHasText, appendAnnexText } from "@/lib/legal-client-fit";

import { CLIENT_FIT_SCENARIOS } from "./client-fit-fixtures";

function seededClient(): QueryClient {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
  });
  const forever = Date.now() + 1000 * 60 * 60 * 24 * 365;
  for (const scenario of CLIENT_FIT_SCENARIOS) {
    client.setQueryData(legalClientFitKeys.client(scenario.data.client_id), scenario.data, {
      updatedAt: forever,
    });
  }
  return client;
}

export function ClientFitHarness() {
  const [queryClient] = useState(seededClient);
  const [rows, setRows] = useState<AnnexChangeRow[]>([]);
  return (
    <QueryClientProvider client={queryClient}>
      <section className="space-y-4 border-t border-border pt-4" aria-label="Zgodność z umową ramową klienta">
        <h2 className="text-[15px] font-semibold">Zgodność z umową ramową klienta (część G)</h2>
        {CLIENT_FIT_SCENARIOS.map((scenario, index) => (
          <div key={scenario.data.client_id} className="space-y-1.5">
            <p className="text-[12px] font-medium uppercase tracking-[0.06em] text-muted-foreground">
              {scenario.label}
            </p>
            <ClientFitPanel
              clientId={scenario.data.client_id}
              poll={false}
              onAddToAnnex={
                index === 0 ? (text) => setRows((prev) => appendAnnexText(prev, text)) : undefined
              }
              isAdded={(text) => annexHasText(rows, text)}
              addHint="Treść z luki dopiszesz w aneksie „inna zmiana” (Aneks — inna zmiana)."
            />
          </div>
        ))}
        <div className="rounded-lg border border-dashed border-border p-3 text-[12.5px]">
          <p className="font-medium">Lista zmian aneksu „inna zmiana” (harness)</p>
          {rows.length ? (
            <ol className="mt-1 list-decimal space-y-1 pl-5 text-muted-foreground">
              {rows.map((row) => (
                <li key={row.text}>{row.text}</li>
              ))}
            </ol>
          ) : (
            <p className="mt-1 text-muted-foreground">Pusta — kliknij „Dodaj do treści aneksu”.</p>
          )}
        </div>
      </section>
    </QueryClientProvider>
  );
}
