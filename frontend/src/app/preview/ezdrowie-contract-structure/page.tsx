"use client";

/**
 * Harness designu „Struktura umów" Centrum e-Zdrowia (ticket 09.2026):
 * sekcja umów ramowych → wykonawczych z panelem przeglądu oraz fragment
 * „Obecnych konsultantów" z filtrem po umowie wykonawczej.
 *
 * Renderuje PRAWDZIWE komponenty, ale nie rusza sieci: cache react-query jest
 * zasiany z góry dla KAŻDEGO klucza, po który sięgają hooki (struktura,
 * przegląd, profil), a domyślny `queryFn` odrzuca lokalnie — klucz pominięty
 * przez pomyłkę nie poleci do API (401 → przekierowanie na /login zabrałoby
 * publiczny podgląd oglądającemu z ekranu). Osoby i numery są zmyślone.
 *
 * Przyciski „Dodaj umowę wykonawczą" / „Przypisz" wołają PRAWDZIWE API —
 * w harnessie nie klikaj ich, pokrywają je testy jednostkowe.
 */

import { useMemo, useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ToastProvider } from "@/components/Toast";
import { ContractStructureSection } from "@/components/client-profile/ContractStructureSection";
import {
  ConsultantsTable,
  toConsultantRow,
} from "@/components/client-profile/ConsultantsTable";
import { ExecutiveContractFilter } from "@/components/client-profile/ExecutiveContractFilter";
import {
  contractStructureQueryKey,
  executiveContractReviewQueryKey,
  type ContractStructureResponse,
  type ExecutiveContractBrief,
  type ExecutiveContractReviewResponse,
} from "@/lib/api/executiveContracts";
import {
  EZDROWIE_CLIENT_ID,
  filterConsultantsByExecutiveContract,
  type ConsultantAssignmentFilter,
} from "@/lib/ezdrowie";
import type { ActiveConsultantItem, ClientProfileResponse } from "@/types/client-profile";

const UW_CZ2_1: ExecutiveContractBrief = {
  id: 10,
  number: "CeZ/145/2025/UW-1",
  status: "active",
  framework_contract_id: 2,
  project_part: "cz2",
};
const UW_CZ2_2: ExecutiveContractBrief = {
  id: 11,
  number: "CeZ/145/2025/UW-2",
  status: "ended",
  framework_contract_id: 2,
  project_part: "cz2",
};
const UW_CZ4_1: ExecutiveContractBrief = {
  id: 12,
  number: "CeZ/147/2025/UW-1",
  status: "active",
  framework_contract_id: 4,
  project_part: "cz4",
};

// Pięć części; dwie z umowami wykonawczymi, trzy bez — obie gałęzie widoku.
const STRUCTURE: ContractStructureResponse = {
  framework_contracts: [
    { id: 1, name: "CeZ/144/2025 – cz. I", project_part: "cz1", status: "active", executive_contracts: [] },
    {
      id: 2,
      name: "CeZ/145/2025 – cz. II",
      project_part: "cz2",
      status: "active",
      executive_contracts: [
        { ...UW_CZ2_1, notes: "Zespół wdrożeniowy P1", consultants_count: 2, created_at: "2026-09-01T09:00:00Z" },
        { ...UW_CZ2_2, notes: null, consultants_count: 0, created_at: "2026-03-01T09:00:00Z" },
      ],
    },
    {
      id: 4,
      name: "CeZ/147/2025 – cz. IV",
      project_part: "cz4",
      status: "active",
      executive_contracts: [
        { ...UW_CZ4_1, notes: null, consultants_count: 1, created_at: "2026-09-10T09:00:00Z" },
      ],
    },
    { id: 5, name: "CeZ/148/2025 – cz. V", project_part: "cz5", status: "active", executive_contracts: [] },
    { id: 6, name: "CeZ/149/2025 – cz. VI", project_part: "cz6", status: "active", executive_contracts: [] },
  ],
};

function consultant(
  contractId: number,
  name: string,
  executive: ExecutiveContractBrief | null,
  legacyPart: string | null,
): ActiveConsultantItem {
  return {
    contract_id: contractId,
    candidate: { id: contractId, name, avatar_url: null, competence_category: null, linkedin: null },
    job_id: null,
    job_title: "Analityk systemowy",
    job_from_order: true,
    start_date: "2026-04-01",
    end_date: null,
    days_to_end: null,
    monthly_rate_client: 24000,
    monthly_rate_candidate: 18000,
    monthly_margin: 6000,
    hourly_rate_client: 150,
    hourly_rate_candidate: 112.5,
    currency: "PLN",
    project_part: executive?.project_part ?? legacyPart,
    executive_contract: executive,
  };
}

