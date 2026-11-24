import { afterEach, describe, expect, it, vi } from "vitest";

import type { ClientOrderRead, ContractWithOrdersRead } from "@/lib/api/dlPortal";
import type { OrderGroupRead, OrderLineRead } from "@/lib/api/orderGroups";
import {
  DEFAULT_ORDER_LIST_FILTERS,
  buildOrderGroupFamilies,
  clientUsesSharedMdPool,
  consultantMatchesQuery,
  contractorMatchesPill,
  contractorMatchesQuery,
  contractorOrderType,
  daysUntil,
  endingGroupWithoutSuccessor,
  endingOrderWithoutSuccessor,
  endingWithoutSuccessorOrderId,
  endsInPhrase,
  endsWithoutSuccessorWithin,
  filterAndSortContractors,
  filterAndSortOrderGroups,
  localTodayIso,
  orderGroupContractIds,
  orderGroupMatchesPill,
  orderGroupMatchesQuery,
  orderGroupMetrics,
  primaryOrder,
  representativeOrder,
  resolveOrderFocus,
  sortOrderLinesByEnd,
  sortUnifiedOrderItems,
  usesSharedMdPool,
  visibleLegacyOrderIds,
  type OrderListFilters,
  type OrderSort,
  type UnifiedOrderListItem,
} from "@/lib/client-order-list";

const TODAY = "2026-12-20";

function line(id: number, name: string, overrides: Partial<OrderLineRead> = {}): OrderLineRead {
  return {
    id,
    group_id: 1,
    contract_id: id,
    candidate_id: id,
    consultant_name: name,
    job_id: null,
    md_optional_total: null,
    md_base_used: null,
    md_optional_used: null,
    replaced_by_order_id: null,
    replaced_by_consultant_name: null,
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
  } as OrderLineRead;
}

function group(id: number, overrides: Partial<OrderGroupRead> = {}): OrderGroupRead {
  return {
    id,
    client_id: 10,
    order_number: `T-${id}`,
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
    lines: [line(id, "Jan Testowy")],
    active_consultants: 1,
    event_count: 0,
    future_orders: [],
    ...overrides,
  } as OrderGroupRead;
}

function order(id: number, overrides: Partial<ClientOrderRead> = {}): ClientOrderRead {
  return {
    id,
    client_id: 10,
    contract_id: id,
    job_id: null,
    framework_contract_id: null,
    title: `ZAM-${id}`,
    description: null,
    status: "active",
    order_type: "periodic",
    start_date: "2026-01-01",
    end_date: "2026-12-31",
    rate_client: 150,
    total_value: null,
    md_quantity: null,
    currency: "PLN",
    project_part: null,
    filename: null,
    has_file: false,
    content_type: null,
    size_bytes: null,
    created_by_user_id: null,
    notes: null,
    created_at: `2026-04-${String(id).padStart(2, "0")}T10:00:00Z`,
    updated_at: `2026-04-${String(id).padStart(2, "0")}T10:00:00Z`,
    candidate_id: id,
    candidate_name: `Kandydat ${id}`,
    contract_status: "active",
    job_title: null,
    monthly_margin: null,
    days_to_end: null,
    ...overrides,
  } as ClientOrderRead;
}

function contractor(id: number, name: string, overrides: Partial<ContractWithOrdersRead> = {}): ContractWithOrdersRead {
  return {
    contract_id: id,
    candidate_id: id,
    candidate_name: name,
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
  } as ContractWithOrdersRead;
}

const filters = (over: Partial<OrderListFilters> = {}): OrderListFilters => ({
  ...DEFAULT_ORDER_LIST_FILTERS,
  ...over,
});

afterEach(() => vi.useRealTimers());

