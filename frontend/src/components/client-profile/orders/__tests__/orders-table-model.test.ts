import { describe, expect, it } from "vitest";

import type { ContractWithOrdersRead } from "@/lib/api/dlPortal";
import type { OrderGroupRead, OrderLineRead } from "@/lib/api/orderGroups";

import {
  buildSectionRows,
  buildSectionTiles,
  findGroup,
  findLine,
  groupRoster,
  perPersonMdTotals,
  selectableKeys,
  selectionFromKey,
  selectionKey,
  topLevelGroupOf,
  type OrdersTableSection,
} from "../orders-table-model";

function line(overrides: Partial<OrderLineRead> = {}): OrderLineRead {
  return {
    id: 1,
    group_id: 30,
    contract_id: 300,
    candidate_id: 5,
    consultant_name: "Jan Kowalski",
    job_id: null,
    job_title: null,
    status: "active",
    is_active: true,
    start_date: "2026-05-01",
    end_date: null,
    rate_cost: 800,
    rate_revenue: 1000,
    input_value: 60,
    input_mode: "md",
    md_total: 60,
    md_remaining: 20,
    md_manual_adjustment: 0,
    md_used: 40,
    predecessor_order_id: null,
    predecessor_consultant_name: null,
    invoiced_total: null,
    unsettled_total: null,
    missing_consumption_month: null,
    md_optional_total: null,
    md_base_used: null,
    md_optional_used: null,
    replaced_by_order_id: null,
    replaced_by_consultant_name: null,
    contract_type: "b2b",
    agreement_termination_mode: null,
    agreement_last_day: null,
    ...overrides,
  } as OrderLineRead;
}

function group(id: number, lines: OrderLineRead[], overrides: Partial<OrderGroupRead> = {}): OrderGroupRead {
  return {
    id,
    client_id: 18,
    order_number: `45000${id}`,
    start_date: "2026-03-01",
    end_date: null,
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
    lines,
    active_consultants: lines.filter((item) => item.is_active).length,
    event_count: 0,
    future_orders: [],
    ...overrides,
  } as OrderGroupRead;
}

const ENDED_PENDING = line({
  id: 3,
  consultant_name: "Paweł Pulowy",
  status: "completed",
  is_active: false,
  end_date: "2026-08-31",
  cooperation_ended_on: "2026-08-31",
  offboarding_case: {
    id: 71,
    status: "pending",
    uses_shared_md_pool: false,
    remaining_md_snapshot: 3.7,
  } as never,
});
const ENDED_DONE = line({
  id: 4,
  consultant_name: "Maria Historyczna",
  status: "completed",
  is_active: false,
  end_date: "2026-07-31",
  cooperation_ended_on: "2026-07-31",
  history_kept_at: "2026-08-02T09:00:00Z",
});

describe("groupRoster", () => {
  it("dzieli obsadę na bieżącą i zakończoną, szkic i zaplanowane zastępstwo są bieżące", () => {
    const draft = line({ id: 7, consultant_name: "Ada Szkic", status: "draft", is_active: false });
    const scheduled = line({ id: 8, consultant_name: "Bartek Wejdzie", is_active: false, takeover_scheduled: true });
    const roster = groupRoster(group(30, [line(), draft, scheduled, ENDED_PENDING, ENDED_DONE]));
    expect(roster.current.map((l) => l.id).sort()).toEqual([1, 7, 8]);
    expect(roster.ended.map((l) => l.id)).toEqual([3, 4]);
    expect(roster.pendingDecisions).toBe(1);
  });
});

describe("perPersonMdTotals", () => {
  it("sumuje budżet MD bieżącej obsady", () => {
    expect(perPersonMdTotals([line({ md_total: 60, md_remaining: 20 }), line({ id: 2, md_total: 40, md_remaining: 5 })])).toEqual({
      remaining: 25,
      total: 100,
    });
  });
  it("zwraca null, gdy nikt nie ma budżetu MD (kosztowe, wspólna pula)", () => {
    expect(perPersonMdTotals([line({ md_total: null, md_remaining: null })])).toBeNull();
  });
});

