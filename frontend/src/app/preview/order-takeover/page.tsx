"use client";

/**
 * Harness wizualny przypisania osoby ze szkicu i przejęcia pozostałych MD
 * (ticket 09.2026). Renderuje PRODUKCYJNE `OrderGroupCard`,
 * `AssignToOrderModal` i `OffboardingDecisionModal` na zamrożonych danych —
 * zero zapytań (ten sam wzorzec co `/preview/order-md-scopes`).
 *
 * `?view=` wybiera stan: `card` (domyślnie — po zastępstwie i zastępstwo
 * zaplanowane), `assign` (okno „Przypisz do zamówienia"), `offboarding`
 * (decyzja o MD z grupą „Nowe osoby u klienta").
 *
 * Nazwiska zmyślone. Numery umów w formacie CeZ są przykładowe.
 */

import { Suspense, useMemo } from "react";
import { useSearchParams } from "next/navigation";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { AssignToOrderModal } from "@/components/client-profile/orders/AssignToOrderModal";
import { OffboardingDecisionModal } from "@/components/client-profile/orders/OffboardingDecisionModal";
import { OrderGroupCard } from "@/components/client-profile/orders/OrderGroupCard";
import type { ContractWithOrdersRead } from "@/lib/api/dlPortal";
import type {
  OrderGroupRead,
  OrderLineRead,
  OrderOffboardingCaseRead,
} from "@/lib/api/orderGroups";
import { EZDROWIE_CLIENT_ID } from "@/lib/ezdrowie";

const CLIENT_ID = EZDROWIE_CLIENT_ID;

function line(overrides: Partial<OrderLineRead> = {}): OrderLineRead {
  return {
    id: 1,
    group_id: 930,
    contract_id: 100,
    candidate_id: 5,
    consultant_name: "Anna Przykładowa",
    job_id: null,
    job_title: null,
    status: "active",
    is_active: true,
    start_date: "2025-12-01",
    end_date: null,
    rate_cost: 760,
    rate_revenue: 800,
    input_value: 190,
    input_mode: "md",
    md_total: 190,
    md_remaining: 196,
    md_manual_adjustment: 0,
    predecessor_order_id: null,
    predecessor_consultant_name: null,
    invoiced_total: null,
    unsettled_total: null,
    missing_consumption_month: null,
    md_used: 164,
    md_optional_total: 170,
    md_base_used: 164,
    md_optional_used: 0,
    replaced_by_order_id: null,
    replaced_by_consultant_name: null,
    pool_unit: "md",
    ...overrides,
  };
}

const PENDING_CASE: OrderOffboardingCaseRead = {
  id: 9,
  contract_id: 102,
  order_id: 3,
  order_group_id: 931,
  client_id: CLIENT_ID,
  effective_date: "2026-08-31",
  status: "pending",
  version: 1,
  uses_shared_md_pool: false,
  remaining_md_snapshot: 187,
  rate_cost_snapshot: 760,
  rate_revenue_snapshot: 800,
  currency_snapshot: "PLN",
  order_number_snapshot: "CeZ/242/2025/P",
  resolution: null,
  target_order_id: null,
  rate_basis: null,
  resolution_payload: null,
  resolved_at: null,
  resolved_by_user_id: null,
  created_by_user_id: null,
  created_at: "2026-09-01T00:00:00Z",
  updated_at: "2026-09-01T00:00:00Z",
};

function group(overrides: Partial<OrderGroupRead>): OrderGroupRead {
  return {
    id: 930,
    client_id: CLIENT_ID,
    order_number: "CeZ/242/2025/P",
    start_date: "2025-12-01",
    end_date: null,
    notes: null,
    created_at: "2025-12-01T10:00:00Z",
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
    filename: null,
    has_file: false,
    content_type: null,
    size_bytes: null,
    file_uploaded_at: null,
    can_add_consultant: true,
    executive_contract: {
      id: 2,
      number: "CeZ/145/2025",
      status: "active",
      framework_contract_id: 12,
      project_part: "cz2",
    },
    md_positions_total: 720,
    md_used_total: 337,
    contract_value_pln: 576_000,
    used_value_pln: 269_600,
    lines: [],
    active_consultants: 1,
    event_count: 4,
    future_orders: [],
    ...overrides,
  } as OrderGroupRead;
}

// Po zapisie: Konrad (zastąpiony, 0 MD pozostałych) i Kamila (zastępstwo).
const AFTER = group({
  lines: [
    line(),
    line({
      id: 3,
      contract_id: 102,
      consultant_name: "Konrad Odchodzący",
      status: "completed",
      is_active: false,
      end_date: "2026-08-31",
      cooperation_ended_on: "2026-08-31",
      md_total: 173,
      md_optional_total: 0,
      md_remaining: 0,
      md_used: 173,
      md_base_used: 173,
      replaced_by_order_id: 4,
      replaced_by_consultant_name: "Kamila Przejmująca",
      replaced_by_kind: "takeover",
      replaced_by_start_date: "2026-09-01",
      replaced_by_md: 187,
    }),
    line({
      id: 4,
      contract_id: 645,
      consultant_name: "Kamila Przejmująca",
      start_date: "2026-09-01",
      rate_cost: 680,
      md_total: 17,
      md_optional_total: 170,
      md_remaining: 187,
      md_used: 0,
      md_base_used: 0,
      predecessor_order_id: 3,
      predecessor_consultant_name: "Konrad Odchodzący",
      origin: "manual",
      assignment_kind: "takeover",
      takeover_from_name: "Konrad Odchodzący",
      takeover_md: 187,
      takeover_method: "one_to_one",
    }),
  ],
});

