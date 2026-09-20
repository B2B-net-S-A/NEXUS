"use client";

/**
 * Harness wizualny Finanse → „Zmiany w zamówieniach".
 *
 * Renderuje produkcyjne `OrderChangesPanel` + `OrderChangesList` na
 * zahardkodowanych danych — bez react-query i bez żadnego zapytania, więc
 * strona może stać w `PUBLIC_PATHS`. Dane są fikcyjne.
 */

import { useMemo, useState } from "react";

import {
  OrderChangesList,
  OrderChangesPanel,
  type OrderChangesSubTab,
} from "@/components/finance/OrderChangesPanel";
import type { OrderChangesResponse } from "@/lib/api/finance";
import { monthOptions } from "@/lib/finance-order-changes";

const ref = (id: number, consultant: string, client: string, number: string) => ({
  order_id: id,
  order_group_id: null,
  contract_id: id + 100,
  client_id: id + 10,
  client_name: client,
  consultant_name: consultant,
  order_number: number,
});

const DATA: OrderChangesResponse = {
  period: { year: 2026, month: 9, label: "Wrzesień 2026" },
  counts: { changes: 6, entries: 2, exits: 2, ending: 2, gaps: 2 },
  changes: [
    {
      ...ref(1, "Jan Nowak", "Bank Przykładowy S.A.", "NB-2291"),
      kind: "rate_revenue",
      occurred_at: "2026-09-12T09:14:00Z",
      effective_date: "2026-09-12",
      old_amount: 152,
      new_amount: 170,
      old_unit: "hourly",
      new_unit: "hourly",
      currency: "PLN",
      old_date: null,
      new_date: null,
      is_whole_order: false,
      source: "user",
      author_name: "Anna Delivery",
      rate_cost: null,
      rate_revenue: null,
      rate_unit: null,
      other_client_names: [],
      previous_order_number: null,
      previous_end_date: null,
      previous_client_name: null,
      start_date: null,
      engagement_since: null,
    },
    {
      ...ref(2, "Adam Testowy", "Ubezpieczenia Demo", "UD-2295"),
      kind: "rate_cost",
      occurred_at: "2026-09-10T07:00:00Z",
      effective_date: "2026-09-10",
      old_amount: 120,
      new_amount: 125,
      old_unit: "hourly",
      new_unit: "hourly",
      currency: "PLN",
      old_date: null,
      new_date: null,
      is_whole_order: false,
      source: "system",
      author_name: null,
      rate_cost: null,
      rate_revenue: null,
      rate_unit: null,
      other_client_names: [],
      previous_order_number: null,
      previous_end_date: null,
      previous_client_name: null,
      start_date: null,
      engagement_since: null,
    },
    {
      ...ref(3, "Całe zamówienie (4 os.)", "Telekom Demo", "SAP 4500123456"),
      order_id: null,
      order_group_id: 77,
      kind: "end_date",
      occurred_at: "2026-09-05T13:40:00Z",
      effective_date: "2026-09-05",
      old_amount: null,
      new_amount: null,
      old_unit: null,
      new_unit: null,
      currency: null,
      old_date: "2026-09-30",
      new_date: "2026-12-31",
      is_whole_order: true,
      source: "user",
      author_name: "Piotr Delivery",
      rate_cost: null,
      rate_revenue: null,
      rate_unit: null,
      other_client_names: [],
      previous_order_number: null,
      previous_end_date: null,
      previous_client_name: null,
      start_date: null,
      engagement_since: null,
    },
    {
      ...ref(4, "Tomasz Przykładowy", "Bank Demo S.A.", "AB-1042"),
      kind: "additional_project",
      occurred_at: null,
      effective_date: "2026-09-14",
      old_amount: null,
      new_amount: null,
      old_unit: null,
      new_unit: null,
      currency: "PLN",
      old_date: null,
      new_date: null,
      is_whole_order: false,
      source: null,
      author_name: null,
      rate_cost: 960,
      rate_revenue: 1340,
      rate_unit: "md",
      other_client_names: ["Ubezpieczenia Demo"],
      previous_order_number: null,
      previous_end_date: null,
      previous_client_name: null,
      start_date: "2026-09-14",
      engagement_since: null,
    },
    {
      ...ref(9, "Adam Matecki", "Bank Przykładowy S.A.", "NB-2291"),
      kind: "order_continuation",
      occurred_at: null,
      effective_date: "2026-09-01",
      old_amount: null,
      new_amount: null,
      old_unit: null,
      new_unit: null,
      currency: "PLN",
      old_date: null,
      new_date: null,
      is_whole_order: false,
      source: null,
      author_name: null,
      rate_cost: 120,
      rate_revenue: 152,
      rate_unit: "hourly",
      other_client_names: [],
      previous_order_number: "NB-1980",
      previous_end_date: "2026-08-31",
      previous_client_name: "Bank Przykładowy S.A.",
      start_date: "2026-09-01",
      engagement_since: null,
    },
    {
      ...ref(10, "Piotr Żukowski", "Telekom Demo", "TD-330"),
      kind: "client_change",
      occurred_at: null,
      effective_date: "2026-09-08",
      old_amount: null,
      new_amount: null,
      old_unit: null,
      new_unit: null,
      currency: "PLN",
      old_date: null,
      new_date: null,
      is_whole_order: false,
      source: null,
      author_name: null,
      rate_cost: 140,
      rate_revenue: 185,
      rate_unit: "hourly",
      other_client_names: [],
      previous_order_number: "UD-12",
      previous_end_date: "2026-08-29",
      previous_client_name: "Ubezpieczenia Demo",
      start_date: "2026-09-08",
      engagement_since: null,
    },
  ],
  entries: [
    {
      ...ref(11, "Adam Grono", "Bank Przykładowy S.A.", "NB-2301"),
      start_date: "2026-09-02",
      end_date: "2026-12-31",
      rate_cost: 120,
      rate_revenue: 152,
      rate_unit: "hourly",
      currency: "PLN",
      order_type: "periodic",
      status: "active",
    },
    {
      ...ref(2, "Alicja Kalbarczyk", "Bank Przykładowy S.A.", "NB-2295"),
      start_date: "2026-09-21",
      end_date: null,
      rate_cost: 130,
      rate_revenue: 170,
      rate_unit: "hourly",
      currency: "PLN",
      order_type: "periodic",
      status: "draft",
    },
  ],
  // Zejścia = zapisany koniec współpracy. Kończące się zamówienia = zamówienie
  // dobiega końca, a współpraca trwa. Werdykt jest tu jedynym rozróżnieniem.
  exits: [
    {
      ...ref(7, "Olga Wiśniewska", "Ubezpieczenia Demo", "UD-12"),
      end_date: "2026-09-15",
      start_date: "2026-01-01",
      rate_cost: 100,
      rate_revenue: 140,
      rate_unit: "hourly",
      currency: "PLN",
      order_type: "cost",
      verdict: "ended_intent",
      verdict_label: "Współpraca zakończona (umowa wypowiedziana)",
      intent: "contract_ended",
    },
    {
      ...ref(8, "Robert Adamczyk", "Telekom Demo", "SAP 4500222222"),
      end_date: "2026-09-30",
      start_date: "2026-02-01",
      rate_cost: 850,
      rate_revenue: 1100,
      rate_unit: "md",
      currency: "PLN",
      order_type: "md",
      verdict: "ended_intent",
      verdict_label: "Zastąpiony innym konsultantem na zamówieniu",
      intent: "replaced",
    },
  ],
  ending_orders: [
    {
      ...ref(5, "Ewa Kowalska", "Telekom Demo", "SAP 4500111111"),
      end_date: "2026-09-30",
      start_date: "2026-04-01",
      rate_cost: 900,
      rate_revenue: 1200,
      rate_unit: "md",
      currency: "PLN",
      order_type: "md",
      verdict: "ending_pending",
      verdict_label: "Kończy się 30.09.2026 — na razie brak kolejnego zamówienia",
      intent: null,
    },
    {
      ...ref(6, "Marek Zieliński", "Energetyka Demo", "ED-77"),
      end_date: "2026-09-05",
      start_date: "2026-03-01",
      rate_cost: 110,
      rate_revenue: 150,
      rate_unit: "hourly",
      currency: "PLN",
      order_type: "periodic",
      verdict: "no_successor",
      verdict_label: "Brak kolejnego zamówienia — do usunięcia z rozliczeń",
      intent: null,
    },
  ],
  gaps: [
    {
      ...ref(6, "Marek Zieliński", "Energetyka Demo", "ED-77"),
      gap_id: 1,
      ended_on: "2026-09-05",
      detected_on: "2026-09-06",
      status: "open",
      resolved_order_number: null,
      resolved_at: null,
      delay_days: null,
    },
    {
      ...ref(8, "Kamil Nowicki", "Bank Demo S.A.", "AB-0999"),
      gap_id: 2,
      ended_on: "2026-08-31",
      detected_on: "2026-09-01",
      status: "filled_late",
      resolved_order_number: "AB-1101",
      resolved_at: "2026-09-08T10:00:00Z",
      delay_days: 7,
    },
  ],
  changes_tracked_since: "2026-09-01T00:00:00Z",
  gaps_tracked_since: "2026-08-01",
  open_gaps_total: 1,
};