describe("buildSectionRows", () => {
  const future = group(31, [line({ id: 9, consultant_name: "Ewa Przyszła" })], { order_number: "4500031", start_date: "2027-01-01" });
  const withEnded = group(30, [line(), ENDED_DONE], { future_orders: [future] });

  it("zamówienie, obsada, zwinięta sekcja zakończonych i przyszłe zamówienie", () => {
    const rows = buildSectionRows([{ kind: "group", group: withEnded }], {
      expandedEnded: new Set(),
      collapsedEnded: new Set(),
    });
    expect(rows.map((row) => row.kind)).toEqual(["group", "line", "ended-toggle", "future"]);
    expect(rows[2]).toMatchObject({ kind: "ended-toggle", count: 1, open: false });
    expect(rows[3].key).toBe("g:31");
  });

  it("sekcja zakończonych rozwija się sama, gdy czeka decyzja — chyba że ktoś ją zwinął", () => {
    const pending = group(40, [line({ id: 11 }), ENDED_PENDING]);
    const open = buildSectionRows([{ kind: "group", group: pending }], {
      expandedEnded: new Set(),
      collapsedEnded: new Set(),
    });
    expect(open.map((row) => row.key)).toEqual(["g:40", "l:11", "e:40", "l:3"]);
    const collapsed = buildSectionRows([{ kind: "group", group: pending }], {
      expandedEnded: new Set(),
      collapsedEnded: new Set([40]),
    });
    expect(collapsed.map((row) => row.key)).toEqual(["g:40", "l:11", "e:40"]);
  });

  it("wyszukane nazwisko wśród zakończonych rozwija sekcję", () => {
    const rows = buildSectionRows([{ kind: "group", group: withEnded }], {
      expandedEnded: new Set(),
      collapsedEnded: new Set(),
      matchesSearch: (name) => name.includes("Maria"),
    });
    expect(rows.some((row) => row.key === "l:4")).toBe(true);
  });

  it("kontraktor okresowy to jeden wiersz", () => {
    const contractor = { contract_id: 466 } as ContractWithOrdersRead;
    expect(buildSectionRows([{ kind: "contractor", contractor }], { expandedEnded: new Set(), collapsedEnded: new Set() })).toEqual([
      { kind: "contractor", key: "c:466", contractor },
    ]);
  });
});

describe("buildSectionTiles (ticket 11)", () => {
  it("każde zamówienie to kafelek z obsadą, „Zakończonymi” i przedłużeniem; kontraktor osobno", () => {
    const future = group(31, [line({ id: 9 })], { order_number: "4500031" });
    const first = group(30, [line(), ENDED_DONE], { future_orders: [future] });
    const second = group(40, [line({ id: 11 })]);
    const contractor = { contract_id: 466 } as ContractWithOrdersRead;
    const rows = buildSectionRows(
      [
        { kind: "group", group: first },
        { kind: "contractor", contractor },
        { kind: "group", group: second },
      ],
      { expandedEnded: new Set(), collapsedEnded: new Set() },
    );
    const tiles = buildSectionTiles(rows);
    expect(tiles.map((tile) => tile.key)).toEqual(["g:30", "c:466", "g:40"]);
    expect(tiles[0].header?.group.id).toBe(30);
    expect(tiles[0].rows.map((row) => row.key)).toEqual(["l:1", "e:30", "g:31"]);
    expect(tiles[1].header).toBeNull();
    expect(tiles[1].rows.map((row) => row.key)).toEqual(["c:466"]);
    expect(tiles[2].rows.map((row) => row.key)).toEqual(["l:11"]);
    // Nic nie ginie: wiersze kafelków to dokładnie wiersze sekcji.
    expect(tiles.flatMap((tile) => [tile.header, ...tile.rows]).filter(Boolean)).toHaveLength(rows.length);
  });
});

describe("zaznaczenie", () => {
  const future = group(31, [line({ id: 9 })]);
  const root = group(30, [line(), ENDED_PENDING], { future_orders: [future] });
  const sections: OrdersTableSection[] = [
    {
      type: "md",
      itemCount: 1,
      rows: buildSectionRows([{ kind: "group", group: root }], { expandedEnded: new Set(), collapsedEnded: new Set() }),
    },
  ];

  it("klucze do nawigacji strzałkami pomijają wiersz zwijania", () => {
    expect(selectableKeys(sections)).toEqual(["g:30", "l:1", "l:3", "g:31"]);
  });

  it("klucz wiersza zamienia się w zaznaczenie i z powrotem", () => {
    expect(selectionFromKey("l:3", sections)).toEqual({ kind: "line", groupId: 30, lineId: 3 });
    expect(selectionFromKey("g:31", sections)).toEqual({ kind: "group", groupId: 31 });
    expect(selectionFromKey("x:1", sections)).toBeNull();
    expect(selectionKey({ kind: "contractor", contractId: 5 })).toBe("c:5");
  });

  it("znajduje zamówienie i linię także w przedłużeniu", () => {
    expect(findGroup([root], 31)?.id).toBe(31);
    expect(findLine([root], 9)?.group.id).toBe(31);
    expect(topLevelGroupOf([root], 31)?.id).toBe(30);
    expect(findLine([root], 999)).toBeNull();
  });
});
