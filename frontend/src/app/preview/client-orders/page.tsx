"use client";

/**
 * Harness zakładki „Zamówienia" profilu klienta (wersja B, 29.09.2026) —
 * PRODUKCYJNY `MultiConsultantOrdersTab` (tabela MD → Kosztowe → Okresowe
 * z panelem szczegółów) dla fikcyjnego klienta 18.
 *
 * Zero zapytań: cache react-query zasiany z góry (`staleTime: Infinity`),
 * a przechwytujący `axios` odrzuca każde żądanie, które mimo to by wyszło
 * (np. zapis z okna otwartego w podglądzie). Użytkownik w store to fikcyjny
 * admin z finansami — widać stawki i wszystkie akcje.
 *
 * `?group=<id>`, `?order=<id>`, `?contract=<id>` otwierają od wejścia panel
 * zamówienia, osoby albo kontraktora (zrzuty ekranu każdego panelu) — tymi
 * samymi propsami co linki z powiadomień na profilu klienta.
 *
 * Nazwiska, numery zamówień i kwoty są zmyślone (repo jest publiczne).
 */

import { useEffect, useState } from "react";
import { AxiosError } from "axios";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ToastProvider } from "@/components/Toast";
import { MultiConsultantOrdersTab } from "@/components/client-profile/orders/MultiConsultantOrdersTab";
import { seedOrderGroupPanels } from "@/app/preview/order-groups-harness";
import { api } from "@/lib/api";
import type {
  ClientOrderRead,
  ClientOrdersGroupedResponse,
  ContractWithOrdersRead,
} from "@/lib/api/dlPortal";
import type {
  LineConsumptionsResponse,
  OrderGroupListResponse,
  OrderGroupRead,
  OrderHistoryEntry,
  OrderLineRead,
  OrderOffboardingCaseRead,
  SharedMdConsumptionsResponse,
} from "@/lib/api/orderGroups";
import { useAuthStore } from "@/store/auth";

const CLIENT_ID = 18;

/** Data lokalna przesunięta o `days` dni — liczona po zamontowaniu. */
function isoOffset(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() + days);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function line(overrides: Partial<OrderLineRead> = {}): OrderLineRead {
  return {
    id: 5011,
    group_id: 501,
    contract_id: 801,
    candidate_id: 41,
    consultant_name: "Anna Przykładowa",
    job_id: null,
    job_title: null,
    status: "active",
    is_active: true,
    start_date: "2026-03-01",
    end_date: null,
    rate_cost: 900,
    rate_revenue: 1150,
    input_value: 60,
    input_mode: "md",
    md_total: 60,
    md_remaining: 22,
    md_manual_adjustment: 0,
    md_used: 38,
    predecessor_order_id: null,
    predecessor_consultant_name: null,
    invoiced_total: null,
    unsettled_total: null,
    missing_consumption_month: null,
    md_optional_total: null,
    md_base_used: null,
    md_optional_used: null,
    replaced_by_order_id: null,
    replaced_by_consultant_name: null,
    contract_type: "b2b",
    ...overrides,
  };
}

function group(overrides: Partial<OrderGroupRead> = {}): OrderGroupRead {
  return {
    id: 501,
    client_id: CLIENT_ID,
    order_number: "4599050001",
    start_date: "2026-03-01",
    end_date: "2026-12-31",
    notes: null,
    created_at: "2026-03-01T10:00:00Z",
    order_type: "md",
    md_budget_mode: "per_person",
    status: "active",
    status_label: "Aktywne",
    closure_date: null,
    closure_reason: null,
    is_cost_based: false,
    is_md_budget_based: false,
    budget_amount: null,
    budget_used: null,
    budget_remaining: null,
    budget_manual_adjustment: null,
    md_budget_total: null,
    md_budget_used: null,
    md_budget_remaining: null,
    md_budget_manual_adjustment: null,
    predecessor_group_id: null,
    filename: "4599050001.pdf",
    has_file: true,
    content_type: "application/pdf",
    size_bytes: 98_000,
    file_uploaded_at: "2026-03-01T10:00:00Z",
    can_add_consultant: true,
    executive_contract: null,
    md_positions_total: null,
    md_used_total: null,
    contract_value_pln: null,
    used_value_pln: null,
    lines: [],
    active_consultants: 0,
    event_count: 4,
    future_orders: [],
    ...overrides,
  };
}

