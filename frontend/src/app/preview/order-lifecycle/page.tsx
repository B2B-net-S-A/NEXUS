"use client";

/**
 * Harness wizualny karty zamówienia wielo-konsultantowego.
 *
 * Renderuje PRODUKCYJNY `OrderGroupCard` (nie kopię), a dane wstrzykuje przez
 * zasiany cache react-query z `staleTime: Infinity` — żaden `queryFn` się nie
 * odpala, więc strona nie robi ani jednego zapytania i może stać w
 * `PUBLIC_PATHS`. Ten sam wzorzec co `/preview/order-consultant-picker`.
 *
 * Stany stoją OBOK SIEBIE celowo: to jedyny sposób, żeby zobaczyć, że awaria,
 * pustka i „wyczerpany budżet" nie wyglądają tak samo.
 */

import { useMemo } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { OrderGroupCard } from "@/components/client-profile/orders/OrderGroupCard";
import type { OrderGroupRead, OrderLineRead } from "@/lib/api/orderGroups";

function line(overrides: Partial<OrderLineRead> = {}): OrderLineRead {
  return {
    id: 1,
    group_id: 10,
    contract_id: 100,
    candidate_id: 5,
    consultant_name: "Jan Kowalski",
    job_id: null,
    job_title: null,
    status: "active",
    is_active: true,
    start_date: "2026-03-01",
    end_date: null,
    rate_cost: 1000,
    rate_revenue: 1200,
    input_value: 50,
    input_mode: "md",
    md_total: 50,
    md_remaining: 32,
    md_manual_adjustment: 0,
    predecessor_order_id: null,
    predecessor_consultant_name: null,
    invoiced_total: null,
    unsettled_total: null,
    missing_consumption_month: null,
    ...overrides,
  };
}

function group(overrides: Partial<OrderGroupRead> = {}): OrderGroupRead {
  return {
    id: 10,
    client_id: 1,
    order_number: "445",
    start_date: "2026-03-01",
    end_date: "2026-12-31",
    notes: null,
    created_at: "2026-03-01T10:00:00Z",
    status: "active",
    status_label: "Aktywne",
    closure_date: null,
    closure_reason: null,
    is_cost_based: false,
    budget_amount: null,
    budget_used: null,
    budget_remaining: null,
    budget_manual_adjustment: null,
    predecessor_group_id: null,
    can_add_consultant: true,
    lines: [line(), line({ id: 2, consultant_name: "Anna Nowak", md_remaining: 8 })],
    active_consultants: 2,
    event_count: 4,
    ...overrides,
  };
}

const CASES: Array<{ title: string; why: string; group: OrderGroupRead }> = [
  {
    title: "Zamówienie MD — stan normalny",
    why: "Pasek MD wypełniony POZOSTAŁOŚCIĄ, komplet akcji cyklu życia.",
    group: group(),
  },
  {
    title: "Zamówienie kosztowe — trzy liczby",
    why: "Kwota, wykorzystano i pozostało — zamiast jednej liczby podpisanej „zużycie”, która maleje.",
    group: group({
      id: 11,
      order_number: "SAP 4500719650",
      is_cost_based: true,
      budget_amount: 50000,
      budget_used: 30000,
      budget_remaining: 20000,
      lines: [
        line({
          id: 3,
          md_total: null,
          md_remaining: null,
          invoiced_total: 20000,
          unsettled_total: 0,
        }),
        line({
          id: 4,
          consultant_name: "Anna Nowak",
          md_total: null,
          md_remaining: null,
          invoiced_total: 10000,
          unsettled_total: 0,
        }),
      ],
    }),
  },
  {
    title: "Budżet wyczerpany + niepełne rozliczenie",
    why: "Zamówienie blokuje dodawanie konsultantów, a przy osobie widać, ILE zabrakło.",
    group: group({
      id: 12,
      order_number: "SAP 4500719651",
      status: "exhausted",
      status_label: "Wyczerpane",
      is_cost_based: true,
      budget_amount: 50000,
      budget_used: 50000,
      budget_remaining: 0,
      can_add_consultant: false,
      lines: [
        line({
          id: 5,
          md_total: null,
          md_remaining: null,
          invoiced_total: 60000,
          unsettled_total: 10000,
        }),
      ],
    }),
  },
  {
    title: "Zakończone — do przywrócenia",
    why: "Przycisk zakończenia znika, pojawia się przywrócenie; data zakończenia jest w nagłówku.",
    group: group({
      id: 13,
      order_number: "444",
      status: "completed",
      status_label: "Zakończone",
      closure_date: "2026-06-30",
      lines: [line({ id: 6, is_active: false, end_date: "2026-06-30" })],
      active_consultants: 0,
    }),
  },
  {
    title: "Brak zejścia za miesiąc",
    why: "Import za miesiąc był, ale ta osoba nie ma w nim rozliczenia — to nie to samo co brak importu.",
    group: group({
      id: 14,
      order_number: "SAP 4500719652",
      is_cost_based: true,
      budget_amount: 50000,
      budget_used: 0,
      budget_remaining: 50000,
      lines: [
        line({
          id: 7,
          md_total: null,
          md_remaining: null,
          invoiced_total: null,
          missing_consumption_month: "2026-07",
        }),
      ],
    }),
  },
];

function noop() {}

export default function OrderLifecyclePreview() {
  const queryClient = useMemo(() => {
    const qc = new QueryClient({
      defaultOptions: {
        queries: {
          staleTime: Infinity,
          retry: false,
          refetchOnMount: false,
          // Domyślne `queryFn`, które odrzuca LOKALNIE — obietnica „zero
          // zapytań" przestaje zależeć od tego, czy zasiałem każdy klucz.
          // Klucz pominięty przez pomyłkę poleciałby do API, dostał 401,
          // a globalny interceptor axiosa przerzuciłby całą stronę na /login
          // — publiczny podgląd zniknąłby oglądającemu z ekranu.
          queryFn: () => Promise.reject(new Error("podgląd: brak zasianych danych")),
        },
      },
    });
    // Historia jest lazy (`enabled: historyOpen`), więc bez zasiania jej
    // rozwinięcie trafiłoby w sieć. Zasiewamy pustą — to też stan do obejrzenia.
    for (const item of CASES) {
      qc.setQueryData(["order-group-events", item.group.client_id, item.group.id], {
        events: [],
      });
    }
    return qc;
  }, []);

  return (
    <QueryClientProvider client={queryClient}>
      <main className="mx-auto flex max-w-5xl flex-col gap-8 p-8">
        <header>
          <h1 className="text-lg font-semibold">
            Harness — karta zamówienia (cykl życia + budżet kosztowy)
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
              clientId={item.group.client_id}
              group={item.group}
              canManage
              canManageLifecycle
              onAddConsultant={noop}
              onEditGroup={noop}
              onEditLine={noop}
              onSwapLine={noop}
              onDeleteLine={noop}
              onDeleteGroup={noop}
              onCloseGroup={noop}
              onReopenGroup={noop}
              onExtendGroup={noop}
            />
          </section>
        ))}
      </main>
    </QueryClientProvider>
  );
}