describe("dziś i dni", () => {
  it("localTodayIso bez argumentu = kalendarz lokalny", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 11, 31, 23, 30));
    expect(localTodayIso()).toBe("2026-12-31");
  });
  it("endsInPhrase: null, ujemne, zero, 1, wiele", () => {
    expect(endsInPhrase(null)).toBe("");
    expect(endsInPhrase(-3)).toBe("dziś");
    expect(endsInPhrase(0)).toBe("dziś");
    expect(endsInPhrase(1)).toBe("za 1 dzień");
    expect(endsInPhrase(12)).toBe("za 12 dni");
  });
  it("daysUntil: brak daty, przez granicę roku, minęło", () => {
    expect(daysUntil(null, TODAY)).toBeNull();
    expect(daysUntil("2027-01-01T00:00:00Z", "2026-12-31")).toBe(1);
    expect(daysUntil("2026-12-01", TODAY)).toBe(-19);
  });
});

describe("wyszukiwanie", () => {
  it("puste zapytanie i same separatory pasują do wszystkiego", () => {
    expect(consultantMatchesQuery("Jan Testowy", "")).toBe(true);
    expect(consultantMatchesQuery("Jan Testowy", " / . ")).toBe(true);
    expect(orderGroupMatchesQuery(group(1), "  ")).toBe(true);
  });
  it("numer zamówienia, osoba w przyszłym zamówieniu, brak trafienia", () => {
    const g = group(1, {
      order_number: "PO-ABC",
      future_orders: [group(2, { lines: [line(2, "Anna Przykładowa")] })],
    });
    expect(orderGroupMatchesQuery(g, "abc")).toBe(true);
    expect(orderGroupMatchesQuery(g, "przykladowa")).toBe(true);
    expect(orderGroupMatchesQuery(g, "nikt")).toBe(false);
  });
  it("kontraktor: puste zapytanie, po tytule zamówienia", () => {
    const c = contractor(1, "Jan Testowy", { orders: [order(1, { title: "Projekt Zielony" })] });
    expect(contractorMatchesQuery(c, "")).toBe(true);
    expect(contractorMatchesQuery(c, "zielony")).toBe(true);
    expect(contractorMatchesQuery(c, "czerwony")).toBe(false);
  });
});

describe("sortOrderLinesByEnd", () => {
  it("dwie linie bez dat: alfabetycznie; data współpracy wygrywa z końcem linii", () => {
    const sorted = sortOrderLinesByEnd([
      line(1, "Zenon", { end_date: null, cooperation_ended_on: null }),
      line(2, "Adam", { end_date: null, cooperation_ended_on: null }),
      line(3, "Celina", { end_date: "2026-01-31", cooperation_ended_on: "2027-01-01" }),
    ]);
    expect(sorted.map((l) => l.id)).toEqual([3, 2, 1]);
  });
});

describe("wspólna pula MD i metryki", () => {
  it("klienci z pulą i flagi z serwera", () => {
    expect(clientUsesSharedMdPool(155)).toBe(true);
    expect(clientUsesSharedMdPool(10)).toBe(false);
    expect(usesSharedMdPool({ client_id: 10, is_md_budget_based: false, md_budget_mode: null, uses_shared_md_pool: true })).toBe(true);
    expect(usesSharedMdPool({ client_id: 155, is_md_budget_based: true, md_budget_mode: "per_line" as never })).toBe(false);
    expect(usesSharedMdPool({ client_id: 10, is_md_budget_based: true, md_budget_mode: "shared" as never })).toBe(true);
    expect(usesSharedMdPool({ client_id: 10, is_md_budget_based: false, md_budget_mode: "shared" as never })).toBe(false);
    expect(usesSharedMdPool({ client_id: 155, is_md_budget_based: true, md_budget_mode: null })).toBe(true);
  });

  it("pula wspólna: MD i zużycie z budżetu zamówienia; brak zużycia = 0", () => {
    const m = orderGroupMetrics(
      group(1, { uses_shared_md_pool: true, md_budget_total: 40, md_budget_used: null } as Partial<OrderGroupRead>),
    );
    expect(m.totalMd).toBe(40);
    expect(m.budgetUsage).toBe(0);
    const used = orderGroupMetrics(
      group(1, { uses_shared_md_pool: true, md_budget_total: 40, md_budget_used: 30 } as Partial<OrderGroupRead>),
    );
    expect(used.budgetUsage).toBe(0.75);
  });

  it("zamówienie kosztowe: budżet zerowy nie dzieli przez zero, brak wykorzystania = 0", () => {
    expect(orderGroupMetrics(group(1, { is_cost_based: true, budget_amount: 0, lines: [] })).budgetUsage).toBeNull();
    expect(orderGroupMetrics(group(1, { is_cost_based: true, budget_amount: 1000, budget_used: null })).budgetUsage).toBe(0);
  });

  it("linie bez MD i bez stawek: wszystko null; korekta ręczna liczy się w zużyciu", () => {
    const empty = orderGroupMetrics(group(1, { lines: [line(1, "A", { md_total: null, rate_cost: null, rate_revenue: null })] }));
    expect(empty).toEqual({ totalMd: null, averageCost: null, averageRevenue: null, budgetUsage: null });
    const adjusted = orderGroupMetrics(
      group(1, { lines: [line(1, "A", { md_total: 10, md_remaining: null, md_manual_adjustment: null }), line(2, "B", { md_total: 10, md_remaining: 5, md_manual_adjustment: 1 })] }),
    );
    expect(adjusted.totalMd).toBe(20);
    expect(adjusted.budgetUsage).toBeCloseTo(16 / 20);
  });
});