const ACTIVE: ActiveConsultantItem[] = [
  consultant(701, "Osoba Pierwsza", UW_CZ2_1, null),
  consultant(702, "Osoba Druga", UW_CZ2_1, null),
  consultant(703, "Osoba Trzecia", UW_CZ4_1, null),
  // Legacy: część wpisana ręcznie sprzed struktury — do przeglądu.
  consultant(704, "Osoba Czwarta", null, "cz2"),
  consultant(705, "Osoba Piąta", null, "cz5"),
];

const PROFILE: ClientProfileResponse = {
  summary: {
    open_jobs: 0,
    active_consultants: ACTIVE.length,
    active_contracts: ACTIVE.length,
    total_placements: 12,
    active_mrr: 30000,
    ltv: 900000,
    avg_time_to_fill_days: 21,
  },
  open_jobs: [],
  active_consultants: ACTIVE,
  planned_consultants: [],
  historical: { placements: [], lost_jobs: [] },
};

const REVIEW: ExecutiveContractReviewResponse = {
  rows: [
    {
      contract_id: 704,
      candidate: { id: 704, name: "Osoba Czwarta" },
      start_date: "2026-04-01",
      bucket: "active",
      legacy_project_part: "cz2",
      representative_order_id: 9001,
      suggested_framework_contract_id: 2,
    },
    {
      contract_id: 705,
      candidate: { id: 705, name: "Osoba Piąta" },
      start_date: "2026-04-01",
      bucket: "active",
      legacy_project_part: "cz5",
      representative_order_id: 9002,
      // Część V nie ma umowy wykonawczej — brak podpowiedzi.
      suggested_framework_contract_id: null,
    },
  ],
  total: 2,
};

function Case({ id, title, children }: { id: string; title: string; children: React.ReactNode }) {
  return (
    <section data-testid={id} className="rounded-xl border border-dashed border-border p-4">
      <h2 className="mb-3 text-xs font-bold uppercase tracking-wide text-muted-foreground">
        {title}
      </h2>
      {children}
    </section>
  );
}

function ConsultantsWithFilter() {
  const [filter, setFilter] = useState<ConsultantAssignmentFilter>("all");
  const filtered = filterConsultantsByExecutiveContract(ACTIVE, filter);
  return (
    <div className="space-y-3">
      <ExecutiveContractFilter
        clientId={EZDROWIE_CLIENT_ID}
        consultants={ACTIVE}
        value={filter}
        onChange={setFilter}
      />
      <p className="text-xs text-muted-foreground">
        Obecni konsultanci: {filtered.length} / {ACTIVE.length}
      </p>
      {filtered.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">
          Brak konsultantów spełniających wybrane kryteria.
        </p>
      ) : (
        <ConsultantsTable rows={filtered.map(toConsultantRow)} />
      )}
    </div>
  );
}

export default function EzdrowieContractStructurePreviewPage() {
  const queryClient = useMemo(() => {
    const qc = new QueryClient({
      defaultOptions: {
        queries: {
          staleTime: Infinity,
          retry: false,
          retryOnMount: false,
          refetchOnMount: false,
          queryFn: () => Promise.reject(new Error("podgląd: brak zasianych danych")),
        },
      },
    });
    const updatedAt = Date.now() + 24 * 60 * 60 * 1000;
    qc.setQueryData(contractStructureQueryKey(EZDROWIE_CLIENT_ID), STRUCTURE, { updatedAt });
    qc.setQueryData(executiveContractReviewQueryKey(EZDROWIE_CLIENT_ID), REVIEW, { updatedAt });
    qc.setQueryData(["client-profile", EZDROWIE_CLIENT_ID], PROFILE, { updatedAt });
    return qc;
  }, []);

  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <main className="mx-auto flex max-w-5xl flex-col gap-8 p-8">
          <header>
            <h1 className="text-lg font-semibold">Centrum e-Zdrowia — struktura umów wykonawczych</h1>
            <p className="text-sm text-muted-foreground">
              Umowa ramowa (część) → umowy wykonawcze; konsultant przypisany do umowy
              wykonawczej. Mocki, zero zapytań — przyciski zapisu wołałyby prawdziwe API.
            </p>
          </header>

          <Case id="structure" title="Sekcja „Struktura umów” + przypisania do przeglądu">
            <ContractStructureSection clientId={EZDROWIE_CLIENT_ID} />
          </Case>

          <Case id="consultants" title="Obecni konsultanci — filtr po umowie wykonawczej">
            <ConsultantsWithFilter />
          </Case>
        </main>
      </ToastProvider>
    </QueryClientProvider>
  );
}
