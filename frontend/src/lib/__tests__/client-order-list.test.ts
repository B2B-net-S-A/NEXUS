import { describe, expect, it } from "vitest";

import type { ContractWithOrdersRead } from "@/lib/api/dlPortal";
import type { OrderGroupRead, OrderLineRead } from "@/lib/api/orderGroups";
import {
  DEFAULT_ORDER_LIST_FILTERS,
  consultantMatchesQuery,
  filterAndSortContractors,
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
    lines: [line(id, "Jan Kowalski")],
    active_consultants: 1,
    event_count: 0,
    future_orders: [],
    ...overrides,
  };
}

function contractor(
  contractId: number,
  candidateName: string,
  overrides: Partial<ContractWithOrdersRead> = {},
): ContractWithOrdersRead {
  return {
    contract_id: contractId,
    candidate_id: contractId,
    candidate_name: candidateName,
    contract_status: "active",
    contract_start_date: "2026-01-01",
    contract_end_date: "2026-12-31",
    rate_candidate: 100,
    rate_unit: "monthly",
    initial_job_id: null,
    initial_job_title: null,
    latest_order_id: null,
    latest_order_end_date: null,
    latest_order_rate_client: null,
    latest_order_monthly_margin: null,
    days_to_latest_end: null,
    orders: [],
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

  it("filtr 80% korzysta ze wspólnego budżetu MD grupy, nie z linii", () => {
    const near = group(1, "CP-MD-NEAR", {
      is_md_budget_based: true,
      md_budget_total: 100,
      md_budget_used: 80,
      md_budget_remaining: 20,
      lines: [
        line(1, "A B", {
          input_mode: null,
          input_value: null,
          md_total: null,
          md_remaining: null,
        }),
      ],
    });
    const below = group(2, "CP-MD-BELOW", {
      is_md_budget_based: true,
      md_budget_total: 100,
      md_budget_used: 79,
      md_budget_remaining: 21,
      lines: [
        line(2, "C D", {
          input_mode: null,
          input_value: null,
          md_total: null,
          md_remaining: null,
        }),
      ],
    });

    expect(
      filterAndSortOrderGroups(
        [below, near],
        "",
        { ...DEFAULT_ORDER_LIST_FILTERS, nearBudget: true },
        "2026-08-21",
      ).map((item) => item.id),
    ).toEqual([1]);
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

  it("sorts groups by the alphabetically first consultant, Z→A being the exact reverse", () => {
    const groups = [
      group(2, "B", { lines: [line(3, "Beata Lis")] }),
      group(3, "C", { lines: [line(4, "\u0141ukasz \u017b\u00f3\u0142\u0107")] }),
      // Grupa wielo-konsultantowa jedzie po SWOIM pierwszym alfabetycznie
      // nazwisku, nie po kolejności linii z serwera.
      group(1, "A", { lines: [line(1, "Zofia Nowak"), line(2, "Adam Kowalski")] }),
    ];
    const asc = filterAndSortOrderGroups([...groups], "", {
      ...DEFAULT_ORDER_LIST_FILTERS,
      sort: "consultant_asc",
    });
    expect(asc.map((item) => item.id)).toEqual([1, 2, 3]);

    const desc = filterAndSortOrderGroups([...groups], "", {
      ...DEFAULT_ORDER_LIST_FILTERS,
      sort: "consultant_desc",
    });
    // Odwrotność, a nie „grupa po ostatnim nazwisku" — inaczej grupa
    // [Adam, Zofia] stałaby na czele OBU porządków.
    expect(desc.map((item) => item.id)).toEqual([3, 2, 1]);
  });

  it("keeps a consultant-less order group last in both directions", () => {
    const groups = [
      group(9, "EMPTY", { lines: [] }),
      group(1, "A", { lines: [line(1, "Adam Kowalski")] }),
      group(2, "B", { lines: [line(2, "Zofia Nowak")] }),
    ];
    const ids = (sort: "consultant_asc" | "consultant_desc") =>
      filterAndSortOrderGroups([...groups], "", {
        ...DEFAULT_ORDER_LIST_FILTERS,
        sort,
      }).map((item) => item.id);
    // Pusty klucz nigdy nie otwiera listy „A\u2192Z" — tam użytkownik spodziewa
    // się realnego „A", nie wiersza bez konsultanta.
    expect(ids("consultant_asc")).toEqual([1, 2, 9]);
    expect(ids("consultant_desc")).toEqual([2, 1, 9]);
  });

  it("sorts contractors alphabetically with Polish folding", () => {
    const contractors = [
      contractor(3, "\u017banna Zaj\u0105c"),
      contractor(1, "\u0141ukasz Domaga\u0142a"),
      contractor(2, "Adam \u015awi\u0105tek"),
      contractor(4, ""),
    ];
    const names = (sort: "consultant_asc" | "consultant_desc") =>
      filterAndSortContractors([...contractors], "", {
        ...DEFAULT_ORDER_LIST_FILTERS,
        sort,
      }).map((item) => item.contract_id);
    // \u0141 sk\u0142ada si\u0119 do „l", \u015a do „s", \u017b do „z" \u2014 tak jak w wyszukiwarce
    // (`foldText`), wi\u0119c kolejno\u015b\u0107 to Adam < \u0141ukasz < \u017banna.
    expect(names("consultant_asc")).toEqual([2, 1, 3, 4]);
    expect(names("consultant_desc")).toEqual([3, 1, 2, 4]);
  });

  it("traktuje serwerowy myślnik jak brak konsultanta, nie jak nazwisko", () => {
    // `consultant_display_name` (backend) zwraca „—" dla linii bez kandydata.
    // Myślnik wypada w kolacji PRZED każdą literą, więc bez odsiania wiersz bez
    // konsultanta otwierałby listę „A→Z".
    const groups = [
      group(9, "DASH", { lines: [line(9, "—")] }),
      group(1, "A", { lines: [line(1, "Adam Kowalski")] }),
      group(2, "B", { lines: [line(2, "Zofia Nowak")] }),
    ];
    const ids = (sort: "consultant_asc" | "consultant_desc") =>
      filterAndSortOrderGroups([...groups], "", {
        ...DEFAULT_ORDER_LIST_FILTERS,
        sort,
      }).map((item) => item.id);
    expect(ids("consultant_asc")).toEqual([1, 2, 9]);
    expect(ids("consultant_desc")).toEqual([2, 1, 9]);
  });

  it("nie daje się wynieść na szczyt A→Z śmieciowi przyklejonemu do nazwiska", () => {
    // Realny wiersz z produkcji Nordei: „{ } Wojciech Łazowski". Backend keyuje
    // nazwiska po [a-z0-9], więc import go dopasowuje bez problemu — rozjazd był
    // wyłącznie w sortowaniu, gdzie `{` wypada przed każdą literą.
    const groups = [
      group(3, "C", { lines: [line(3, "{ } Wojciech Łazowski")] }),
      group(1, "A", { lines: [line(1, "Adam Kowalski")] }),
      group(2, "B", { lines: [line(2, "Zofia Nowak")] }),
    ];
    const ids = (sort: "consultant_asc" | "consultant_desc") =>
      filterAndSortOrderGroups([...groups], "", {
        ...DEFAULT_ORDER_LIST_FILTERS,
        sort,
      }).map((item) => item.id);
    // Ł składa się do „l", więc Adam < Wojciech < Zofia.
    expect(ids("consultant_asc")).toEqual([1, 3, 2]);
    expect(ids("consultant_desc")).toEqual([2, 3, 1]);
  });

  it("exports nested future orders in their visible order", () => {
    const future = group(2, "FUTURE");
    const current = group(1, "CURRENT", { future_orders: [future] });
    expect(flattenOrderGroupIds([current])).toEqual([1, 2]);
  });
});