const PENDING_CASE: OrderOffboardingCaseRead = {
  id: 91,
  contract_id: 805,
  order_id: 5015,
  order_group_id: 501,
  client_id: CLIENT_ID,
  effective_date: "2026-08-31",
  status: "pending",
  version: 1,
  uses_shared_md_pool: false,
  remaining_md_snapshot: 8,
  rate_cost_snapshot: 900,
  rate_revenue_snapshot: 1150,
  currency_snapshot: "PLN",
  order_number_snapshot: "4599050001",
  resolution: null,
  target_order_id: null,
  rate_basis: null,
  resolution_payload: null,
  resolved_at: null,
  resolved_by_user_id: null,
  created_by_user_id: null,
  created_at: "2026-09-01T06:00:00Z",
  updated_at: "2026-09-01T06:00:00Z",
};

/** Zamówienie MD per osoba: obsada (brak zejścia, dodany ręcznie, zastępstwo),
 *  zakończeni (decyzja czeka, zastąpiony, zostawiony jako historia)
 *  i przyszłe zamówienie. */
const MD_GROUP = group({
  // Sumy pozycji liczy serwer (`md_positions_total` / `md_used_total`).
  md_positions_total: 120,
  md_used_total: 69,
  lines: [
    line({
      consumption_recent: [
        { period_month: "2026-06", md: 20 },
        { period_month: "2026-07", md: 18 },
      ],
      consumption_flags: ["missing_previous_month"],
      missing_consumption_month: "2026-08",
    }),
    line({
      id: 5012,
      contract_id: 802,
      candidate_id: 42,
      consultant_name: "Bartosz Wzorcowy",
      start_date: "2026-07-01",
      md_total: 40,
      md_remaining: 31,
      md_used: 9,
      origin: "manual",
      added_by_name: "Delivery Lead Przykładowy",
      added_at: "2026-07-01T09:00:00Z",
      consumption_recent: [{ period_month: "2026-08", md: 9 }],
    }),
    line({
      id: 5013,
      contract_id: 803,
      candidate_id: 43,
      consultant_name: "Celina Zastępcza",
      start_date: "2026-09-01",
      md_total: 12,
      md_remaining: 12,
      md_used: 0,
      assignment_kind: "takeover",
      takeover_from_name: "Dariusz Odchodzący",
      takeover_md: 12,
      takeover_method: "one_to_one",
      predecessor_order_id: 5014,
      predecessor_consultant_name: "Dariusz Odchodzący",
    }),
    line({
      id: 5014,
      contract_id: 804,
      candidate_id: 44,
      consultant_name: "Dariusz Odchodzący",
      status: "completed",
      is_active: false,
      start_date: "2026-03-01",
      end_date: "2026-08-31",
      cooperation_ended_on: "2026-08-31",
      md_total: 50,
      md_remaining: 0,
      md_used: 38,
      replaced_by_order_id: 5013,
      replaced_by_consultant_name: "Celina Zastępcza",
      replaced_by_kind: "takeover",
      replaced_by_start_date: "2026-09-01",
      replaced_by_md: 12,
    }),
    line({
      id: 5015,
      contract_id: 805,
      candidate_id: 45,
      consultant_name: "Ewa Czekająca",
      status: "completed",
      is_active: false,
      start_date: "2026-03-01",
      end_date: "2026-08-31",
      cooperation_ended_on: "2026-08-31",
      md_total: 30,
      md_remaining: 8,
      md_used: 22,
      offboarding_case: PENDING_CASE,
      agreement_termination_mode: "notice",
      agreement_last_day: "2026-09-30",
    }),
    line({
      id: 5016,
      contract_id: 806,
      candidate_id: 46,
      consultant_name: "Filip Historyczny",
      status: "completed",
      is_active: false,
      start_date: "2026-03-01",
      end_date: "2026-06-30",
      cooperation_ended_on: "2026-06-30",
      md_total: 40,
      md_remaining: 0,
      md_used: 40,
      history_kept_at: "2026-07-01T09:00:00Z",
      history_kept_by_name: "Delivery Lead Przykładowy",
      agreement_termination_mode: "mutual_agreement",
      agreement_last_day: "2026-06-30",
    }),
  ],
  active_consultants: 3,
  event_count: 6,
  future_orders: [
    group({
      id: 502,
      order_number: "4599050002",
      start_date: "2027-01-01",
      end_date: "2027-06-30",
      status: "scheduled",
      status_label: "Zaplanowane",
      predecessor_group_id: 501,
      filename: null,
      has_file: false,
      can_add_consultant: true,
      event_count: 1,
      lines: [
        line({
          id: 5021,
          group_id: 502,
          status: "draft",
          is_active: false,
          start_date: "2027-01-01",
          md_total: 60,
          md_remaining: 60,
          md_used: 0,
        }),
      ],
    }),
  ],
});

