"use client";

/**
 * Harness wizualny kafelka kontraktora z zakładki „Zamówienia".
 *
 * Renderuje PRODUKCYJNY `ContractorOrderCards` (nie kopię) — ten sam
 * komponent, który obsługuje OBA widoki zamówień: jednoosobowy
 * (`OrdersAndContractsTab`) i wielo-konsultantowy (`MultiConsultantOrdersTab`
 * importuje go wprost). Dzięki temu kompaktowość kafelka da się obejrzeć raz,
 * a nie osobno u każdego klienta.
 *
 * Zero zapytań: `ContractorOrderCards` nie ma ani jednego `useQuery` (tylko
 * mutacje, odpalane kliknięciem), więc strona może stać w `PUBLIC_PATHS`.
 *
 * Trzy typy zamówień stoją OBOK SIEBIE, bo ticket wymaga jednego wzorca dla
 * wszystkich; rozjazd między nimi widać wyłącznie w zestawieniu.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { ToastProvider } from "@/components/Toast";
import { ContractorOrderCards } from "@/components/OrdersAndContractsTab";
import type {
  ClientOrderRead,
  ContractWithOrdersRead,
  OrderType,
} from "@/lib/api/dlPortal";

const client = new QueryClient({
  defaultOptions: { queries: { retry: false, staleTime: Infinity } },
});

function order(overrides: Partial<ClientOrderRead> = {}): ClientOrderRead {
  return {
    id: 1,
    client_id: 1,
    contract_id: 466,
    job_id: null,
    framework_contract_id: null,
    title: "9/98/2026/BL",
    description: null,
    status: "active",
    order_type: "periodic",
    start_date: "2026-09-01",
    end_date: "2026-12-31",
    rate_unit: "daily",
    billing_hours_per_month: null,
    rate_candidate: 150,
    rate_client: 1450,
    total_value: null,
    md_quantity: null,
    currency: "PLN",
    rate_client_currency: "PLN",
    rate_candidate_currency: "PLN",
    project_part: null,
    filename: null,
    has_file: false,
    content_type: null,
    size_bytes: null,
    created_by_user_id: null,
    notes: null,
    created_at: "2026-09-01T00:00:00Z",
    updated_at: "2026-09-01T00:00:00Z",
    candidate_id: 5,
    candidate_name: null,
    contract_status: "active",
    job_title: null,
    monthly_margin: null,
    days_to_end: 116,
    ...overrides,
  };
}

function contractor(
  overrides: Partial<ContractWithOrdersRead> = {},
): ContractWithOrdersRead {
  return {
    contract_id: 466,
    candidate_id: 5,
    candidate_name: "Mateusz Wzorcowy",
    contract_status: "active",
    contract_start_date: "2026-09-01",
    contract_end_date: null,
    rate_candidate: 150,
    rate_client_currency: "PLN",
    rate_candidate_currency: "PLN",
    rate_unit: "daily",
    billing_hours_per_month: null,
    initial_job_id: 7,
    initial_job_title: "Administrator systemów",
    latest_order_id: 1,
    latest_order_end_date: "2026-12-31",
    latest_order_rate_client: 1450,
    latest_order_monthly_margin: null,
    days_to_latest_end: 116,
    orders: [order()],
    ...overrides,
  };
}

const CONTRACTORS: ContractWithOrdersRead[] = [
  contractor(),
  contractor({
    contract_id: 468,
    candidate_id: 6,
    candidate_name: "Paweł Fikcyjny",
    rate_candidate: 140,
    initial_job_title: "Inżynier DevOps",
    latest_order_rate_client: 1440,
    orders: [
      order({
        id: 2,
        contract_id: 468,
        order_type: "md",
        rate_candidate: 140,
        rate_client: 1440,
        candidate_id: 6,
      }),
    ],
  }),
  contractor({
    contract_id: 463,
    candidate_id: 7,
    candidate_name: "Anna Wzorcowa",
    rate_candidate: 130,
    initial_job_title: "Analityk biznesowy",
    latest_order_rate_client: 1380,
    orders: [
      order({
        id: 3,
        contract_id: 463,
        order_type: "cost",
        rate_candidate: 130,
        rate_client: 1380,
        candidate_id: 7,
      }),
    ],
  }),
];

/** Data lokalna przesunięta o `days` dni — jak `todayLocalISO` na karcie. */
function isoOffset(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() + days);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/**
 * Komunikaty o zamówieniu kończącym się w najbliższych dniach (zgłoszenie
 * 29.09.2026). Daty liczone od DZIŚ, więc harness zawsze pokazuje „jutro".
 * Wszystkie trzy kafelki mają mówić to samo o zamówieniu, które trwa:
 * „kończy się za 1 dzień" (bez numeru i bez słowa „przyszłe") i mieć przycisk
 * „Zakończ zamówienie"; „przyszłe zamówienie …" tylko przy zamówieniu, które
 * jeszcze się nie zaczęło.
 */
