"use client";

/**
 * Harness wizualny zamówienia MD z zakresami podstawa + opcja (Centrum
 * e-Zdrowia, Faza B). Renderuje PRODUKCYJNY `OrderGroupCard` na zamrożonych
 * danych: cache react-query zasiany ze `staleTime: Infinity` i domyślnym
 * `queryFn`, które odrzuca LOKALNIE — strona nie robi ani jednego zapytania
 * (ten sam wzorzec co `/preview/order-lifecycle`).
 *
 * Dwa warianty tej samej karty stoją obok siebie celowo: z kwotami (rola
 * z finansami) i bez (`contract_value_pln: null`) — różnica ma być widoczna
 * na jednym ekranie, a nie zależeć od tego, kto akurat patrzy.
 *
 * Nazwiska zmyślone. Numery umów w formacie CeZ są przykładowe.
 */

import { useMemo } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { OrderGroupCard } from "@/components/client-profile/orders/OrderGroupCard";
import { lineConsumptionsQueryKey } from "@/components/client-profile/orders/LineMonthlyHistoryDialog";
import type {
  LineConsumptionRow,
  OrderGroupListResponse,
  OrderGroupRead,
  OrderLineRead,
} from "@/lib/api/orderGroups";
import { EZDROWIE_CLIENT_ID } from "@/lib/ezdrowie";

const CLIENT_ID = EZDROWIE_CLIENT_ID;

function line(overrides: Partial<OrderLineRead> = {}): OrderLineRead {
  return {
    id: 1,
    group_id: 910,
    contract_id: 100,
    candidate_id: 5,
    consultant_name: "Anna Przykładowa",
    job_id: null,
    job_title: null,
    status: "active",
    is_active: true,
    start_date: "2025-10-01",
    end_date: null,
    rate_cost: 1000,
    rate_revenue: 1240,
    input_value: 190,
    input_mode: "md",
    md_total: 190,
    md_remaining: 36,
    md_manual_adjustment: 0,
    predecessor_order_id: null,
    predecessor_consultant_name: null,
    invoiced_total: null,
    unsettled_total: null,
    missing_consumption_month: null,
    md_used: 154,
    md_optional_total: 170,
    md_base_used: 154,
    md_optional_used: 0,
    replaced_by_order_id: null,
    replaced_by_consultant_name: null,
    ...overrides,
  };
}

/** Cztery przypadki z ticketu: podstawa+opcja z zużyciem, bez opcji,
 *  zastąpiony → następca, następca z zerowym zużyciem. */
const LINES: OrderLineRead[] = [
  line(),
  line({
    id: 2,
    contract_id: 101,
    candidate_id: 6,
    consultant_name: "Piotr Bezopcji",
    md_total: 120,
    md_remaining: 70,
    md_used: 50,
    md_optional_total: null,
    md_base_used: 50,
    md_optional_used: null,
    rate_revenue: 1100,
  }),
  line({
    id: 3,
    contract_id: 102,
    candidate_id: 7,
    consultant_name: "Tomasz Zastąpiony",
    status: "completed",
    is_active: false,
    end_date: "2026-06-30",
    cooperation_ended_on: "2026-06-30",
    md_total: 100,
    md_remaining: 0,
    md_used: 112,
    md_optional_total: 40,
    md_base_used: 100,
    md_optional_used: 12,
    rate_revenue: 1180,
    replaced_by_order_id: 4,
    replaced_by_consultant_name: "Marcin Następca",
  }),
  line({
    id: 4,
    contract_id: 103,
    candidate_id: 8,
    consultant_name: "Marcin Następca",
    start_date: "2026-07-01",
    md_total: 60,
    md_remaining: 60,
    md_used: 0,
    md_optional_total: 28,
    md_base_used: 0,
    md_optional_used: 0,
    rate_revenue: 1180,
    predecessor_order_id: 3,
    predecessor_consultant_name: "Tomasz Zastąpiony",
    origin: "manual",
    added_by_name: "Delivery Lead Przykładowy",
    added_at: "2026-07-01T09:00:00Z",
    replaces_name: "Tomasz Zastąpiony",
  }),
];

function group(overrides: Partial<OrderGroupRead> = {}): OrderGroupRead {
  return {
    id: 910,
    client_id: CLIENT_ID,
    order_number: "CeZ/242/2025/Z-7",
    start_date: "2025-10-01",
    end_date: "2026-12-31",
    notes: null,
    created_at: "2025-10-01T10:00:00Z",
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
    filename: "CeZ-242-2025-Z-7.pdf",
    has_file: true,
    content_type: "application/pdf",
    size_bytes: 120_000,
    file_uploaded_at: "2025-10-01T10:00:00Z",
    can_add_consultant: true,
    executive_contract: {
      id: 71,
      number: "CeZ/242/2025",
      status: "active",
      framework_contract_id: 12,
      project_part: "cz2",
    },
    md_positions_total: 708,
    md_used_total: 316,
    contract_value_pln: 2_295_200,
    used_value_pln: 711_480,
    lines: LINES,
    active_consultants: 3,
    event_count: 6,
    future_orders: [],
    ...overrides,
  };
}

