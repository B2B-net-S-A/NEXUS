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
      is_continuation: false,
      previous_order_number: null,
      previous_end_date: null,
      additional_project: false,
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
      successor_order_number: null,
      successor_start_date: null,
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
}: {
  data?: OrderChangesResponse | null;
  initial?: OrderChangesSubTab;
}) {
  const [subTab, setSubTab] = useState<OrderChangesSubTab>(initial);
  return (
    <OrderChangesPanel
      data={data}
      body={
        data ? (
          <OrderChangesList data={data} subTab={subTab} onOpenGaps={() => setSubTab("gaps")} />
        ) : (
          <p>Wczytywanie</p>
        )
      }
      subTab={subTab}
      onSubTabChange={setSubTab}
      month="2026-09"
      months={monthOptions(new Date(2026, 8, 14))}
      onMonthChange={vi.fn()}
      onExport={vi.fn()}
      exporting={false}
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
});
