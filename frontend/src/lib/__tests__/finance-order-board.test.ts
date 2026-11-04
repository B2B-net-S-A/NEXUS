import { describe, expect, it } from "vitest";

import type {
  OrderChangeItem,
  OrderChangesResponse,
  OrderExitItem,
} from "@/lib/api/finance";
import {
  boardItems,
  buildCards,
  cardTitle,
  clientTiles,
  doneInMonthLabel,
  splitCards,
  statusCounts,
  withCheck,
} from "@/lib/finance-order-board";

const DONE = { by_name: "Anna Finanse", at: "2026-09-18T09:14:00Z" };

function change(overrides: Partial<OrderChangeItem>): OrderChangeItem {
  return {
    order_id: 1,
    order_group_id: null,
    contract_id: 1,
    client_id: 10,
    client_name: "Nordea Bank Abp",
    consultant_name: "Axel Gocan",
    order_number: "286139",
    item_key: "chg:ev:1",
    order_start: "2026-10-01",
    order_end: "2026-12-31",
    pdf: null,
    done: null,
    entered_at: "2026-09-21T10:41:00Z",
    entered_by: "Anna Delivery",
    kind: "end_date",
    event_id: 1,
    occurred_at: "2026-09-21T10:41:00Z",
    effective_date: "2026-09-21",
    old_amount: null,
    new_amount: null,
    old_unit: null,
    new_unit: null,
    currency: "PLN",
    old_date: "2026-11-30",
    new_date: "2026-12-31",
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
    ...overrides,
  };
}

function data(
  changes: OrderChangeItem[],
  extra: Partial<OrderChangesResponse> = {},
) {
  return {
    period: { year: 2026, month: 9, label: "Wrzesień 2026" },
    counts: {
      changes: changes.length,
      entries: 0,
      exits: 0,
      ending: 0,
      gaps: 0,
    },
    changes,
    entries: [],
    exits: [],
    ending_orders: [],
    gaps: [],
    changes_tracked_since: null,
    gaps_tracked_since: "2026-08-01",
    open_gaps_total: 0,
    ...extra,
  } satisfies OrderChangesResponse;
}

describe("karta zamówienia", () => {
  it("ma nagłówek w formacie z „Zamówień PDF”", () => {
    expect(
      cardTitle({
        orderNumber: "286139",
        orderStart: "2026-10-01",
        orderEnd: "2026-12-31",
        consultantName: "Axel Gocan",
      }),
    ).toBe("Zam. 286139 · 01.10.2026 – 31.12.2026 · Axel Gocan");
    expect(
      cardTitle({
        orderNumber: "1",
        orderStart: "2026-10-01",
        orderEnd: null,
        consultantName: "X",
      }),
    ).toBe("Zam. 1 · 01.10.2026 – bezterminowo · X");
  });

  it("stara strona zmiany stawki jest w swojej walucie", () => {
    const [item] = boardItems(
      data([
        change({
          kind: "rate_revenue",
          old_amount: 1000,
          new_amount: 1000,
          old_unit: "daily",
          new_unit: "daily",
          currency: "EUR",
          old_currency: "PLN",
          old_date: null,
          new_date: null,
        }),
      ]),
      "changes",
    );
    expect(item.before).toBe("1000,00 zł/dzień");
    expect(item.after).toBe("1000,00 EUR/dzień");
  });

  it("grupuje zmiany jednego zamówienia i zbiera etykiety typów", () => {
    const items = boardItems(
      data([
        change({}),
        change({
          item_key: "chg:ev:2",
          event_id: 2,
          kind: "rate_revenue",
          old_amount: 1000,
          new_amount: 1080,
          old_unit: "daily",
          new_unit: "daily",
          old_date: null,
          new_date: null,
        }),
        change({
          item_key: "chg:ev:3",
          event_id: 3,
          order_id: 2,
          consultant_name: "Marta",
        }),
      ]),
      "changes",
    );
    const cards = buildCards(items, "all");
    expect(cards).toHaveLength(2);
    const gocan = cards.find((card) => card.consultantName === "Axel Gocan")!;
    expect(gocan.items).toHaveLength(2);
    expect(gocan.labels).toEqual(["extension", "rate_revenue"]);
    const rate = gocan.items.find((item) => item.label === "rate_revenue")!;
    expect(rate.before).toBe("1000,00 zł/dzień");
    expect(rate.after).toBe("1080,00 zł/dzień");
    expect(rate.enteredBy).toBe("Anna Delivery");
  });

  it("skrócenie daty końca to „Zmiana okresu”, wydłużenie — „Przedłużenie”", () => {
    const [shorter] = boardItems(
      data([change({ old_date: "2026-12-31", new_date: "2026-11-30" })]),
      "changes",
    );
    expect(shorter.label).toBe("period");
    const [open] = boardItems(
      data([change({ old_date: "2026-12-31", new_date: null })]),
      "changes",
    );
    expect(open.label).toBe("extension");
    expect(open.after).toBe("bezterminowo");
  });

  it("automat maila podpisuje się adresem skrzynki", () => {
    const [item] = boardItems(
      data([
        change({
          entered_by: null,
          entered_automatically: true,
          from_order_mail: true,
        }),
      ]),
      "changes",
    );
    expect(item.enteredBy).toBe(
      "dodane automatycznie (zamowienia@b2bnetwork.pl)",
    );
  });
});

