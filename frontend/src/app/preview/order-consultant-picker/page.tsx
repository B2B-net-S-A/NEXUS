"use client";

/**
 * Harness designu pickera konsultanta (linia zamówienia wielo-konsultantowego).
 *
 * Renderuje PRAWDZIWY `ConsultantPicker`, ale przy renderze nie rusza sieci:
 * cache react-query jest zasiany z góry (`setQueryData` + `staleTime:
 * Infinity`), więc żaden `queryFn` się nie odpala. To warunek wejścia do
 * `PUBLIC_PATHS` w middleware.ts — stronę otwiera nightly Playwright bez sesji.
 *
 * Cztery stany obok siebie, bo ich różnice łatwo zepsuć niezauważenie:
 * scalona lista dwóch źródeł, wybrana osoba spoza rekrutacji, PUSTY WYNIK
 * (który nie może wyglądać jak awaria) i lista przycięta limitem (która nie
 * może wyglądać jak komplet).
 *
 * Wpisanie czegokolwiek w pole wyszukiwania pyta o klucz, którego nikt nie
 * zasiał, więc picker faktycznie strzela do API i — bez sesji — pokazuje gałąź
 * awarii. To jest cecha, nie usterka: piąty stan, który MUSI wyglądać inaczej
 * niż pusty wynik obok.
 */

import { useMemo, useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ConsultantPicker } from "@/components/client-profile/orders/ConsultantPicker";
import type { ConsultantOption } from "@/lib/api/orderGroups";

const FROM_CLIENT: ConsultantOption[] = [
  {
    candidate_id: 2,
    contract_id: 100,
    full_name: "Barbara Nowak",
    first_name: "Barbara",
    last_name: "Nowak",
    source: "client_recruitment",
    source_label: "Rekrutacja u klienta",
    job_title: "Analityk danych",
    suggested_rate_cost: 560,
    has_different_client_contract_rates: true,
  },
  {
    candidate_id: 4,
    contract_id: 101,
    full_name: "Łukasz Żółw",
    first_name: "Łukasz",
    last_name: "Żółw",
    source: "client_recruitment",
    source_label: "Rekrutacja u klienta",
    job_title: "Inżynier DevOps",
    suggested_rate_cost: 700,
    has_different_client_contract_rates: false,
  },
];

const FROM_BASE: ConsultantOption[] = [
  {
    candidate_id: 1,
    contract_id: null,
    full_name: "Adam Zieliński",
    first_name: "Adam",
    last_name: "Zieliński",
    source: "nexus_base",
    source_label: "Baza Nexus",
    job_title: null,
    suggested_rate_cost: null,
    has_different_client_contract_rates: false,
  },
  {
    candidate_id: 3,
    contract_id: null,
    full_name: "Celina Wójcik",
    first_name: "Celina",
    last_name: "Wójcik",
    source: "nexus_base",
    source_label: "Baza Nexus",
    job_title: null,
    suggested_rate_cost: null,
    has_different_client_contract_rates: false,
  },
];

// Kolejność jak z serwera: alfabetycznie po imieniu, oba źródła przemieszane.
const MERGED = [FROM_BASE[0], FROM_CLIENT[0], FROM_BASE[1], FROM_CLIENT[1]];

const CASES: Array<{ id: number; title: string; note: string }> = [
  {
    id: 1,
    title: "Jedna lista, dwa źródła",
    note: "Etykieta przy każdym nazwisku; kolejność alfabetyczna po imieniu.",
  },
  {
    id: 2,
    title: "Wybrana osoba z bazy Nexus",
    note: "Wybór z obu źródeł działa tak samo — różni się tylko etykieta.",
  },
  {
    id: 3,
    title: "Brak wyników",
    note: "Pustka MUSI być odróżnialna od awarii pobrania.",
  },
  {
    id: 4,
    title: "Lista przycięta limitem",
    note: "Bez licznika przycięta lista czyta się jako komplet.",
  },
];

function Case({ id, children }: { id: number; children: React.ReactNode }) {
  const meta = CASES.find((c) => c.id === id)!;
  return (
    <section className="flex flex-col gap-2 rounded-lg border border-border bg-card p-4">
      <h2 className="text-sm font-semibold text-foreground">{meta.title}</h2>
      <p className="text-xs text-muted-foreground">{meta.note}</p>
      {children}
    </section>
  );
}

export default function OrderConsultantPickerPreview() {
  const [selected, setSelected] = useState<ConsultantOption | null>(FROM_BASE[0]);

  const queryClient = useMemo(() => {
    const qc = new QueryClient({
      defaultOptions: {
        queries: { staleTime: Infinity, retry: false, refetchOnMount: false },
      },
    });
    const key = (clientId: number) => [
      "order-line-consultant-options",
      clientId,
      "",
    ];
    qc.setQueryData(key(1), { options: MERGED, total: MERGED.length });
    // Także dla „wybranej osoby": po kliknięciu „Zmień" picker odsłania listę
    // i bez zasianego wpisu poleciałby po nią do API — czego ten harness
    // obiecuje nie robić.
    qc.setQueryData(key(2), { options: MERGED, total: MERGED.length });
    qc.setQueryData(key(3), { options: [], total: 0 });
    qc.setQueryData(key(4), { options: MERGED, total: 137 });
    return qc;
  }, []);

  return (
    <QueryClientProvider client={queryClient}>
      <main className="mx-auto flex max-w-3xl flex-col gap-4 p-6">
        <header>
          <h1 className="text-lg font-semibold text-foreground">
            Picker konsultanta — linia zamówienia
          </h1>
          <p className="text-xs text-muted-foreground">
            Harness designu. Wyłącznie zahardkodowane mocki, zero wywołań API.
          </p>
        </header>

        <Case id={1}>
          <ConsultantPicker clientId={1} value={null} onChange={() => {}} />
        </Case>

        <Case id={2}>
          <ConsultantPicker
            clientId={2}
            value={selected}
            onChange={setSelected}
          />
        </Case>

        <Case id={3}>
          <ConsultantPicker clientId={3} value={null} onChange={() => {}} />
        </Case>

        <Case id={4}>
          <ConsultantPicker clientId={4} value={null} onChange={() => {}} />
        </Case>
      </main>
    </QueryClientProvider>
  );
}
