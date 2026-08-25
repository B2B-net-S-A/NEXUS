"use client";

/**
 * Harness wizualny konsolidacji kontraktorów wieloklientowych — bez API i bez
 * logowania (wzorzec `preview/dl-alerts`): produkcyjne komponenty + ZASIANY
 * cache react-query, żeby żaden `queryFn` nigdy nie wystartował (niezasiany
 * klucz → 401 → redirect na /login, patrz pamięć projektu).
 *
 * Pokazuje obok siebie:
 * 1. Zgrupowaną listę kontraktów (jedna osoba × N klientów w jednym wierszu,
 *    kolumny „Stawka kosztowa"/„Stawka przychodowa", rozbicie per klient),
 * 2. Dialog „+ Dodaj kolejny projekt" (walidacja: klient wymagany).
 *
 * Auth: zustand store dostaje admina z view_finance — komponenty czytają rolę
 * z tego samego store'a co produkcja, więc kolumny finansowe się renderują.
 *
 * UWAGA: harness gwarantuje zero requestów przy ŁADOWANIU (wszystkie zapytania
 * zasiane). Kliknięcie „Dodaj projekt" z wybranym klientem wykonałoby jednak
 * prawdziwy POST /api/contracts (mutacja, nie query) i skończyło się 401 —
 * dialog służy tu do oglądania WALIDACJI (zapis bez klienta), nie do zapisu.
 */

import { useEffect, useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ContractsListV2 } from "@/components/v2/pages/ContractsListV2";
import { AddProjectDialog } from "@/components/contracts/AddProjectDialog";
import { ToastProvider } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { useAuthStore } from "@/store/auth";

const member = (over: Record<string, unknown>) => ({
  client_name: null,
  job_title: null,
  start_date: "2026-07-01",
  end_date: "2026-09-30",
  latest_order_end_date: null,
  contract_type: "b2b",
  rate_candidate: 125,
  rate_client: 175,
  margin: 50,
  rate_unit: "hourly",
  currency: "PLN",
  status: "active",
  ...over,
});

const LIST_PAYLOAD = {
  items: [
    {
      id: 467,
      candidate_id: 10,
      candidate_name: "Paweł Małek",
      client_name: "Bank Pocztowy",
      job_title: null,
      status: "ended",
      contract_type: "b2b",
      start_date: "2026-07-01",
      end_date: "2026-09-30",
      rate_candidate: 125,
      rate_client: 175,
      margin: 50,
      currency: "PLN",
      group_members: [
        member({
          id: 512,
          client_id: 2,
          client_name: "VeloBank",
          rate_candidate: 120,
          rate_client: 162.5,
          margin: 42.5,
          end_date: null,
          job_title: "Tester Mobile",
        }),
        member({
          id: 467,
          client_id: 1,
          client_name: "Bank Pocztowy",
          status: "ended",
        }),
      ],
    },
    {
      id: 300,
      candidate_id: 11,
      candidate_name: "Jakub Jedynak",
      client_name: "CARDIF - ASSURANCES RISQUES DIVERS",
      job_title: "Tester Mobile",
      status: "active",
      contract_type: "b2b",
      start_date: "2026-04-27",
      end_date: "2026-12-31",
      rate_candidate: 100,
      rate_client: 140,
      margin: 40,
      currency: "PLN",
      group_members: [
        member({
          id: 300,
          client_id: 3,
          client_name: "CARDIF - ASSURANCES RISQUES DIVERS",
          rate_candidate: 100,
          rate_client: 140,
          margin: 40,
          job_title: "Tester Mobile",
        }),
      ],
    },
  ],
  total: 2,
  page: 1,
  page_size: 20,
};

function seededClient(): QueryClient {
  const qc = new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: Infinity,
        retry: false,
        refetchOnMount: false,
        refetchOnWindowFocus: false,
      },
    },
  });
  // Klucz MUSI odpowiadać temu z komponentu (debouncedSearch="", filtry puste,
  // endingSoon=false, page=1) — inaczej queryFn wystartuje i strzeli w API.
  qc.setQueryData(["contracts-v2", "", [], [], false, 1], LIST_PAYLOAD);
  qc.setQueryData(["contracts-expiring-v2"], []);
  qc.setQueryData(
    ["clients-lookup-add-project"],
    [
      { id: 1, name: "Bank Pocztowy" },
      { id: 2, name: "VeloBank" },
      { id: 3, name: "CARDIF - ASSURANCES RISQUES DIVERS" },
    ],
  );
  for (const cid of ["1", "2", "3"]) {
    qc.setQueryData(
      ["add-project-jobs", cid],
      [{ id: 11, title: "Tester Mobile" }],
    );
  }
  return qc;
}

export default function ContractsConsolidationPreview() {
  const [ready, setReady] = useState(false);
  const [qc] = useState(seededClient);
  const [dialogOpen, setDialogOpen] = useState(true);

  useEffect(() => {
    // Komponenty czytają rolę z produkcyjnego store'a — zasilamy go adminem
    // z view_finance, żeby kolumny stawek były widoczne na zrzucie.
    useAuthStore.setState({
      user: {
        id: 1,
        email: "preview@example.com",
        name: "Preview Admin",
        role: "admin",
        roles: ["admin"],
        profile_completed: true,
        profile_completed_at: null,
        force_password_change: false,
        force_password_change_at: null,
        capabilities: ["view_finance", "contract.create"],
        analytics_capabilities: ["view_finance"],
      } as never,
      hydrated: true,
    });
    setReady(true);
  }, []);

  if (!ready) {
    return <div className="p-8 text-sm text-muted-foreground">Ładowanie…</div>;
  }

  return (
    <ToastProvider>
      <QueryClientProvider client={qc}>
        <div className="min-h-screen bg-background p-6 space-y-10">
          <section>
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              1. Lista kontraktów — jeden wiersz na osobę (Paweł Małek: Bank
              Pocztowy + VeloBank)
            </h2>
            <ContractsListV2 />
          </section>

          <section>
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              2. Dialog „+ Dodaj kolejny projekt” (Klient wymagany — spróbuj
              zapisać bez klienta)
            </h2>
            <Button size="sm" variant="outline" onClick={() => setDialogOpen(true)}>
              Otwórz dialog
            </Button>
            <AddProjectDialog
              open={dialogOpen}
              onOpenChange={setDialogOpen}
              candidateId={10}
              candidateName="Paweł Małek"
              canManageFinance
              baseContract={{
                id: 467,
                client_id: 1,
                contract_type: "b2b",
                rate_unit: "hourly",
                currency: "PLN",
                billing_hours_per_month: 160,
                work_mode: "remote",
              }}
            />
          </section>
        </div>
      </QueryClientProvider>
    </ToastProvider>
  );
}