describe("endingOrderWithoutSuccessor — reguła następcy", () => {
  it("horyzont nieliczbowy = 30 dni, ujemny = 0", () => {
    const orders = [order(1, { end_date: "2027-01-10" })];
    expect(endingOrderWithoutSuccessor(orders, Number.NaN, TODAY)?.id).toBe(1);
    expect(endingOrderWithoutSuccessor(orders, -5, TODAY)).toBeNull();
    expect(endingOrderWithoutSuccessor([order(1, { end_date: TODAY })], -5, TODAY)?.id).toBe(1);
  });

  it("szkic bez końca i bez stawki to nie następca; ze stawką — następca", () => {
    const ending = order(1, { end_date: "2026-12-31" });
    expect(
      endingOrderWithoutSuccessor([ending, order(2, { status: "draft", end_date: null, rate_client: null })], 30, TODAY)?.id,
    ).toBe(1);
    expect(
      endingOrderWithoutSuccessor([ending, order(2, { status: "draft", end_date: null, rate_client: 0 })], 30, TODAY)?.id,
    ).toBe(1);
    expect(
      endingOrderWithoutSuccessor([ending, order(2, { status: "draft", end_date: null, rate_client: 120 })], 30, TODAY),
    ).toBeNull();
  });

  it("zamknięte bez daty i zamknięte z końcem w przyszłości nie są następcą; wyczerpane też nie", () => {
    const ending = order(1, { end_date: "2026-12-31" });
    expect(endingOrderWithoutSuccessor([ending, order(2, { status: "completed", end_date: null })], 30, TODAY)?.id).toBe(1);
    expect(
      endingOrderWithoutSuccessor([ending, order(2, { status: "completed", end_date: "2027-03-31" })], 30, TODAY)?.id,
    ).toBe(1);
    expect(endingOrderWithoutSuccessor([ending, order(2, { status: "exhausted" as never, end_date: "2027-03-31" })], 30, TODAY)?.id).toBe(1);
    expect(endingOrderWithoutSuccessor([ending, order(2, { status: "active", end_date: null })], 30, TODAY)).toBeNull();
  });

  it("zawieszone też się kwalifikuje; wcześniejsze z następcą (zawieszonym) odpada", () => {
    const found = endingOrderWithoutSuccessor(
      [order(1, { end_date: "2027-01-05", status: "paused" }), order(2, { end_date: "2026-12-28" })],
      30,
      TODAY,
    );
    expect(found?.id).toBe(1);
    expect(
      endingOrderWithoutSuccessor(
        [order(1, { end_date: "2027-01-05" }), order(2, { end_date: "2026-12-28", status: "cancelled" })],
        30,
        TODAY,
      )?.id,
    ).toBe(1);
  });

  it("bez pola rate_client w wierszu (inny kształt) szkic bez końca liczy się jako następca", () => {
    const rows = [
      { id: 1, status: "active", start_date: "2026-01-01", end_date: "2026-12-31" },
      { id: 2, status: "draft", start_date: "2027-01-01", end_date: null },
    ] as Pick<ClientOrderRead, "id" | "status" | "start_date" | "end_date">[];
    expect(endingOrderWithoutSuccessor(rows, 30, TODAY)).toBeNull();
  });
});

