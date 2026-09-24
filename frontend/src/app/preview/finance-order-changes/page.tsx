"use client";

/**
 * Harness wizualny Finanse → „Zmiany w zamówieniach".
 *
 * Renderuje produkcyjne `OrderChangesPanel` + `OrderChangesList` na
 * zahardkodowanych danych — bez react-query i bez żadnego zapytania do API,
 * więc strona może stać w `PUBLIC_PATHS`. Dane są fikcyjne. „Zrobione"
 * zapisuje się tylko w stanie strony; podgląd PDF-u czyta plik statyczny
 * harnessu `/preview/cv-search` (ten sam origin, nie API).
 *
 * `?panel=1` otwiera od razu panel podglądu pierwszej karty.
 */

import { useEffect, useMemo, useState } from "react";

import {
  OrderChangesList,
  OrderChangesPanel,
  type OrderChangesSubTab,
} from "@/components/finance/OrderChangesPanel";
import type {
  OrderChangesResponse,
  OrderHistoryEntry,
  OrderPdfRef,
} from "@/lib/api/finance";
import {
  boardItems,
  cardItemsAllTabs,
  statusCounts,
  withCheck,
  type StatusFilter,
} from "@/lib/finance-order-board";
import { monthOptions } from "@/lib/finance-order-changes";

// Ten sam klient = to samo id (kafelki klientów grupują po id).
const CLIENT_IDS: Record<string, number> = {};
const clientId = (name: string) =>
  (CLIENT_IDS[name] ??= Object.keys(CLIENT_IDS).length + 11);

const ref = (id: number, consultant: string, client: string, number: string) => ({
  order_id: id,
  order_group_id: null,
  contract_id: id + 100,
  client_id: clientId(client),
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
  // Zejścia = zapisany koniec współpracy. Zamówienia bez kontynuacji = zamówienie
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
    // Zamówienie kończy się w ostatnim dniu miesiąca — brak wykryje się
    // dopiero w październiku, więc we wrześniu stoi tutaj. Marek (ED-77) ma
    // brak wykryty we wrześniu i stoi WYŁĄCZNIE w Brakach (audyt 24.09.2026).
    {
      ...ref(11, "Tomasz Lis", "Energetyka Demo", "ED-81"),
      end_date: "2026-09-30",
      start_date: "2026-03-01",
      rate_cost: 110,
      rate_revenue: 150,
      rate_unit: "hourly",
      currency: "PLN",
      order_type: "periodic",
      verdict: "no_successor",
      verdict_label: "Zamówienie się skończyło, brak kolejnego — współpraca trwa",
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

const PDF = (id: number, name: string): OrderPdfRef => ({
  kind: "order",
  id,
  month: "2026-09",
  client_id: 11,
  download_name: name,
});

type Item = { order_id: number | null; item_key?: string };

/** Pola karty zamówienia, które w aplikacji dokłada serwer (0354). */
function enrich(data: OrderChangesResponse): OrderChangesResponse {
  let seq = 0;
  const decorate = <T extends Item>(tab: string, list: T[]): T[] =>
    list.map((item) => {
      seq += 1;
      const id = item.order_id ?? 0;
      return {
        ...item,
        item_key: `${tab}:${seq}`,
        order_start: "2026-09-01",
        order_end: id % 3 === 0 ? null : "2026-12-31",
        pdf: id % 2 === 0 ? null : PDF(id, `Zamowienie_${id}.pdf`),
        done:
          seq % 4 === 0
            ? { by_name: "Anna Finanse", at: "2026-09-18T09:14:00Z" }
            : null,
        entered_at: "2026-09-17T07:59:00Z",
        entered_by: seq % 5 === 0 ? null : "Anna Delivery",
        entered_automatically: seq % 5 === 0,
        from_order_mail: seq % 5 === 0,
      };
    });
  return {
    ...data,
    can_check: true,
    changes: decorate("changes", data.changes),
    entries: decorate("entries", data.entries),
    exits: decorate("exits", data.exits),
    ending_orders: decorate("ending", data.ending_orders),
    gaps: decorate("gaps", data.gaps),
    superseded: [
      {
        item_key: "ending:old",
        tab: "ending",
        order_id: 6,
        order_group_id: null,
        summary: "Koniec zamówienia 14.09.2026 — kończy się",
        done: { by_name: "Anna Finanse", at: "2026-09-10T12:00:00Z" },
      },
    ],
  };
}

const HISTORY: OrderHistoryEntry[] = [
  {
    at: "2026-09-21T12:41:00Z",
    kind: "change",
    summary: "Zmiana daty końca: 30.11.2026 → 31.12.2026",
    by_name: "Anna Delivery",
    automatic: false,
  },
  {
    at: "2026-09-18T11:20:00Z",
    kind: "checked",
    summary: "Zmiana daty końca: 14.09.2026 → 30.11.2026",
    by_name: "Anna Finanse",
    automatic: false,
  },
];

async function loadStaticPdf(): Promise<Blob> {
  const response = await fetch("/preview/cv-search/cv-tekst.pdf");
  if (!response.ok) throw new Error("brak pliku");
  return response.blob();
}

export default function FinanceOrderChangesPreview() {
  const [subTab, setSubTab] = useState<OrderChangesSubTab>("changes");
  const [data, setData] = useState<OrderChangesResponse>(() => enrich(DATA));
  const [status, setStatus] = useState<StatusFilter>("todo");
  const [tile, setTile] = useState<string | null>(null);
  const [previewCard, setPreviewCard] = useState<string | null>(null);
  // Po montowaniu, nie w inicjalizatorze — inaczej serwer i przeglądarka
  // wyrenderowałyby co innego (błąd hydracji).
  useEffect(() => {
    if (new URLSearchParams(window.location.search).get("panel") === "1") {
      setPreviewCard("o:1");
    }
  }, []);
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
    <div className="mx-auto max-w-[1400px] space-y-4 p-4 sm:p-6">
      <h1 className="text-lg font-semibold">Zmiany w zamówieniach — podgląd</h1>
      <OrderChangesPanel
        data={data}
        body={
          <OrderChangesList
            data={data}
            subTab={subTab}
            onOpenGaps={() => setSubTab("gaps")}
            board={{
              status,
              selectedClient: tile,
              onSelectClient: (next) => {
                setPreviewCard(null);
                setTile(next);
              },
              onToggle: (item, done) =>
                setData((current) =>
                  withCheck(
                    current,
                    item.key,
                    done
                      ? { by_name: "Ty (podgląd)", at: new Date().toISOString() }
                      : null,
                  ),
                ),
              pendingKeys: new Set(),
              onDownloadPdf: () => undefined,
              downloadingPdf: null,
              previewCard,
              onPreviewCard: setPreviewCard,
              preview: {
                itemsForCard: (cardKey) => cardItemsAllTabs(data, cardKey),
                history: { items: HISTORY, loading: false, failed: false },
                loadPdf: loadStaticPdf,
                onOpenInPdfs: () => undefined,
              },
            }}
          />
        }
        subTab={subTab}
        onSubTabChange={(next) => {
          setPreviewCard(null);
          setSubTab(next);
        }}
        status={status}
        onStatusChange={setStatus}
        statusCounts={statusCounts(boardItems(data, subTab))}
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
