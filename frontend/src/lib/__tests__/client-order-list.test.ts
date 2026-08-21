import { describe, expect, it } from "vitest";

import type { OrderGroupRead, OrderLineRead } from "@/lib/api/orderGroups";
import {
  DEFAULT_ORDER_LIST_FILTERS,
  consultantMatchesQuery,
  filterAndSortOrderGroups,
  flattenOrderGroupIds,
  sortOrderLinesByConsultant,
} from "@/lib/client-order-list";

function line(
  id: number,
  consultantName: string,
  overrides: Partial<OrderLineRead> = {},
): OrderLineRead {
  return {
    id,
    group_id: 1,
    contract_id: id,
    candidate_id: id,
    consultant_name: consultantName,
    job_id: null,
    job_title: null,
    status: "active",
    is_active: true,
    start_date: "2026-01-01",
    end_date: "2026-12-31",
    rate_cost: 100,
    rate_revenue: 150,
    input_value: 100,
    input_mode: "md",
    md_total: 100,
    md_remaining: 50,
    md_manual_adjustment: 0,
    predecessor_order_id: null,
    predecessor_consultant_name: null,
    invoiced_total: null,
    unsettled_total: null,
    missing_consumption_month: null,
    ...overrides,
  };
}

function group(
  id: number,
  orderNumber: string,
  overrides: Partial<OrderGroupRead> = {},
): OrderGroupRead {
  return {
    id,
    client_id: 10,
    order_number: orderNumber,
    start_date: "2026-01-01",
    end_date: "2026-12-31",
    notes: null,
    created_at: `2026-08-${String(id).padStart(2, "0")}T10:00:00Z`,
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
    filename: null,
    has_file: false,
    content_type: null,
    size_bytes: null,
    file_uploaded_at: null,
    can_add_consultant: true,
    lines: [line(id, "Jan Kowalski")],
    active_consultants: 1,
    event_count: 0,
    future_orders: [],
    ...overrides,
  };
}

describe("client order list filters", () => {
  it("matches first and last name fragments in either order and without accents", () => {
    expect(consultantMatchesQuery("Łukasz Żółć", "zol luk")).toBe(true);
    expect(consultantMatchesQuery("Łukasz Żółć", "Anna Żółć")).toBe(false);
  });

  it("keeps the whole multi-consultant order when one consultant matches", () => {
    const item = group(1, "274607", {
      lines: [line(1, "Anna Nowak"), line(2, "Zofia Kowalska")],
    });
    expect(
      filterAndSortOrderGroups(
        [item],
        "Kowal Zof",
        DEFAULT_ORDER_LIST_FILTERS,
      ),
    ).toEqual([item]);
  });

  it("filters at 80% budget usage and combines it with ending-soon", () => {
    const near = group(1, "A", {
      end_date: "2026-09-10",
      lines: [line(1, "A B", { md_total: 100, md_remaining: 20 })],
    });
    const below = group(2, "B", {
      end_date: "2026-09-10",
      lines: [line(2, "C D", { md_total: 100, md_remaining: 21 })],
    });
    const result = filterAndSortOrderGroups(
      [below, near],
      "",
      {
        ...DEFAULT_ORDER_LIST_FILTERS,
        nearBudget: true,
        endingSoon: true,
        endingDays: 30,
      },
      "2026-08-21",
    );
    expect(result.map((item) => item.id)).toEqual([1]);
  });

  it("sorts groups by average consultant rate and lines alphabetically", () => {
    const cheaper = group(1, "A", {
      lines: [
        line(1, "Zofia Nowak", { rate_cost: 100 }),
        line(2, "Adam Kowalski", { rate_cost: 200 }),
      ],
    });
    const dearer = group(2, "B", {
      lines: [line(3, "Beata Lis", { rate_cost: 175 })],
    });
    expect(
      filterAndSortOrderGroups(
        [cheaper, dearer],
        "",
        { ...DEFAULT_ORDER_LIST_FILTERS, sort: "cost_desc" },
      ).map((item) => item.id),
    ).toEqual([2, 1]);
    expect(
      sortOrderLinesByConsultant(cheaper.lines).map((item) => item.consultant_name),
    ).toEqual(["Adam Kowalski", "Zofia Nowak"]);
  });

  it("exports nested future orders in their visible order", () => {
    const future = group(2, "FUTURE");
    const current = group(1, "CURRENT", { future_orders: [future] });
    expect(flattenOrderGroupIds([current])).toEqual([1, 2]);
  });
});