describe("rodziny grup i koniec bez przedłużenia", () => {
  it("cykl poprzedników (uszkodzone dane) nie zapętla — każda grupa ma rodzinę", () => {
    const a = group(1, { predecessor_group_id: 2 });
    const b = group(2, { predecessor_group_id: 1 });
    const fam = buildOrderGroupFamilies([a, b]);
    expect([...fam.membersByGroupId.keys()].sort()).toEqual([1, 2]);
  });

  it("łańcuch przedłużeń zagnieżdżony w przyszłych zamówieniach to jedna rodzina", () => {
    const fam = buildOrderGroupFamilies([
      group(1, { future_orders: [group(2, { predecessor_group_id: 1, future_orders: [group(3, { predecessor_group_id: 2 })] })] }),
    ]);
    expect(fam.membersByGroupId.get(3)?.map((g) => g.id)).toEqual([1, 2, 3]);
  });

  it("przyszłe zamówienie bez daty końca przedłuża; anulowane nie", () => {
    const withFuture = group(1, {
      end_date: "2026-12-31",
      future_orders: [group(2, { predecessor_group_id: 1, status: "draft", end_date: null })],
    });
    expect(endingGroupWithoutSuccessor(withFuture, 30, TODAY)).toBeNull();
    const cancelled = group(1, {
      end_date: "2026-12-31",
      future_orders: [group(2, { predecessor_group_id: 1, status: "cancelled", end_date: "2027-06-30" })],
    });
    expect(endingGroupWithoutSuccessor(cancelled, 30, TODAY)?.id).toBe(1);
  });

  it("status poza listą (zakończone) się nie kwalifikuje; najwcześniejsze z drzewa", () => {
    expect(endingGroupWithoutSuccessor(group(1, { status: "completed" }), 30, TODAY)).toBeNull();
    const tree = group(1, {
      end_date: "2027-01-10",
      future_orders: [group(2, { end_date: "2026-12-25", status: "scheduled" })],
    });
    // 2 nie jest w rodzinie 1 (brak poprzednika), więc obie bez przedłużenia
    expect(endingGroupWithoutSuccessor(tree, 30, TODAY)?.id).toBe(2);
  });

  it("grupa spoza przekazanych rodzin korzysta z siebie samej", () => {
    const fam = buildOrderGroupFamilies([]);
    expect(endingGroupWithoutSuccessor(group(1), 30, TODAY, fam)?.id).toBe(1);
  });
});