/** Zamówienie kosztowe: wspólna kwota, faktury per osoba, niepełne rozliczenie. */
const COST_GROUP = group({
  id: 503,
  order_number: "SAP 4599050003",
  order_type: "cost",
  md_budget_mode: null,
  is_cost_based: true,
  budget_amount: 80_000,
  budget_used: 32_000,
  budget_remaining: 48_000,
  filename: null,
  has_file: false,
  event_count: 3,
  lines: [
    line({
      id: 5031,
      group_id: 503,
      contract_id: 807,
      candidate_id: 47,
      consultant_name: "Grzegorz Kosztowy",
      md_total: null,
      md_remaining: null,
      md_used: null,
      input_mode: null,
      input_value: null,
      invoiced_total: 32_000,
      unsettled_total: 1_500,
    }),
    line({
      id: 5032,
      group_id: 503,
      contract_id: 808,
      candidate_id: 48,
      consultant_name: "Hanna Nowa",
      start_date: "2026-09-01",
      md_total: null,
      md_remaining: null,
      md_used: null,
      input_mode: null,
      input_value: null,
      invoiced_total: null,
    }),
  ],
  active_consultants: 2,
});

/** Wspólna pula MD zamówienia — linie bez własnego budżetu. */
const SHARED_GROUP = group({
  id: 504,
  order_number: "4599050004",
  md_budget_mode: "shared",
  is_md_budget_based: true,
  uses_shared_md_pool: true,
  md_budget_total: 100,
  md_budget_used: 40,
  md_budget_remaining: 60,
  filename: null,
  has_file: false,
  event_count: 2,
  lines: [
    line({
      id: 5041,
      group_id: 504,
      contract_id: 809,
      candidate_id: 49,
      consultant_name: "Igor Wspólny",
      md_total: null,
      md_remaining: null,
      // Suma osoby z podziału zejść (sierpień 25 MD); lipiec zapisano samą sumą.
      md_used: 25,
      shared_md_unattributed_months: 1,
      input_mode: null,
      input_value: null,
    }),
  ],
  active_consultants: 1,
});

const GROUPS = [MD_GROUP, COST_GROUP, SHARED_GROUP];