describe("zmieniono ponownie", () => {
  it("nowa zmiana tego samego pola chowa odhaczoną i oznacza kartę", () => {
    const items = boardItems(
      data([
        change({
          item_key: "chg:ev:1",
          event_id: 1,
          entered_at: "2026-09-14T10:00:00Z",
          old_date: "2026-09-14",
          new_date: "2026-11-30",
          done: DONE,
        }),
        change({
          item_key: "chg:ev:2",
          event_id: 2,
          entered_at: "2026-09-21T10:41:00Z",
          old_date: "2026-11-30",
          new_date: "2026-12-31",
        }),
      ]),
      "changes",
    );
    const [card] = buildCards(items, "todo");
    expect(card.changedAgain).toBe(true);
    expect(card.visible.map((entry) => entry.item.key)).toEqual(["chg:ev:2"]);
    expect(card.visible[0].earlier[0].summary).toBe(
      "Data końca: 14.09.2026 → 30.11.2026",
    );
    // Historia zostaje: w filtrze „Zrobione” odhaczona zmiana jest widoczna.
    const [doneCard] = buildCards(items, "done");
    expect(doneCard.visible.map((entry) => entry.item.key)).toEqual([
      "chg:ev:1",
    ]);
  });

  it("odhaczenie, którego pozycji już nie ma, też oznacza kartę", () => {
    const ending: OrderExitItem = {
      order_id: 5,
      order_group_id: null,
      contract_id: 5,
      client_id: 10,
      client_name: "Nordea",
      consultant_name: "Ewa",
      order_number: "77",
      item_key: "ending:5:2026-09-20",
      end_date: "2026-09-20",
      start_date: "2026-01-01",
      rate_cost: null,
      rate_revenue: null,
      rate_unit: null,
      currency: null,
      order_type: "periodic",
      verdict: "ending_pending",
      verdict_label: "Kończy się 20.09.2026",
      intent: null,
    };
    const response = data([], {
      ending_orders: [ending],
      superseded: [
        {
          item_key: "ending:5:2026-09-10",
          tab: "ending",
          order_id: 5,
          order_group_id: null,
          summary: "Koniec zamówienia 10.09.2026",
          done: DONE,
        },
      ],
    });
    const [card] = buildCards(
      boardItems(response, "ending"),
      "todo",
      response.superseded,
      "ending",
    );
    expect(card.changedAgain).toBe(true);
    expect(card.previous[0].summary).toBe("Koniec zamówienia 10.09.2026");
  });
});

describe("liczniki i klienci", () => {
  const response = data([
    change({ item_key: "a", client_id: 1, client_name: "Beta", done: DONE }),
    change({ item_key: "b", client_id: 2, client_name: "Alfa", order_id: 3 }),
    change({ item_key: "c", client_id: 2, client_name: "Alfa", order_id: 4 }),
    change({ item_key: "d", client_id: 3, client_name: "Gamma", order_id: 5 }),
  ]);
  const items = boardItems(response, "changes");

  it("liczy do zrobienia, zrobione i wszystkie", () => {
    expect(statusCounts(items)).toEqual({ todo: 3, done: 1, all: 4 });
  });

  it("kafelki: najwięcej do zrobienia na górze, zrobieni na dole", () => {
    expect(
      clientTiles(items).map((tile) => [tile.name, tile.todo, tile.total]),
    ).toEqual([
      ["Alfa", 2, 2],
      ["Gamma", 1, 1],
      ["Beta", 0, 1],
    ]);
  });

  it("karta w całości zrobiona trafia do sekcji „Zrobione”", () => {
    const cards = buildCards(items, "todo");
    const { open, finished } = splitCards(cards, "todo");
    expect(open).toHaveLength(3);
    expect(finished.map((card) => card.consultantName)).toEqual(["Axel Gocan"]);
  });

  it("odhaczenie zmienia dane od razu (bez ponownego odczytu)", () => {
    const next = withCheck(response, "b", DONE);
    expect(statusCounts(boardItems(next, "changes"))).toEqual({
      todo: 2,
      done: 2,
      all: 4,
    });
    expect(withCheck(next, "a", null).changes[0].done).toBeNull();
  });

  it("miesiąc w pasku postępu odmienia się", () => {
    expect(doneInMonthLabel(9)).toBe("Zrobione we wrześniu");
    expect(doneInMonthLabel(10)).toBe("Zrobione w październiku");
  });
});