describe("filterAndSortOrderGroups — filtry i sortowanie", () => {
  it("zakres startu i końca, grupa bez dat odpada przy ustawionym zakresie", () => {
    const groups = [
      group(1, { start_date: "2026-01-01", end_date: "2026-12-31" }),
      group(2, { start_date: "2027-01-01", end_date: "2027-12-31" }),
      group(3, { start_date: null as unknown as string, end_date: null }),
    ];
    expect(filterAndSortOrderGroups(groups, "", filters({ startFrom: "2026-12-31" }), TODAY).map((g) => g.id)).toEqual([2]);
    expect(filterAndSortOrderGroups(groups, "", filters({ startTo: "2026-06-30" }), TODAY).map((g) => g.id)).toEqual([1]);
    expect(filterAndSortOrderGroups(groups, "", filters({ endFrom: "2027-01-01" }), TODAY).map((g) => g.id)).toEqual([2]);
    expect(filterAndSortOrderGroups(groups, "", filters({ endTo: "2026-12-31" }), TODAY).map((g) => g.id)).toEqual([1]);
    expect(filterAndSortOrderGroups(groups, "nikt", filters(), TODAY)).toEqual([]);
  });

  it("domyślnie najnowsze utworzone najpierw, przy tym samym czasie — wyższe id", () => {
    const groups = [
      group(1, { created_at: "2026-08-01T10:00:00Z" }),
      group(2, { created_at: "2026-09-01T10:00:00Z" }),
      group(3, { created_at: "2026-09-01T10:00:00Z" }),
    ];
    expect(filterAndSortOrderGroups(groups, "", filters(), TODAY).map((g) => g.id)).toEqual([3, 2, 1]);
  });

  it("blisko budżetu: od 80 %, grupa bez zużycia odpada", () => {
    const groups = [
      group(1, { lines: [line(1, "A", { md_total: 10, md_remaining: 2 })] }),
      group(2, { lines: [line(2, "B", { md_total: 10, md_remaining: 3 })] }),
      group(3, { lines: [line(3, "C", { md_total: null })] }),
    ];
    expect(filterAndSortOrderGroups(groups, "", filters({ nearBudget: true }), TODAY).map((g) => g.id)).toEqual([1]);
  });

  it("kończące się: tylko bez przedłużenia", () => {
    const groups = [group(1, { end_date: "2026-12-31" }), group(2, { end_date: "2027-06-30" })];
    expect(filterAndSortOrderGroups(groups, "", filters({ endingSoon: true }), TODAY).map((g) => g.id)).toEqual([1]);
  });

  it("sortowanie po MD, koszcie i przychodzie w obu kierunkach; puste na końcu; remis po utworzeniu", () => {
    const groups = [
      group(1, { lines: [line(1, "A", { md_total: 10, rate_cost: 50, rate_revenue: 300 })] }),
      group(2, { lines: [line(2, "B", { md_total: 30, rate_cost: 90, rate_revenue: 100 })] }),
      group(3, { lines: [line(3, "C", { md_total: null, rate_cost: null, rate_revenue: null })] }),
      group(4, { lines: [line(4, "D", { md_total: 10, rate_cost: 50, rate_revenue: 300 })] }),
    ];
    const by = (sort: OrderSort) => filterAndSortOrderGroups(groups, "", filters({ sort }), TODAY).map((g) => g.id);
    expect(by("md_asc")).toEqual([4, 1, 2, 3]);
    expect(by("md_desc")).toEqual([2, 4, 1, 3]);
    expect(by("cost_asc")).toEqual([4, 1, 2, 3]);
    expect(by("cost_desc")).toEqual([2, 4, 1, 3]);
    expect(by("revenue_asc")).toEqual([2, 4, 1, 3]);
    expect(by("revenue_desc")).toEqual([4, 1, 2, 3]);
  });

  it("sortowanie po osobie: interpunkcja ignorowana, bez nazwiska na końcu w obu kierunkach", () => {
    const groups = [
      group(1, { lines: [line(1, "{ } Zenon Testowy")] }),
      group(2, { lines: [line(2, "Adam Testowy"), line(22, "Bartek Testowy")] }),
      group(3, { lines: [line(3, "—")] }),
      group(4, { lines: [line(4, "")] }),
    ];
    const by = (sort: OrderSort) => filterAndSortOrderGroups(groups, "", filters({ sort }), TODAY).map((g) => g.id);
    expect(by("consultant_asc")).toEqual([2, 1, 4, 3]);
    expect(by("consultant_desc")).toEqual([1, 2, 4, 3]);
  });
});