/** Zejścia wspólnej puli (40 MD z 100): miesiąc z podziałem i stara suma. */
const SHARED_CONSUMPTIONS: SharedMdConsumptionsResponse = {
  months: [
    {
      period_month: "2026-08",
      md_reported: 25,
      source: "manual",
      breakdown: [{ order_id: 5041, consultant_name: "Igor Wspólny", md: 25 }],
      breakdown_source: "manual",
      created_by_name: "Delivery Lead Przykładowy",
      updated_at: "2026-09-02T09:00:00Z",
    },
    {
      period_month: "2026-07",
      md_reported: 15,
      source: "manual",
      breakdown: null,
      breakdown_source: null,
      created_by_name: "Delivery Lead Przykładowy",
      updated_at: "2026-08-03T09:00:00Z",
    },
  ],
  consultants: [{ order_id: 5041, consultant_name: "Igor Wspólny", status: "active" }],
  md_budget_total: 100,
  md_used: 40,
  md_remaining: 60,
};

function entry(overrides: Partial<OrderHistoryEntry>): OrderHistoryEntry {
  return {
    key: "ev-1",
    category: "order",
    event_type: "utworzenie",
    type_label: "Utworzenie zamówienia",
    created_at: "2026-03-01T10:00:00Z",
    author_id: 7,
    author_name: "Delivery Lead Przykładowy",
    summary: "Utworzono zamówienie.",
    order_id: null,
    person_name: null,
    person_names: [],
    changes: [],
    balance_before: null,
    balance_after: null,
    details: [],
    import_id: null,
    import_period_month: null,
    import_people: null,
    import_md: null,
    related_group_id: null,
    related_order_number: null,
    ...overrides,
  };
}

const MD_HISTORY: OrderHistoryEntry[] = [
  entry({
    key: "ev-4",
    category: "consultants",
    event_type: "zamiana_kontraktora",
    type_label: "Zastępstwo",
    created_at: "2026-09-01T08:00:00Z",
    summary: "Celina Zastępcza przejęła 12 MD po Dariuszu Odchodzącym.",
    person_names: ["Celina Zastępcza", "Dariusz Odchodzący"],
  }),
  entry({
    key: "import-import_md-7",
    category: "consumption",
    event_type: "import_md",
    type_label: "Import MD",
    created_at: "2026-08-05T08:00:00Z",
    author_id: null,
    author_name: null,
    summary: "Import MD za lipiec 2026 – 2 osoby, 27 MD",
    person_names: ["Anna Przykładowa", "Bartosz Wzorcowy"],
    import_id: 7,
    import_period_month: "2026-07",
    import_people: 2,
    import_md: 27,
  }),
  entry({ key: "ev-1" }),
];

const ANNA_CONSUMPTIONS: LineConsumptionsResponse = {
  order_number: "4599050001",
  md_budget: 60,
  md_used: 38,
  md_remaining: 22,
  rows: [
    {
      period_month: "2026-06",
      md_reported: 20,
      status: "accepted",
      note: null,
      source: "import",
      import_id: 6,
      created_by_name: "Import z Finansów",
      updated_at: "2026-07-04T08:00:00Z",
      balance_after: 40,
    },
    {
      period_month: "2026-07",
      md_reported: 18,
      status: "protocol",
      note: "protokół 07/2026",
      source: "import",
      import_id: 7,
      created_by_name: "Import z Finansów",
      updated_at: "2026-08-05T08:00:00Z",
      balance_after: 22,
    },
  ],
};

function order(overrides: Partial<ClientOrderRead>): ClientOrderRead {
  return {
    id: 901,
    client_id: CLIENT_ID,
    contract_id: 811,
    job_id: null,
    framework_contract_id: null,
    title: "K/2026/000901/PR/1",
    description: null,
    status: "active",
    order_type: "periodic",
    start_date: "2026-04-01",
    end_date: "2026-12-31",
    rate_unit: "hourly",
    billing_hours_per_month: null,
    rate_candidate: 120,
    rate_client: 150,
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
    created_at: "2026-04-01T00:00:00Z",
    updated_at: "2026-04-01T00:00:00Z",
    candidate_id: 51,
    candidate_name: null,
    contract_status: "active",
    job_title: null,
    monthly_margin: null,
    days_to_end: null,
    ...overrides,
  };
}

