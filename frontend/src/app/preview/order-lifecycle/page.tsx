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

import { useMemo, useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import {
  OrderGroupCard,
  type OrderGroupFocusRequest,
} from "@/components/client-profile/orders/OrderGroupCard";
import type {
  OrderGroupEvent,
  OrderGroupRead,
  OrderLineRead,
} from "@/lib/api/orderGroups";

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
    lines: [line(), line({ id: 2, consultant_name: "Anna Nowak", md_remaining: 8 })],
    active_consultants: 2,
    event_count: 4,
    future_orders: [],
    ...overrides,
  };
}

function event(overrides: Partial<OrderGroupEvent> = {}): OrderGroupEvent {
  return {
    id: 1,
    event_type: "utworzenie",
    event_label: "Utworzenie",
    description: "Zamówienie utworzone.",
    order_id: null,
    payload: null,
    related_group_id: null,
    related_order_number: null,
    created_by_user_id: null,
    created_at: "2026-03-01T10:00:00Z",
    ...overrides,
  };
}

/** `events` domyślnie puste — to też stan do obejrzenia (pusta historia nie
 *  może wyglądać jak awaria pobrania). */
const CASES: Array<{
  title: string;
  why: string;
  group: OrderGroupRead;
  events?: OrderGroupEvent[];
}> = [
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
  {
    title: "Przeniesienie MD na zamówienie-następcę",
    why:
      "Historia niesie ikonę per typ wpisu, a numer zamówienia powiązanego jest " +
      "klikalny — cel leży w „Przyszłych zamówieniach” tej samej karty. Wpis bez " +
      "powiązania (ostatni) renderuje sam tekst, bez martwego przycisku.",
    group: group({
      id: 15,
      order_number: "4500030067",
      lines: [line({ id: 8, md_total: 50, md_remaining: 0 })],
      active_consultants: 1,
      event_count: 5,
      future_orders: [
        group({
          id: 16,
          order_number: "4500029903",
          start_date: "2026-08-15",
          end_date: null,
          status: "scheduled",
          status_label: "Zaplanowane",
          lines: [
            line({ id: 9, group_id: 16, status: "draft", md_total: 22, md_remaining: 22 }),
          ],
          active_consultants: 0,
          event_count: 2,
          future_orders: [],
        }),
      ],
    }),
    events: [
      event({ id: 101, description: "Zamówienie utworzone przez import PDF." }),
      event({
        id: 102,
        event_type: "dodanie_konsultanta",
        event_label: "Dodanie konsultanta",
        description: "Dodano konsultanta Jan Kowalski (50 MD).",
        created_at: "2026-03-02T09:00:00Z",
      }),
      event({
        id: 103,
        event_type: "import_md",
        event_label: "Import MD",
        description:
          "Za lipiec 2026 zużyto 20 MD z zamówienia nr 4500030067 — " +
          "wykorzystano 45 / pozostało 5 MD.",
        created_at: "2026-08-05T08:00:00Z",
      }),
      event({
        id: 104,
        event_type: "transfer_md",
        event_label: "Przeniesienie MD",
        description:
          "Zamówienie zakończone — budżet MD wyczerpany, kontynuacja na " +
          "zamówieniu nr 4500029903",
        related_group_id: 16,
        related_order_number: "4500029903",
        created_at: "2026-08-20T08:00:00Z",
      }),
      event({
        id: 105,
        event_type: "transfer_md",
        event_label: "Przeniesienie MD",
        description:
          "Zamówienie zakończone — budżet MD wyczerpany, kontynuacja na " +
          "zamówieniu nr 4500029904",
        related_group_id: null,
        related_order_number: "4500029904",
        created_at: "2026-08-20T08:05:00Z",
      }),
    ],
  },
];

function noop() {}

export default function OrderLifecyclePreview() {
  // Ta sama plątanina co w `MultiConsultantOrdersTab` — harness ma ćwiczyć
  // PRODUKCYJNĄ ścieżkę przejścia, a nie jej uproszczoną atrapę.
  const [focusRequest, setFocusRequest] = useState<OrderGroupFocusRequest | null>(
    null,
  );

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
    // rozwinięcie trafiłoby w sieć.
    for (const item of CASES) {
      qc.setQueryData(["order-group-events", item.group.client_id, item.group.id], {
        events: item.events ?? [],
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
              focusRequest={focusRequest}
              onFocusGroup={(groupId) =>
                setFocusRequest((prev) => ({
                  groupId,
                  nonce: (prev?.nonce ?? 0) + 1,
                }))
              }
            />
          </section>
        ))}
      </main>
    </QueryClientProvider>
  );
}