describe("zamówienia kontraktora", () => {
  it("orderGroupContractIds obejmuje przyszłe zamówienia", () => {
    const ids = orderGroupContractIds([group(1, { future_orders: [group(2)] })]);
    expect([...ids].sort()).toEqual([1, 2]);
  });

  it("primaryOrder: tylko przyszłe — najbliższe; zamówienie bez startu liczy się jako rozpoczęte", () => {
    const c = contractor(1, "Jan Testowy", {
      orders: [order(1, { start_date: "2027-03-01" }), order(2, { start_date: "2027-01-01" }), order(3, { status: "cancelled", start_date: "2026-01-01" })],
    });
    expect(primaryOrder(c, TODAY)?.id).toBe(2);
    expect(primaryOrder(contractor(1, "X", { orders: [order(4, { start_date: null as unknown as string })] }), TODAY)?.id).toBe(4);
    expect(primaryOrder(contractor(1, "X"), TODAY)).toBeNull();
  });

  it("representativeOrder: same anulowane — najnowszy start, potem utworzenie i id", () => {
    const c = contractor(1, "Jan Testowy", {
      orders: [
        order(1, { status: "cancelled", start_date: "2026-01-01" }),
        order(2, { status: "cancelled", start_date: "2026-01-01", created_at: "2026-04-09T10:00:00Z" }),
        order(3, { status: "cancelled", start_date: "2026-01-01", created_at: "2026-04-09T10:00:00Z" }),
      ],
    });
    expect(representativeOrder(c, TODAY)?.id).toBe(3);
    expect(representativeOrder(contractor(1, "X"), TODAY)).toBeNull();
    expect(contractorOrderType(contractor(1, "X"), "md", TODAY)).toBe("md");
  });

  it("wartości z serwera mają pierwszeństwo przy końcu bez następcy", () => {
    expect(endingWithoutSuccessorOrderId(contractor(1, "X", { ending_without_successor_order_id: null } as Partial<ContractWithOrdersRead>), TODAY)).toBeNull();
    expect(endingWithoutSuccessorOrderId(contractor(1, "X", { ending_without_successor_order_id: 9 } as Partial<ContractWithOrdersRead>), TODAY)).toBe(9);
    const withDays = (d: number | null) =>
      contractor(1, "X", { next_ending_without_successor_days: d } as Partial<ContractWithOrdersRead>);
    expect(endsWithoutSuccessorWithin(withDays(null), 30, TODAY)).toBe(false);
    expect(endsWithoutSuccessorWithin(withDays(30), 30, TODAY)).toBe(true);
    expect(endsWithoutSuccessorWithin(withDays(31), 30, TODAY)).toBe(false);
    expect(endsWithoutSuccessorWithin(contractor(1, "X", { orders: [order(1)] }), 30, TODAY)).toBe(true);
  });
});

describe("pigułki", () => {
  it("kontraktor: wszystkie, aktywny-szkic karty, szkic umowy z aktywnym zamówieniem, zakończony jeszcze nie zamknięty", () => {
    expect(contractorMatchesPill(contractor(1, "X"), "all", TODAY)).toBe(true);
    expect(contractorMatchesPill(contractor(1, "X", { draft_card: true } as Partial<ContractWithOrdersRead>), "active", TODAY)).toBe(false);
    expect(
      contractorMatchesPill(contractor(1, "X", { contract_status: "ready_for_signature", orders: [order(1)] }), "active", TODAY),
    ).toBe(true);
    expect(contractorMatchesPill(contractor(1, "X", { contract_status: "draft" }), "active", TODAY)).toBe(false);
    expect(
      contractorMatchesPill(contractor(1, "X", { contract_status: "ended", contract_end_date: "2026-12-31" }), "active", TODAY),
    ).toBe(true);
    expect(contractorMatchesPill(contractor(1, "X", { contract_status: "ending" }), "active", TODAY)).toBe(true);
  });

  it("kontraktor: szkic, anulowane, wyczerpane (nie dotyczy)", () => {
    expect(contractorMatchesPill(contractor(1, "X", { contract_status: "draft" }), "draft", TODAY)).toBe(true);
    expect(
      contractorMatchesPill(contractor(1, "X", { contract_status: "draft", orders: [order(1)] }), "draft", TODAY),
    ).toBe(false);
    expect(contractorMatchesPill(contractor(1, "X", { orders: [order(1, { status: "draft" })] }), "draft", TODAY)).toBe(true);
    expect(
      contractorMatchesPill(contractor(1, "X", { orders: [order(1, { status: "cancelled" }), order(2, { status: "paused" })] }), "cancelled", TODAY),
    ).toBe(false);
    expect(contractorMatchesPill(contractor(1, "X", { orders: [order(1, { status: "cancelled" })] }), "cancelled", TODAY)).toBe(true);
    expect(contractorMatchesPill(contractor(1, "X"), "exhausted", TODAY)).toBe(false);
    expect(contractorMatchesPill(contractor(1, "X", { orders: [order(1)] }), "ending_30d", TODAY)).toBe(true);
  });

  it("grupa: każdy status i nieznana pigułka", () => {
    expect(orderGroupMatchesPill(group(1), "all", TODAY)).toBe(true);
    expect(orderGroupMatchesPill(group(1, { status: "exhausted" }), "exhausted", TODAY)).toBe(true);
    expect(orderGroupMatchesPill(group(1, { status: "cancelled" }), "cancelled", TODAY)).toBe(true);
    expect(orderGroupMatchesPill(group(1, { status: "completed" }), "completed", TODAY)).toBe(true);
    expect(orderGroupMatchesPill(group(1, { status: "draft" }), "draft", TODAY)).toBe(true);
    expect(orderGroupMatchesPill(group(1), "ending_30d", TODAY)).toBe(true);
    expect(orderGroupMatchesPill(group(1), "inna" as never, TODAY)).toBe(false);
  });
});

