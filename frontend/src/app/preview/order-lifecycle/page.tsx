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
  ClientMdImportsTab,
  clientMdImportsQueryKey,
} from "@/components/client-profile/orders/ClientMdImportsTab";
import { lineConsumptionsQueryKey } from "@/components/client-profile/orders/LineMonthlyHistoryDialog";
import {
  OrderGroupCard,
  type OrderGroupFocusRequest,
} from "@/components/client-profile/orders/OrderGroupCard";
import { orderHistoryQueryKey } from "@/components/client-profile/orders/OrderHistoryPanel";
import type {
  ClientMdImportDetail,
  ClientMdImportSummary,
  LineConsumptionsResponse,
  OrderGroupRead,
  OrderHistoryEntry,
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
    md_optional_total: null,
    md_base_used: null,
    md_optional_used: null,
    replaced_by_order_id: null,
    replaced_by_consultant_name: null,
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
    executive_contract: null,
    md_positions_total: null,
    md_used_total: null,
    contract_value_pln: null,
    used_value_pln: null,
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

function entry(overrides: Partial<OrderHistoryEntry> = {}): OrderHistoryEntry {
  return {
    key: "ev-1",
    category: "order",
    event_type: "utworzenie",
    type_label: "Utworzenie zamówienia",
    created_at: "2026-03-01T10:00:00Z",
    author_id: 7,
    author_name: "Anna Przykładowa",
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

/** Historia zamówienia 4500030197 (BIK) w kształcie z produkcji po ticket 7:
 *  23 wpisy dziennika → 10 wpisów biznesowych. */
const BIK_HISTORY: OrderHistoryEntry[] = [
  entry({
    key: "ev-530",
    category: "edits",
    event_type: "edycja_reczna",
    type_label: "Edycja",
    created_at: "2026-09-24T16:16:50Z",
    author_id: null,
    author_name: null,
    summary:
      "Korekta importu MD: za 2026-08 zaksięgowano 2 MD z wiersza z numerem 4500030197; " +
      "19 MD z wiersza z numerem 4500030845 przeniesiono na zamówienie 4500030845.",
    order_id: 145,
    person_name: "Paweł Łaski",
    person_names: ["Paweł Łaski"],
    balance_before: -19,
    balance_after: 0,
  }),
  entry({
    key: "edit-522",
    category: "edits",
    event_type: "edycja_reczna",
    type_label: "Edycja",
    created_at: "2026-09-24T12:25:01Z",
    summary: "6 zmian w serii edycji",
    order_id: 146,
    person_name: "Konrad Teper",
    person_names: ["Konrad Teper"],
    changes: [
      { label: "ręczna korekta MD", before: null, after: null },
      { label: "stawka kosztowa", before: null, after: null },
      { label: "budżet MD", before: null, after: null },
    ],
    balance_before: -4,
    balance_after: 5.963,
    details: [
      { created_at: "2026-09-24T12:22:18Z", author_id: 7, author_name: "Anna Przykładowa", text: "Zmieniono: ręczna korekta MD. Pozostało 3,7 MD." },
      { created_at: "2026-09-24T12:22:48Z", author_id: 7, author_name: "Anna Przykładowa", text: "Zmieniono: ręczna korekta MD. Pozostało 5,963 MD." },
      { created_at: "2026-09-24T12:23:47Z", author_id: 7, author_name: "Anna Przykładowa", text: "Zejście MD za sierpień 2026: 4 → 3,7 MD. Pozostało 6,263 MD." },
      { created_at: "2026-09-24T12:24:16Z", author_id: 7, author_name: "Anna Przykładowa", text: "Zmieniono: stawka kosztowa, data zakończenia, budżet MD. Pozostało 9,963 MD." },
      { created_at: "2026-09-24T12:24:35Z", author_id: 7, author_name: "Anna Przykładowa", text: "Zejście MD za sierpień 2026: 3,7 MD. Pozostało 9,963 MD." },
      { created_at: "2026-09-24T12:25:01Z", author_id: 7, author_name: "Anna Przykładowa", text: "Zmieniono: ręczna korekta MD. Pozostało 5,963 MD." },
    ],
  }),
  entry({
    key: "import-import_md-2",
    category: "consumption",
    event_type: "import_md",
    type_label: "Import MD",
    created_at: "2026-09-23T11:40:03Z",
    summary: "Import MD za sierpień 2026 – 2 osoby, 25 MD",
    person_names: ["Paweł Łaski", "Konrad Teper"],
    import_id: 2,
    import_period_month: "2026-08",
    import_people: 2,
    import_md: 25,
  }),
  entry({
    key: "ev-481",
    event_type: "zakonczenie",
    type_label: "Zakończenie zamówienia",
    created_at: "2026-09-23T11:40:03Z",
    author_id: null,
    author_name: null,
    summary:
      "Zakończono zamówienie 4500030197 z dniem 2026-09-23 — wszyscy konsultanci wyczerpali limit MD",
  }),
  entry({
    key: "edit-900",
    category: "edits",
    event_type: "edycja_reczna",
    type_label: "Edycja",
    created_at: "2026-09-25T09:10:00Z",
    summary: "stawka kosztowa: 560 zł/MD → 580 zł/MD; budżet MD: 9,66 MD → 10 MD.",
    order_id: 146,
    person_name: "Konrad Teper",
    person_names: ["Konrad Teper"],
    changes: [
      { label: "stawka kosztowa", before: "560 zł/MD", after: "580 zł/MD" },
      { label: "budżet MD", before: "9,66 MD", after: "10 MD" },
    ],
    balance_before: 5.963,
    balance_after: 6.303,
  }),
  entry({
    key: "import-import_md-1",
    category: "consumption",
    event_type: "import_md",
    type_label: "Import MD",
    created_at: "2026-08-31T11:19:05Z",
    summary: "Import MD za lipiec 2026 – 2 osoby, 44,75 MD",
    person_names: ["Paweł Łaski", "Konrad Teper"],
    import_id: 1,
    import_period_month: "2026-07",
    import_people: 2,
    import_md: 44.75,
  }),
  entry({
    key: "ev-115",
    category: "consultants",
    event_type: "dodanie_konsultanta",
    type_label: "Dodanie konsultanta",
    created_at: "2026-08-21T09:52:11Z",
    summary: "Konrad Teper — stawka kosztowa 560.00 zł/MD, przychodowa 1000.00 zł/MD, budżet 9.66 MD",
    order_id: 146,
    person_name: "Konrad Teper",
    person_names: ["Konrad Teper"],
  }),
  entry({
    key: "ev-112",
    created_at: "2026-08-21T09:31:15Z",
    summary: "Utworzono zamówienie nr 4500030197 (2026-05-01 → 2026-08-31)",
  }),
].sort((a, b) => b.created_at.localeCompare(a.created_at));

const TEPER_CONSUMPTIONS: LineConsumptionsResponse = {
  order_number: "4500030197",
  md_budget: 35.713,
  md_used: 25.45,
  md_remaining: 5.963,
  foreign_import_warnings: [],
  removed_months: [],
  rows: [
    {
      period_month: "2026-07",
      md_reported: 21.75,
      status: null,
      note: null,
      source: "import",
      source_kind: "import",
      import_id: 1,
      created_by_name: "Anna Przykładowa",
      updated_at: "2026-08-31T11:19:05Z",
      balance_after: 9.663,
      import_rows: [
        { import_id: 1, row_number: 31, order_number_hint: "4500030197", md_reported: 21.75, foreign: false },
      ],
      corrections: [],
    },
    {
      period_month: "2026-08",
      md_reported: 3.7,
      status: null,
      note: "Przeliczona stawka",
      source: "manual",
      source_kind: "manual_correction",
      import_id: null,
      created_by_name: "Anna Przykładowa",
      updated_at: "2026-09-24T12:24:35Z",
      balance_after: 5.963,
      import_rows: [
        { import_id: 2, row_number: 12, order_number_hint: "4500030197", md_reported: 4, foreign: false },
      ],
      corrections: [
        { created_at: "2026-09-24T12:23:47Z", period_month: "2026-08", author_name: "Anna Przykładowa", from_md: 4, from_source: "import", to_md: 3.7, removed: false },
        { created_at: "2026-09-24T12:24:35Z", period_month: "2026-08", author_name: "Anna Przykładowa", from_md: 3.7, from_source: "manual", to_md: 3.7, removed: false },
      ],
    },
  ],
};

const LASKI_CONSUMPTIONS: LineConsumptionsResponse = {
  order_number: "4500030197",
  md_budget: 25,
  md_used: 44,
  md_remaining: -19,
  removed_months: [],
  foreign_import_warnings: [
    { period_month: "2026-08", order_number: "4500030845", md: 19, import_id: 2, row_number: 36 },
  ],
  rows: [
    {
      period_month: "2026-07",
      md_reported: 23,
      status: null,
      note: null,
      source: "import",
      source_kind: "import",
      import_id: 1,
      created_by_name: "Anna Przykładowa",
      updated_at: "2026-08-31T11:19:05Z",
      balance_after: 2,
      import_rows: [
        { import_id: 1, row_number: 30, order_number_hint: "4500030197", md_reported: 23, foreign: false },
      ],
      corrections: [],
    },
    {
      period_month: "2026-08",
      md_reported: 21,
      status: "protocol",
      note: null,
      source: "import",
      source_kind: "import",
      import_id: 2,
      created_by_name: "Anna Przykładowa",
      updated_at: "2026-09-23T11:40:03Z",
      balance_after: -19,
      import_rows: [
        { import_id: 2, row_number: 35, order_number_hint: "4500030197", md_reported: 2, foreign: false },
        { import_id: 2, row_number: 36, order_number_hint: "4500030845", md_reported: 19, foreign: true },
      ],
      corrections: [],
    },
  ],
};

const IMPORTS: ClientMdImportSummary[] = [
  {
    id: 2,
    period_month: "2026-08",
    filename: "zuzycie_MD_sierpien_2026.xlsx",
    created_at: "2026-09-23T11:40:03Z",
    uploaded_by_name: "Anna Przykładowa",
    rows_total: 4,
    rows_booked: 3,
    rows_to_verify: 1,
    rows_error: 0,
    md_booked: 25,
  },
  {
    id: 1,
    period_month: "2026-07",
    filename: "zuzycie_MD_lipiec_2026.xlsx",
    created_at: "2026-08-31T11:19:05Z",
    uploaded_by_name: "Anna Przykładowa",
    rows_total: 2,
    rows_booked: 2,
    rows_to_verify: 0,
    rows_error: 0,
    md_booked: 44.75,
  },
];

const IMPORT_DETAIL: ClientMdImportDetail = {
  ...IMPORTS[0],
  rows: [
    { id: 1, row_number: 12, consultant_name: "Konrad Teper", order_number_hint: "4500030197", target_order_number: "4500030197", target_group_id: 51, md_reported: 4, invoice_amount: null, state: "booked", state_label: "Zaksięgowano", status_label: "Zaktualizowano", status_reason: null, number_mismatch: false },
    { id: 2, row_number: 35, consultant_name: "Paweł Łaski", order_number_hint: "4500030197", target_order_number: "4500030197", target_group_id: 51, md_reported: 2, invoice_amount: null, state: "booked", state_label: "Zaksięgowano", status_label: "Zaktualizowano", status_reason: null, number_mismatch: false },
    { id: 3, row_number: 36, consultant_name: "Paweł Łaski", order_number_hint: "4500030845", target_order_number: "4500030197", target_group_id: 51, md_reported: 19, invoice_amount: null, state: "booked", state_label: "Zaksięgowano", status_label: "Zaktualizowano", status_reason: null, number_mismatch: true },
    { id: 4, row_number: 40, consultant_name: "Marta Przykładowa", order_number_hint: "4500031000", target_order_number: null, target_group_id: null, md_reported: 20, invoice_amount: null, state: "to_verify", state_label: "Do weryfikacji", status_label: "Wymaga przypisania", status_reason: "Osoba jest na dwóch zamówieniach klienta — wybierz zamówienie.", number_mismatch: false },
  ],
};

/** `events` domyślnie puste — to też stan do obejrzenia (pusta historia nie
 *  może wyglądać jak awaria pobrania). */
const CASES: Array<{
  title: string;
  why: string;
  group: OrderGroupRead;
  history?: OrderHistoryEntry[];
  consumptions?: Record<number, LineConsumptionsResponse>;
}> = [
  {
    title: "Ticket 7 — historia, „Zużycie MD” i importy (BIK 4500030197)",
    why:
      "Historia tylko biznesowa: import = jeden wpis z „Otwórz import →”, sześć edycji " +
      "Konrada Tepera = jeden wpis „▸ 6 zmian”, „Zakończono zamówienie” raz. Przycisk " +
      "„Zużycie · sie 3,7” z mini-wykresem; pomarańczowy przy ujemnym saldzie, braku " +
      "zejścia za poprzedni miesiąc albo wierszu importu do weryfikacji.",
    group: group({
      id: 51,
      client_id: 18,
      order_number: "4500030197",
      start_date: "2026-05-01",
      end_date: "2026-08-31",
      status: "active",
      event_count: 8,
      lines: [
        line({
          id: 145,
          group_id: 51,
          consultant_name: "Paweł Łaski",
          start_date: "2026-05-01",
          md_total: 25,
          md_remaining: -19,
          consumption_recent: [
            { period_month: "2026-07", md: 23 },
            { period_month: "2026-08", md: 2 },
          ],
          consumption_flags: ["negative_balance", "import_to_verify"],
        }),
        line({
          id: 146,
          group_id: 51,
          consultant_name: "Konrad Teper",
          start_date: "2026-05-01",
          md_total: 31.41,
          md_remaining: 5.963,
          consumption_recent: [
            { period_month: "2026-06", md: 12 },
            { period_month: "2026-07", md: 21.75 },
            { period_month: "2026-08", md: 3.7 },
          ],
          consumption_flags: [],
        }),
        line({
          id: 147,
          group_id: 51,
          consultant_name: "Ewa Bezzejścia",
          start_date: "2026-05-01",
          md_total: 20,
          md_remaining: 12,
          consumption_recent: [{ period_month: "2026-07", md: 8 }],
          consumption_flags: ["missing_previous_month"],
          consumption_missing_month: "2026-08",
        }),
      ],
      active_consultants: 3,
    }),
    history: BIK_HISTORY,
    consumptions: { 145: LASKI_CONSUMPTIONS, 146: TEPER_CONSUMPTIONS },
  },
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
    title: "Pełna historia osób na zamówieniu (zlecenie kosztowe)",
    why:
      "Aktywna osoba, osoba z zakończoną współpracą (wykorzystanie zostaje przy niej, " +
      "trzy decyzje), zastępca dodany ręcznie (kto, kiedy, za kogo, PDF podpięty) " +
      "i osoba usunięta z zamówienia z wykorzystaną kwotą.",
    group: group({
      id: 17,
      order_number: "SAP 4500987654",
      start_date: "2026-03-30",
      is_cost_based: true,
      budget_amount: 40000,
      budget_used: 40000,
      budget_remaining: 0,
      has_file: true,
      lines: [
        line({
          id: 30,
          consultant_name: "Ewa Nowak-Testowa",
          start_date: "2026-03-30",
          md_total: null,
          md_remaining: null,
          rate_revenue: 840,
          invoiced_total: 14280,
          unsettled_total: 0,
          origin: "document",
        }),
        line({
          id: 31,
          consultant_name: "Marian Odeszły",
          status: "completed",
          is_active: false,
          start_date: "2026-03-30",
          end_date: "2026-08-12",
          md_total: null,
          md_remaining: null,
          rate_revenue: 1280,
          invoiced_total: 25720,
          unsettled_total: 0,
          origin: "document",
          cooperation_ended_on: "2026-08-12",
        }),
        line({
          id: 32,
          consultant_name: "Tadeusz Zastępca",
          start_date: "2026-08-13",
          md_total: null,
          md_remaining: null,
          rate_revenue: 1280,
          invoiced_total: 0,
          unsettled_total: 0,
          origin: "manual",
          added_by_name: "Anna Przykładowa",
          added_at: "2026-08-13T09:00:00Z",
          replaces_name: "Marian Odeszły",
        }),
        line({
          id: 33,
          consultant_name: "Olga Usunięta",
          status: "completed",
          is_active: false,
          start_date: "2026-04-01",
          end_date: "2026-05-31",
          md_total: null,
          md_remaining: null,
          invoiced_total: 3000,
          unsettled_total: 0,
          origin: "manual",
          added_by_name: "Anna Przykładowa",
          added_at: "2026-04-01T10:00:00Z",
          removed_from_order: true,
        }),
      ],
      active_consultants: 2,
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
    title: "Zejście w trakcie zamówienia",
    why:
      "Osoba z zapisaną datą końca współpracy schodzi z aktywnej obsady, choć jej " +
      "linia jest w bazie wciąż aktywna (zamówienie MD kończy budżet, nie kalendarz). " +
      "„Zakończone” układają się datą zejścia malejąco, a historia — okres, zużycie, " +
      "kto kogo zastąpił — zostaje przy osobie.",
    group: group({
      id: 18,
      order_number: "CeZ/242/2025",
      end_date: "2026-12-31",
      active_consultants: 1,
      lines: [
        line({
          id: 20,
          consultant_name: "Ewa Aktywna",
          md_total: 60,
          md_remaining: 24,
          md_used: 36,
        }),
        line({
          id: 21,
          consultant_name: "Zenon Ostatni",
          status: "active",
          is_active: false,
          start_date: "2026-03-01",
          end_date: "2026-08-31",
          cooperation_ended_on: "2026-08-31",
          md_total: 50,
          md_remaining: 18,
          md_used: 32,
        }),
        line({
          id: 22,
          consultant_name: "Anna Wczesna",
          status: "completed",
          is_active: false,
          start_date: "2026-03-01",
          end_date: "2026-05-31",
          cooperation_ended_on: "2026-05-31",
          md_total: 40,
          md_remaining: 0,
          md_used: 40,
          replaced_by_order_id: 20,
          replaced_by_consultant_name: "Ewa Aktywna",
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
    history: [
      entry({
        key: "ev-104",
        category: "consumption",
        event_type: "transfer_md",
        type_label: "Przejęcie zużycia MD",
        created_at: "2026-08-20T08:05:00Z",
        summary:
          "Zamówienie zakończone — budżet MD wyczerpany, kontynuacja na " +
          "zamówieniu nr 4500029904",
      }),
      entry({
        key: "ev-103",
        category: "consumption",
        event_type: "transfer_md",
        type_label: "Przejęcie zużycia MD",
        created_at: "2026-08-20T08:00:00Z",
        summary:
          "Zamówienie zakończone — budżet MD wyczerpany, kontynuacja na " +
          "zamówieniu nr 4500029903",
        related_group_id: 16,
        related_order_number: "4500029903",
      }),
      entry({
        key: "import-import_md-9",
        category: "consumption",
        event_type: "import_md",
        type_label: "Import MD",
        created_at: "2026-08-05T08:00:00Z",
        summary: "Import MD za lipiec 2026 – 1 osoba, 20 MD",
        person_names: ["Jan Kowalski"],
        import_id: 9,
        import_period_month: "2026-07",
        import_people: 1,
        import_md: 20,
      }),
      entry({ key: "ev-101", summary: "Zamówienie utworzone przez import PDF." }),
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
  const [selectedImport, setSelectedImport] = useState<number | null>(null);

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
    // Historia i okno zużycia pobierają dane dopiero po rozwinięciu —
    // bez zasiania ich otwarcie trafiłoby w sieć.
    for (const item of CASES) {
      const people = [
        ...new Set((item.history ?? []).flatMap((e) => e.person_names)),
      ].sort();
      qc.setQueryData(orderHistoryQueryKey(item.group.client_id, item.group.id), {
        entries: item.history ?? [],
        people,
      });
      for (const ln of item.group.lines) {
        qc.setQueryData(
          lineConsumptionsQueryKey(item.group.client_id, item.group.id, ln.id),
          item.consumptions?.[ln.id] ?? { rows: [] },
        );
      }
    }
    qc.setQueryData(clientMdImportsQueryKey(18), { imports: IMPORTS });
    qc.setQueryData([...clientMdImportsQueryKey(18), 2], IMPORT_DETAIL);
    qc.setQueryData([...clientMdImportsQueryKey(18), 1], { ...IMPORTS[1], rows: [] });
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
              onResolveOffboarding={noop}
              onKeepHistory={noop}
              onReplaceLine={noop}
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

        <section className="flex flex-col gap-2" id="importy-md">
          <div>
            <h2 className="text-sm font-semibold">Zakładka „Importy MD” (profil klienta)</h2>
            <p className="text-xs text-muted-foreground">
              Lista importów, które dotknęły klienta; po otwarciu — wiersze ze statusem.
              Wiersz z numerem innym niż zamówienie docelowe jest wyróżniony.
            </p>
          </div>
          <ClientMdImportsTab
            clientId={18}
            selectedImportId={selectedImport}
            onSelectImport={setSelectedImport}
          />
        </section>
      </main>
    </QueryClientProvider>
  );
}