const WITH_FINANCE = group();
const WITHOUT_FINANCE = group({
  id: 911,
  order_number: "CeZ/242/2025/Z-8",
  contract_value_pln: null,
  used_value_pln: null,
  lines: LINES.map((item) => ({
    ...item,
    group_id: 911,
    rate_cost: null,
    rate_revenue: null,
  })),
});

const CONSUMPTIONS: LineConsumptionRow[] = [
  {
    period_month: "2025-12",
    md_reported: 20,
    status: "accepted",
    note: null,
    source: "import",
    import_id: 501,
    created_by_name: "Import z Finansów",
    updated_at: "2026-01-05T08:00:00Z",
  },
  {
    period_month: "2026-01",
    md_reported: 21,
    status: "accepted",
    note: "protokół 01/2026",
    source: "import",
    import_id: 502,
    created_by_name: "Import z Finansów",
    updated_at: "2026-02-04T08:00:00Z",
  },
  {
    period_month: "2026-02",
    md_reported: 18.5,
    status: "protocol",
    note: null,
    source: "manual",
    import_id: null,
    created_by_name: "Delivery Lead Przykładowy",
    updated_at: "2026-03-02T08:00:00Z",
  },
];

const CASES: Array<{ title: string; why: string; group: OrderGroupRead }> = [
  {
    title: "Zamówienie MD z zakresami — rola z finansami",
    why:
      "Nagłówek: umowa wykonawcza z częścią, pasek MD pozycji i wartość umowy w PLN. " +
      "Wiersze: podstawa + opcja z zużyciem, brak opcji w umowie, osoba zastąpiona " +
      "z przejściem „→ następca”, następca z zerowym zużyciem. Kalendarz przy wierszu " +
      "otwiera rozliczenia miesięczne (zasiane dla pierwszej osoby).",
    group: WITH_FINANCE,
  },
  {
    title: "To samo zamówienie — rola bez finansów",
    why:
      "`contract_value_pln: null` → nagłówek pokazuje wyłącznie MD, stawki w wierszach " +
      "renderują się jako „—”, paski MD (operacyjne) zostają.",
    group: WITHOUT_FINANCE,
  },
];

function noop() {}

export default function OrderMdScopesPreview() {
  const queryClient = useMemo(() => {
    const qc = new QueryClient({
      defaultOptions: {
        queries: {
          staleTime: Infinity,
          retry: false,
          refetchOnMount: false,
          // Domyślne `queryFn` odrzuca LOKALNIE — obietnica „zero zapytań"
          // nie zależy od tego, czy zasiałem każdy klucz.
          queryFn: () => Promise.reject(new Error("podgląd: brak zasianych danych")),
        },
      },
    });
    qc.setQueryData<OrderGroupListResponse>(["client-order-groups", CLIENT_ID], {
      groups: CASES.map((item) => item.group),
      total_groups: CASES.length,
      total_consultants: LINES.length,
    });
    for (const item of CASES) {
      qc.setQueryData(["order-group-events", CLIENT_ID, item.group.id], { events: [] });
      for (const row of item.group.lines) {
        // Pierwsza osoba ma wpisy, reszta pusty stan — oba do obejrzenia.
        qc.setQueryData(lineConsumptionsQueryKey(CLIENT_ID, item.group.id, row.id), {
          rows: row.id === 1 ? CONSUMPTIONS : [],
        });
      }
    }
    return qc;
  }, []);

  return (
    <QueryClientProvider client={queryClient}>
      <main className="mx-auto flex max-w-5xl flex-col gap-8 p-8">
        <header>
          <h1 className="text-lg font-semibold">
            Harness — zamówienie MD z zakresami (podstawa + opcja, CeZ)
          </h1>
          <p className="text-sm text-muted-foreground">
            Publiczny podgląd na zamrożonych danych. Zero zapytań do API.
          </p>
        </header>

        {CASES.map((item) => (
          <section key={item.group.id} className="flex flex-col gap-2">
            <div>
              <h2 className="text-sm font-semibold">{item.title}</h2>
              <p className="text-xs text-muted-foreground">{item.why}</p>
            </div>
            <OrderGroupCard
              clientId={CLIENT_ID}
              group={item.group}
              canManage
              canManageLifecycle
              onAddConsultant={noop}
              onEditGroup={noop}
              onEditLine={noop}
              onSwapLine={noop}
              onDeleteLine={noop}
              onResolveOffboarding={noop}
              onKeepHistory={noop}
              onReplaceLine={noop}
              onDeleteGroup={noop}
              onCloseGroup={noop}
              onReopenGroup={noop}
              onExtendGroup={noop}
              onFocusGroup={noop}
            />
          </section>
        ))}
      </main>
    </QueryClientProvider>
  );
}