// Zastępstwo zaplanowane: odchodzący jeszcze pracuje.
const SCHEDULED = group({
  id: 932,
  order_number: "CeZ/2/2026/P",
  lines: [
    line({
      id: 10,
      group_id: 932,
      contract_id: 110,
      consultant_name: "Marek Kończący",
      end_date: "2026-10-31",
      replaced_by_order_id: 11,
      replaced_by_consultant_name: "Ola Nowa",
      replaced_by_kind: "takeover",
      replaced_by_start_date: "2026-11-01",
      replaced_by_scheduled: true,
      replaced_by_md: 196,
    }),
    line({
      id: 11,
      group_id: 932,
      contract_id: 111,
      consultant_name: "Ola Nowa",
      status: "draft",
      is_active: false,
      start_date: "2026-11-01",
      md_total: 26,
      md_remaining: 196,
      md_used: 0,
      md_base_used: 0,
      predecessor_order_id: 10,
      assignment_kind: "takeover",
      takeover_from_name: "Marek Kończący",
      takeover_md: 196,
      takeover_method: "one_to_one",
      takeover_scheduled: true,
    }),
  ],
});

// Przed zapisem: Konrad czeka na decyzję o MD.
const KONRAD_PENDING = line({
  id: 3,
  group_id: 931,
  contract_id: 102,
  consultant_name: "Konrad Odchodzący",
  status: "completed",
  is_active: false,
  end_date: "2026-08-31",
  md_remaining: 187,
  md_used: 173,
  md_base_used: 173,
  takeover_source: "ended",
  departure_date: "2026-08-31",
  offboarding_case: PENDING_CASE,
});
const BEFORE = group({
  id: 931,
  lines: [line({ group_id: 931 }), KONRAD_PENDING],
});

const KAMILA = {
  contract_id: 645,
  candidate_id: 1,
  candidate_name: "Kamila Przejmująca",
  contract_status: "active",
  rate_candidate: 85,
  rate_unit: "hourly",
  initial_job_id: null,
  draft_card: true,
  orders: [],
} as unknown as ContractWithOrdersRead;

function noop() {}

function cardProps(item: OrderGroupRead) {
  return {
    clientId: CLIENT_ID,
    group: item,
    canManage: true,
    canManageLifecycle: true,
    onAddConsultant: noop,
    onEditGroup: noop,
    onEditLine: noop,
    onSwapLine: noop,
    onDeleteLine: noop,
    onResolveOffboarding: noop,
    onKeepHistory: noop,
    onReplaceLine: noop,
    onDeleteGroup: noop,
    onCloseGroup: noop,
    onReopenGroup: noop,
    onExtendGroup: noop,
    onFocusGroup: noop,
  };
}

function Harness() {
  const view = useSearchParams().get("view") ?? "card";
  return (
    <main className="mx-auto flex max-w-5xl flex-col gap-8 p-8">
      <header>
        <h1 className="text-lg font-semibold">
          Harness — przypisanie ze szkicu i przejęcie MD (CeZ)
        </h1>
        <p className="text-sm text-muted-foreground">
          Publiczny podgląd na zamrożonych danych. Zero zapytań do API.
          Widoki: <code>?view=card</code>, <code>?view=assign</code>,{" "}
          <code>?view=offboarding</code>.
        </p>
      </header>
      {view === "card" ? (
        <>
          <section className="flex flex-col gap-2">
            <h2 className="text-sm font-semibold">Po zastępstwie (Konrad → Kamila)</h2>
            <OrderGroupCard {...cardProps(AFTER)} />
          </section>
          <section className="flex flex-col gap-2">
            <h2 className="text-sm font-semibold">Zastępstwo zaplanowane</h2>
            <OrderGroupCard {...cardProps(SCHEDULED)} />
          </section>
        </>
      ) : null}
      <AssignToOrderModal
        open={view === "assign"}
        onOpenChange={noop}
        contractor={KAMILA}
        groups={[BEFORE]}
        submitting={false}
        error={null}
        onJoin={noop}
        onTakeover={noop}
        onNewOrder={noop}
      />
      <OffboardingDecisionModal
        open={view === "offboarding"}
        onOpenChange={noop}
        group={BEFORE}
        line={KONRAD_PENDING}
        submitting={false}
        error={null}
        onSubmit={noop}
        newPeople={[KAMILA]}
        onTakeover={noop}
      />
    </main>
  );
}

export default function OrderTakeoverPreview() {
  const queryClient = useMemo(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: Infinity,
            retry: false,
            refetchOnMount: false,
            queryFn: () => Promise.reject(new Error("podgląd: brak zasianych danych")),
          },
        },
      }),
    [],
  );
  return (
    <QueryClientProvider client={queryClient}>
      <Suspense fallback={null}>
        <Harness />
      </Suspense>
    </QueryClientProvider>
  );
}