function contractor(overrides: Partial<ContractWithOrdersRead>): ContractWithOrdersRead {
  return {
    contract_id: 811,
    candidate_id: 51,
    candidate_name: "Jakub Okresowy",
    contract_status: "active",
    contract_start_date: "2026-04-01",
    contract_end_date: null,
    rate_candidate: 120,
    rate_client_currency: "PLN",
    rate_candidate_currency: "PLN",
    rate_unit: "hourly",
    billing_hours_per_month: null,
    initial_job_id: null,
    initial_job_title: "Administrator systemów",
    latest_order_id: 901,
    latest_order_end_date: "2026-12-31",
    latest_order_rate_client: 150,
    latest_order_monthly_margin: null,
    days_to_latest_end: null,
    orders: [order({})],
    ...overrides,
  };
}

/** Kontraktorzy okresowi — daty od dziś, więc „jutro" zostaje jutrem. */
function periodicContractors(): ContractWithOrdersRead[] {
  return [
    // Zamówienie kończy się jutro, bez kontynuacji.
    contractor({
      contract_id: 811,
      days_to_latest_end: 1,
      latest_order_end_date: isoOffset(1),
      ending_without_successor_order_id: 901,
      ending_without_successor_end_date: isoOffset(1),
      ending_without_successor_days: 1,
      next_ending_without_successor_days: 1,
      orders: [order({ start_date: isoOffset(-120), end_date: isoOffset(1) })],
    }),
    // Umowa trwa, okres zamówienia minął — „Brak aktywnego zamówienia".
    contractor({
      contract_id: 812,
      candidate_id: 52,
      candidate_name: "Karolina Bezzamówienia",
      latest_order_id: 902,
      latest_order_end_date: isoOffset(-10),
      orders: [
        order({
          id: 902,
          contract_id: 812,
          candidate_id: 52,
          title: "K/2026/000902/PR/2",
          status: "completed",
          start_date: isoOffset(-200),
          end_date: isoOffset(-10),
        }),
      ],
    }),
    // Karta szkicu — kontrakt bez zamówienia.
    contractor({
      contract_id: 813,
      candidate_id: 53,
      candidate_name: "Leon Szkicowy",
      contract_status: "draft",
      draft_card: true,
      latest_order_id: null,
      latest_order_end_date: null,
      latest_order_rate_client: null,
      orders: [],
    }),
    // Bieżące zamówienie i przyszłe przedłużenie.
    contractor({
      contract_id: 814,
      candidate_id: 54,
      candidate_name: "Monika Przedłużona",
      latest_order_id: 905,
      latest_order_end_date: isoOffset(150),
      orders: [
        order({
          id: 905,
          contract_id: 814,
          candidate_id: 54,
          title: "K/2026/000905/PR/5",
          start_date: isoOffset(31),
          end_date: isoOffset(150),
          rate_client: 160,
        }),
        order({
          id: 904,
          contract_id: 814,
          candidate_id: 54,
          title: "K/2026/000904/PR/4",
          start_date: isoOffset(-60),
          end_date: isoOffset(30),
        }),
      ],
    }),
    // Współpraca zakończona.
    contractor({
      contract_id: 815,
      candidate_id: 55,
      candidate_name: "Norbert Zakończony",
      contract_status: "ended",
      contract_end_date: isoOffset(-40),
      latest_order_id: 906,
      latest_order_end_date: isoOffset(-40),
      orders: [
        order({
          id: 906,
          contract_id: 815,
          candidate_id: 55,
          title: "K/2026/000906/PR/6",
          status: "completed",
          start_date: isoOffset(-300),
          end_date: isoOffset(-40),
          contract_status: "ended",
        }),
      ],
    }),
  ];
}