function endingSoonScenarios(): ContractWithOrdersRead[] {
  const running = { start_date: isoOffset(-90), end_date: isoOffset(1) };
  return [
    // Stary wiersz `completed` z importu obok aktywnego wiersza TEGO SAMEGO
    // okresu — API sortuje po starcie, więc martwy wiersz stoi pierwszy.
    contractor({
      contract_id: 479,
      candidate_id: 11,
      candidate_name: "Maria Duplikatowa",
      days_to_latest_end: 1,
      ending_without_successor_order_id: 12,
      ending_without_successor_days: 1,
      orders: [
        order({
          id: 11,
          contract_id: 479,
          candidate_id: 11,
          title: "K/2026/000001/XX/1/26TEST",
          status: "completed",
          ...running,
        }),
        order({
          id: 12,
          contract_id: 479,
          candidate_id: 11,
          title: "K/2026/000001/XX/1/26TEST",
          ...running,
        }),
      ],
    }),
    // Jedno aktywne zamówienie kończące się jutro.
    contractor({
      contract_id: 478,
      candidate_id: 12,
      candidate_name: "Piotr Jutrzejszy",
      days_to_latest_end: 1,
      ending_without_successor_order_id: 13,
      ending_without_successor_days: 1,
      orders: [
        order({
          id: 13,
          contract_id: 478,
          candidate_id: 12,
          title: "K/2026/000002/XX/2/26TEST",
          ...running,
        }),
      ],
    }),
    // Bieżące zamówienie ma kontynuację; PRZYSZŁE samo kończy się za 20 dni.
    contractor({
      contract_id: 480,
      candidate_id: 13,
      candidate_name: "Ewa Następna",
      days_to_latest_end: 20,
      ending_without_successor_order_id: 15,
      ending_without_successor_days: 20,
      orders: [
        order({
          id: 15,
          contract_id: 480,
          candidate_id: 13,
          title: "K/2026/000003/XX/3/26NEXT",
          start_date: isoOffset(5),
          end_date: isoOffset(20),
        }),
        order({
          id: 14,
          contract_id: 480,
          candidate_id: 13,
          title: "K/2026/000003/XX/3/26CUR",
          start_date: isoOffset(-100),
          end_date: isoOffset(4),
        }),
      ],
    }),
  ];
}

/** Kontraktor bez zamówienia — najwyższy wariant kafelka (pas ostrzeżeń). */
const NO_ORDER: ContractWithOrdersRead[] = [
  contractor({
    contract_id: 470,
    candidate_id: 8,
    candidate_name: "Katarzyna Przykładowa-Testowa",
    initial_job_title: "Specjalista ds. bezpieczeństwa informacji",
    latest_order_id: null,
    latest_order_end_date: null,
    latest_order_rate_client: null,
    days_to_latest_end: null,
    orders: [],
  }),
];

function Block({
  title,
  contractors,
  narrow,
}: {
  title: string;
  contractors: ContractWithOrdersRead[];
  narrow?: boolean;
}) {
  return (
    <section className="space-y-2">
      <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </h2>
      <div className={narrow ? "max-w-3xl" : undefined}>
        <ul className="space-y-3">
          <ContractorOrderCards
            clientId={1}
            contractors={contractors}
            canViewFinance
            canManageFinance
            canManageOrders
            suggestedOrderType={"periodic" as OrderType}
            legacyNullOrderType="periodic"
            searching={false}
          />
        </ul>
      </div>
    </section>
  );
}

/** Daty liczone od dziś w przeglądarce — po zamontowaniu, bez rozjazdu SSR. */
function EndingSoonBlock() {
  const [contractors, setContractors] = useState<ContractWithOrdersRead[] | null>(
    null,
  );
  useEffect(() => setContractors(endingSoonScenarios()), []);
  if (!contractors) return null;
  return <Block title="Kończy się jutro (zgłoszenie 29.09.2026)" contractors={contractors} />;
}

export default function OrderTilePreview() {
  return (
    <QueryClientProvider client={client}>
      <ToastProvider>
        <main className="min-h-dvh bg-background p-4 sm:p-8 space-y-8">
          <header className="space-y-1">
            <h1 className="text-lg font-semibold text-foreground">
              Kafelek zamówienia — harness
            </h1>
            <p className="text-sm text-muted-foreground">
              Ten sam kafelek obsługuje zamówienia okresowe, MD i kosztowe u
              wszystkich klientów.
            </p>
          </header>
          <Block title="Trzy typy zamówień" contractors={CONTRACTORS} />
          <EndingSoonBlock />
          <Block title="Bez zamówienia" contractors={NO_ORDER} />
          <Block
            title="Wąski kontener (sprawdzenie zawijania)"
            contractors={CONTRACTORS.slice(0, 1)}
            narrow
          />
        </main>
      </ToastProvider>
    </QueryClientProvider>
  );
}