describe("filterAndSortContractors", () => {
  const people = [
    contractor(1, "Zenon Testowy", { rate_candidate: 50, orders: [order(1, { start_date: "2026-01-01", end_date: "2026-12-31", rate_client: 300 })] }),
    contractor(2, "Adam Testowy", { rate_candidate: null as unknown as number, orders: [order(2, { start_date: "2026-06-01", end_date: "2027-06-30", rate_client: 100 })] }),
    contractor(3, "", { rate_candidate: 90, orders: [] }),
  ];

  it("zapytanie odfiltrowuje kontraktorów", () => {
    expect(filterAndSortContractors(people, "zenon", filters(), TODAY).map((c) => c.contract_id)).toEqual([1]);
  });

  it("zakresy dat po zamówieniu reprezentatywnym; kontraktor bez zamówień odpada przy zakresie", () => {
    const by = (f: Partial<OrderListFilters>) => filterAndSortContractors(people, "", filters(f), TODAY).map((c) => c.contract_id);
    expect(by({ startFrom: "2026-03-01" })).toEqual([2]);
    expect(by({ startTo: "2026-03-01" })).toEqual([1]);
    expect(by({ endFrom: "2027-01-01" })).toEqual([2]);
    expect(by({ endTo: "2026-12-31" })).toEqual([1]);
    expect(by({ endingSoon: true })).toEqual([1]);
  });

  it("sortowanie: utworzenie, osoba (pusta na końcu), MD (remis → id), koszt, przychód", () => {
    const by = (sort: OrderSort) => filterAndSortContractors(people, "", filters({ sort }), TODAY).map((c) => c.contract_id);
    expect(by("created_desc")).toEqual([2, 1, 3]);
    expect(by("consultant_asc")).toEqual([2, 1, 3]);
    expect(by("consultant_desc")).toEqual([1, 2, 3]);
    expect(by("md_asc")).toEqual([3, 2, 1]);
    expect(by("cost_asc")).toEqual([1, 3, 2]);
    expect(by("cost_desc")).toEqual([3, 1, 2]);
    expect(by("revenue_desc")).toEqual([1, 2, 3]);
    expect(by("revenue_asc")).toEqual([2, 1, 3]);
  });
});