function seededClient(): QueryClient {
  const qc = new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: Infinity,
        retry: false,
        refetchOnMount: false,
        refetchOnWindowFocus: false,
        // Klucz niezasiany przez pomyłkę odrzuca LOKALNIE — nie leci do API.
        queryFn: () => Promise.reject(new Error("podgląd: brak zasianych danych")),
      },
    },
  });
  const contractors = periodicContractors();
  qc.setQueryData<OrderGroupListResponse>(["client-order-groups", CLIENT_ID], {
    groups: GROUPS,
    total_groups: GROUPS.length,
    total_consultants: 9,
    suggested_order_type: "md",
  });
  qc.setQueryData<ClientOrdersGroupedResponse>(["dl-orders-grouped", CLIENT_ID], {
    contractors,
    total_contractors: contractors.length,
    can_manage_finance: true,
  });
  qc.setQueryData(["client-default-rate-unit", CLIENT_ID], "daily");
  seedOrderGroupPanels(qc, CLIENT_ID, GROUPS, {
    history: { 501: MD_HISTORY },
    consumptions: { 5011: ANNA_CONSUMPTIONS },
    sharedConsumptions: { 504: SHARED_CONSUMPTIONS },
  });
  return qc;
}

interface Focus {
  group: number | null;
  order: number | null;
  contract: number | null;
}

function readFocus(): Focus {
  const params = new URLSearchParams(window.location.search);
  const id = (name: string) => {
    const value = Number(params.get(name));
    return Number.isInteger(value) && value > 0 ? value : null;
  };
  return { group: id("group"), order: id("order"), contract: id("contract") };
}

export default function ClientOrdersPreview() {
  const [queryClient, setQueryClient] = useState<QueryClient | null>(null);
  const [focus, setFocus] = useState<Focus>({ group: null, order: null, contract: null });

  // Wszystko po zamontowaniu: daty „od dziś" i adres zna tylko przeglądarka
  // (SSR dałby inny pierwszy render), a blokada sieci i fikcyjny użytkownik
  // mają zniknąć razem z harnessem.
  useEffect(() => {
    const blocker = api.interceptors.request.use((config) =>
      Promise.reject(new AxiosError("preview: sieć wyłączona", "ECONNABORTED", config)),
    );
    const previousAuth = useAuthStore.getState();
    useAuthStore.setState({
      user: {
        id: 1,
        email: "preview@example.com",
        name: "Administrator Przykładowy",
        role: "admin",
        roles: ["admin"],
        capabilities: ["view_finance", "manage_finance"],
        profile_completed: true,
        profile_completed_at: null,
        force_password_change: false,
      } as never,
      token: "preview",
    } as never);
    setFocus(readFocus());
    setQueryClient(seededClient());
    return () => {
      api.interceptors.request.eject(blocker);
      useAuthStore.setState({ user: previousAuth.user, token: previousAuth.token } as never);
    };
  }, []);

  if (!queryClient) {
    return <div className="p-8 text-sm text-muted-foreground">Ładowanie…</div>;
  }

  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <main className="mx-auto flex max-w-[1680px] flex-col gap-4 p-4 sm:p-6">
          <header>
            <h1 className="text-lg font-semibold">Harness — zakładka „Zamówienia” klienta</h1>
            <p className="text-sm text-muted-foreground">
              Publiczny podgląd na zamrożonych danych. Zero zapytań do API. Kliknij
              wiersz albo dodaj do adresu <code>?group=501</code>, <code>?order=5015</code>{" "}
              lub <code>?contract=813</code>.
            </p>
          </header>
          <MultiConsultantOrdersTab
            clientId={CLIENT_ID}
            clientName="Klient Przykładowy"
            legacyNullOrderType="periodic"
            focusGroupId={focus.group}
            focusOrderId={focus.order}
            focusContractId={focus.contract}
            onFocusHandled={() => setFocus({ group: null, order: null, contract: null })}
          />
        </main>
      </ToastProvider>
    </QueryClientProvider>
  );
}