export default function FinanceOrderChangesPreview() {
  const [subTab, setSubTab] = useState<OrderChangesSubTab>("changes");
  const months = useMemo(() => monthOptions(new Date(2026, 8, 14)), []);
  const [month, setMonth] = useState("2026-09");
  const [search, setSearch] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [client, setClient] = useState<string | null>(null);

  // Picker klienta odpytuje `/api/clients-lookup`, a harness musi wykonywać
  // ZERO zapytań — stąd atrapa z tą samą wysokością i rolą.
  const clientPicker = (
    <select
      aria-label="Klient"
      value={client ?? ""}
      onChange={(event) => setClient(event.target.value || null)}
      className="h-9 rounded-md border border-border bg-background px-3 text-sm text-foreground"
    >
      <option value="">Wszyscy klienci</option>
      <option value="Bank Przykładowy S.A.">Bank Przykładowy S.A.</option>
      <option value="Telekom Demo">Telekom Demo</option>
    </select>
  );

  return (
    <div className="mx-auto max-w-[1100px] space-y-4 p-4 sm:p-6">
      <h1 className="text-lg font-semibold">Zmiany w zamówieniach — podgląd</h1>
      <OrderChangesPanel
        data={DATA}
        body={
          <OrderChangesList
            data={DATA}
            subTab={subTab}
            onOpenGaps={() => setSubTab("gaps")}
          />
        }
        subTab={subTab}
        onSubTabChange={setSubTab}
        month={month}
        months={months}
        onMonthChange={setMonth}
        onExport={() => undefined}
        exporting={false}
        filters={{
          search,
          onSearchChange: setSearch,
          dateFrom,
          onDateFromChange: setDateFrom,
          dateTo,
          onDateToChange: setDateTo,
          clientPicker,
          clientLabel: client,
          onClearClient: () => setClient(null),
          onClearDates: () => {
            setDateFrom("");
            setDateTo("");
          },
          onClearAll: () => {
            setSearch("");
            setDateFrom("");
            setDateTo("");
            setClient(null);
          },
        }}
      />
    </div>
  );
}