describe("sortUnifiedOrderItems", () => {
  const items: UnifiedOrderListItem[] = [
    { kind: "group", group: group(5, { lines: [line(5, "Celina Testowa", { md_total: 20, rate_cost: 70, rate_revenue: 200 })] }) },
    {
      kind: "contractor",
      contractor: contractor(6, "Adam Testowy", {
        rate_candidate: 80,
        orders: [order(6, { md_quantity: "15" as unknown as number, rate_client: 250, created_at: "2026-09-01T10:00:00Z" })],
      }),
    },
    { kind: "contractor", contractor: contractor(7, "Bartek Testowy", { rate_candidate: null as unknown as number, orders: [] }) },
  ];
  const ids = (sort: OrderSort) =>
    sortUnifiedOrderItems(items, sort, TODAY).map((i) => (i.kind === "group" ? `g${i.group.id}` : `c${i.contractor.contract_id}`));

  it("utworzenie: najnowsze najpierw, kontraktor bez zamówień na końcu", () => {
    expect(ids("created_desc")).toEqual(["c6", "g5", "c7"]);
  });
  it("osoba rosnąco i malejąco", () => {
    expect(ids("consultant_asc")).toEqual(["c6", "c7", "g5"]);
    expect(ids("consultant_desc")).toEqual(["g5", "c7", "c6"]);
  });
  it("MD z tekstu z API, koszt, przychód; puste na końcu", () => {
    expect(ids("md_desc")).toEqual(["g5", "c6", "c7"]);
    expect(ids("md_asc")).toEqual(["c6", "g5", "c7"]);
    expect(ids("cost_asc")).toEqual(["g5", "c6", "c7"]);
    expect(ids("revenue_desc")).toEqual(["c6", "g5", "c7"]);
  });
  it("MD nieliczbowe i puste traktowane jak brak", () => {
    const odd: UnifiedOrderListItem[] = [
      { kind: "contractor", contractor: contractor(8, "A", { orders: [order(8, { md_quantity: "abc" as unknown as number })] }) },
      { kind: "contractor", contractor: contractor(9, "B", { orders: [order(9, { md_quantity: "" as unknown as number })] }) },
      { kind: "contractor", contractor: contractor(10, "C", { orders: [order(10, { md_quantity: 3 })] }) },
    ];
    expect(sortUnifiedOrderItems(odd, "md_desc", TODAY).map((i) => (i.kind === "contractor" ? i.contractor.contract_id : 0))[0]).toBe(10);
  });
});

describe("visibleLegacyOrderIds / resolveOrderFocus", () => {
  it("trafienie po tytule, gdy osoba nie pasuje; z kilku bieżących — najpóźniej rozpoczęte", () => {
    const c = contractor(1, "Jan Testowy", {
      orders: [
        order(1, { title: "Projekt Zielony", start_date: "2026-01-01" }),
        order(2, { title: "Projekt Zielony 2", start_date: "2026-06-01" }),
        order(3, { title: "Inny", start_date: "2026-09-01" }),
      ],
    });
    expect(visibleLegacyOrderIds([c], "zielony", TODAY)).toEqual([2]);
    expect(visibleLegacyOrderIds([c], "", TODAY)).toEqual([3]);
    expect(visibleLegacyOrderIds([c], "brak", TODAY)).toEqual([]);
  });

  it("fokus: grupa po id (także przyszła), linia w przyszłym zamówieniu, szkic kontraktora, brak", () => {
    const groups = [group(1, { future_orders: [group(2, { lines: [line(22, "A")] })] })];
    const people = [contractor(5, "X", { orders: [order(50, { status: "draft" })] })];
    expect(resolveOrderFocus(groups, people, { groupId: 2 })).toEqual({ kind: "group", groupId: 2 });
    expect(resolveOrderFocus(groups, people, { groupId: 99, orderId: 22 })).toEqual({ kind: "group", groupId: 2, lineId: 22 });
    expect(resolveOrderFocus(groups, people, { orderId: 50 })).toEqual({
      kind: "contractor",
      contractId: 5,
      orderId: 50,
      isDraft: true,
    });
    expect(resolveOrderFocus(groups, people, { orderId: 404 })).toBeNull();
    expect(resolveOrderFocus(groups, people, { orderId: null })).toBeNull();
    expect(resolveOrderFocus(groups, people, {})).toBeNull();
  });
});
