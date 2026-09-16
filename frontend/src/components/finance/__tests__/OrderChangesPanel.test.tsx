import { fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import {
  OrderChangesList,
  OrderChangesPanel,
  type OrderChangesSubTab,
} from "@/components/finance/OrderChangesPanel";
import type { OrderChangesResponse } from "@/lib/api/finance";
import { monthOptions } from "@/lib/finance-order-changes";

const ref = {
  order_group_id: null,
  contract_id: 1,
  client_id: 2,
  client_name: "Klient Demo",
  order_number: "NB-1",
};

const DATA: OrderChangesResponse = {
  period: { year: 2026, month: 9, label: "Wrzesień 2026" },
  counts: { changes: 0, entries: 1, exits: 1, gaps: 2 },
  changes: [],
  entries: [
    {
      ...ref,
      order_id: 10,
      consultant_name: "Jan Nowak",
      start_date: "2026-09-01",
      end_date: null,
      rate_cost: 120,
      rate_revenue: 152,
      rate_unit: "hourly",
      currency: "PLN",
      order_type: "periodic",
      status: "active",
    },
  ],
  exits: [
    {
      ...ref,
      order_id: 11,
      consultant_name: "Ewa Kowalska",
      end_date: "2026-09-05",
      start_date: "2026-01-01",
      rate_cost: 100,
      rate_revenue: 140,
      rate_unit: "hourly",
      currency: "PLN",
      order_type: "cost",
      verdict: "no_successor",
      verdict_label: "Brak kolejnego zamówienia — do usunięcia z rozliczeń",
      intent: null,
    },
  ],
  gaps: [
    {
      ...ref,
      order_id: 11,
      consultant_name: "Ewa Kowalska",
      gap_id: 1,
      ended_on: "2026-09-05",
      detected_on: "2026-09-06",
      status: "open",
      resolved_order_number: null,
      resolved_at: null,
      delay_days: null,
    },
    {
      ...ref,
      order_id: 12,
      consultant_name: "Kamil Nowicki",
      gap_id: 2,
      ended_on: "2026-08-31",
      detected_on: "2026-09-01",
      status: "filled_late",
      resolved_order_number: "NB-9",
      resolved_at: "2026-09-08T10:00:00Z",
      delay_days: 7,
    },
  ],
  changes_tracked_since: null,
  gaps_tracked_since: "2026-08-01",
  open_gaps_total: 1,
};

function Harness({
  data = DATA,
  initial = "entries",
  onExport = vi.fn(),
  filtersActive = false,
}: {
  data?: OrderChangesResponse | null;
  initial?: OrderChangesSubTab;
  onExport?: () => void;
  filtersActive?: boolean;
}) {
  const [subTab, setSubTab] = useState<OrderChangesSubTab>(initial);
  const [search, setSearch] = useState(filtersActive ? "kowalska" : "");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  return (
    <OrderChangesPanel
      data={data}
      body={
        data ? (
          <OrderChangesList
            data={data}
            subTab={subTab}
            onOpenGaps={() => setSubTab("gaps")}
            filtersActive={Boolean(search || dateFrom || dateTo)}
          />
        ) : (
          <p>Wczytywanie</p>
        )
      }
      subTab={subTab}
      onSubTabChange={setSubTab}
      month="2026-09"
      months={monthOptions(new Date(2026, 8, 14))}
      onMonthChange={vi.fn()}
      onExport={onExport}
      exporting={false}
      filters={{
        search,
        onSearchChange: setSearch,
        dateFrom,
        onDateFromChange: setDateFrom,
        dateTo,
        onDateToChange: setDateTo,
        clientPicker: <span data-testid="client-picker" />,
        clientLabel: null,
        onClearClient: vi.fn(),
        onClearDates: () => {
          setDateFrom("");
          setDateTo("");
        },
        onClearAll: () => {
          setSearch("");
          setDateFrom("");
          setDateTo("");
        },
      }}
    />
  );
}

describe("OrderChangesPanel", () => {
  it("shows the four sub-tabs with their counts", () => {
    render(<Harness />);
    const tabs = screen.getAllByRole("tab");
    expect(tabs.map((tab) => tab.textContent)).toEqual([
      "Zmiany0",
      "Wejścia1",
      "Zejścia1",
      "Braki2",
    ]);
  });

  it("does not claim zero before the data arrives", () => {
    render(<Harness data={null} />);
    expect(screen.getByRole("tab", { name: "Braki" }).textContent).toBe("Braki");
  });

  it("lists entries with the order type and points to open gaps", () => {
    render(<Harness />);
    const row = screen.getByText("Jan Nowak").closest("li")!;
    expect(within(row).getByText("B2B")).toBeInTheDocument();
    expect(within(row).getByText("Nowy konsultant")).toBeInTheDocument();
    expect(row.textContent).toContain("przychód 152,00 zł/h");

    fireEvent.click(screen.getByRole("button", { name: "sprawdź podzakładkę Braki" }));
    expect(screen.getByText("Brak zamówienia")).toBeInTheDocument();
    expect(
      screen.getByText("Uzupełnione z opóźnieniem: zam. NB-9 (7 dni po terminie)"),
    ).toBeInTheDocument();
  });

  it("tells finance that change history starts with the deployment", () => {
    render(<Harness initial="changes" />);
    expect(screen.getByText(/Dziennik zmian stawek i dat działa od wdrożenia/)).toBeInTheDocument();
  });

  it("names the date filter after the active sub-tab", () => {
    render(<Harness initial="entries" />);
    expect(screen.getByLabelText("Data wejścia od")).toBeInTheDocument();

    // Radix aktywuje zakładkę na `mousedown`, nie na `click`.
    fireEvent.mouseDown(screen.getByRole("tab", { name: /Zejścia/ }));
    expect(screen.getByLabelText("Data zejścia od")).toBeInTheDocument();
    expect(screen.queryByLabelText("Data wejścia od")).not.toBeInTheDocument();
  });

  it("exports the sub-tab the user is looking at", () => {
    const onExport = vi.fn();
    render(<Harness initial="gaps" onExport={onExport} />);

    const button = screen.getByRole("button", { name: "Eksport do Excela: Braki" });
    fireEvent.click(button);
    expect(onExport).toHaveBeenCalledTimes(1);
  });

  it("shows an active filter as a removable chip", () => {
    render(<Harness filtersActive />);
    const chip = screen.getByText("Szukaj: kowalska");
    expect(chip).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Usuń filtr: Szukaj: kowalska" }));
    expect(screen.queryByText("Szukaj: kowalska")).not.toBeInTheDocument();
  });

  it("clears both dates in one call, so the URL cannot keep a stale bound", () => {
    const onClearDates = vi.fn();
    render(
      <OrderChangesPanel
        data={DATA}
        body={null}
        subTab="changes"
        onSubTabChange={vi.fn()}
        month="2026-09"
        months={monthOptions(new Date(2026, 8, 14))}
        onMonthChange={vi.fn()}
        onExport={vi.fn()}
        exporting={false}
        filters={{
          search: "",
          onSearchChange: vi.fn(),
          dateFrom: "2026-09-01",
          onDateFromChange: vi.fn(),
          dateTo: "2026-09-30",
          onDateToChange: vi.fn(),
          clientPicker: null,
          clientLabel: null,
          onClearClient: vi.fn(),
          onClearDates,
          onClearAll: vi.fn(),
        }}
      />,
    );

    fireEvent.click(
      screen.getByRole("button", {
        name: "Usuń filtr: Data zmiany: od 01.09.2026 do 30.09.2026",
      }),
    );
    expect(onClearDates).toHaveBeenCalledTimes(1);
  });

  it("says a filter hid the rows instead of claiming the month was empty", () => {
    const empty = { ...DATA, entries: [], counts: { ...DATA.counts, entries: 0 } };
    render(<Harness data={empty} filtersActive />);
    expect(
      screen.getByText("Żaden wiersz nie pasuje do ustawionych filtrów."),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Nikt nie rozpoczął z nami współpracy/)).toBeNull();
  });
});
