import { describe, expect, it } from "vitest";

import type {
  OrderChangeItem,
  OrderChangesResponse,
  OrderEntryItem,
  OrderExitItem,
  OrderGapItem,
} from "@/lib/api/finance";
import {
  boardItems,
  buildCards,
  cardItemsAllTabs,
  cardTitle,
  clientKey,
  clientTiles,
  doneInMonthLabel,
  doneLabel,
  itemSummary,
  ORDER_MAIL_ADDRESS,
  splitCards,
  withInvoiceLines,
  type BoardItem,
} from "@/lib/finance-order-board";

const DONE = { by_name: "Anna Przykładowa", at: "2026-12-31T11:00:00Z" };

const ref = {
  order_id: 1 as number | null,
  order_group_id: null as number | null,
  contract_id: 1,
  client_id: 10 as number | null,
  client_name: "Firma Testowa",
  consultant_name: "Jan Testowy",
  order_number: "T-1",
};

function change(overrides: Partial<OrderChangeItem>): OrderChangeItem {
  return {
    ...ref,
    item_key: "chg:1",
    kind: "rate_cost",
    event_id: null,
    occurred_at: null,
    effective_date: null,
    old_amount: 100,
    new_amount: 120,
    old_unit: "hourly",
    new_unit: "hourly",
    currency: "PLN",
    old_date: null,
    new_date: null,
    is_whole_order: false,
    source: "user",
    author_name: null,
    rate_cost: 800,
    rate_revenue: 1000,
    rate_unit: "md",
    other_client_names: [],
    previous_order_number: null,
    previous_end_date: null,
    previous_client_name: null,
    start_date: null,
    engagement_since: null,
    ...overrides,
  };
}

function entry(overrides: Partial<OrderEntryItem> = {}): OrderEntryItem {
  return {
    ...ref,
    item_key: "ent:1",
    start_date: "2027-01-01",
    end_date: null,
    rate_cost: 800,
    rate_revenue: 1000,
    rate_unit: "md",
    currency: "PLN",
    order_type: "md",
    status: "active",
    ...overrides,
  };
}

function exit(overrides: Partial<OrderExitItem> = {}): OrderExitItem {
  return {
    ...ref,
    item_key: "ex:1",
    end_date: "2026-12-31",
    start_date: null,
    rate_cost: null,
    rate_revenue: null,
    rate_unit: null,
    currency: null,
    order_type: "periodic",
    verdict: "ended_intent",
    verdict_label: "Zakończenie współpracy",
    intent: null,
    ...overrides,
  } as OrderExitItem;
}

function gap(overrides: Partial<OrderGapItem> = {}): OrderGapItem {
  return {
    ...ref,
    item_key: "gap:1",
    gap_id: 1,
    ended_on: "2026-12-31",
    detected_on: "2027-01-01",
    status: "open",
    resolved_order_number: null,
    resolved_at: null,
    delay_days: null,
    ...overrides,
  };
}

function data(extra: Partial<OrderChangesResponse> = {}): OrderChangesResponse {
  return {
    period: { year: 2026, month: 12, label: "Grudzień 2026" },
    counts: { changes: 0, entries: 0, exits: 0, ending: 0, gaps: 0 },
    changes: [],
    entries: [],
    exits: [],
    ending_orders: [],
    gaps: [],
    changes_tracked_since: null,
    gaps_tracked_since: "2026-01-01",
    open_gaps_total: 0,
    ...extra,
  };
}

describe("boardItems — zmiany", () => {
  it("klucz karty: zamówienie, grupa, brak obu; brak klucza pozycji → zapasowy", () => {
    const items = boardItems(
      data({
        changes: [
          change({ item_key: undefined }),
          change({ order_id: null, order_group_id: 7 }),
          change({ order_id: null, order_group_id: null }),
        ],
      }),
      "changes",
    );
    expect(items.map((i) => i.cardKey)).toEqual(["o:1", "g:7", "x:?"]);
    expect(items[0].key).toBe("changes:0");
  });

  it("autor: mail zamówień, wpisujący, zmiana automatyczna ze zdarzeniem i bez, nikt", () => {
    const items = boardItems(
      data({
        changes: [
          change({ from_order_mail: true, entered_by: "Ktoś" }),
          change({ entered_by: "Anna Przykładowa" }),
          change({ entered_automatically: true, event_id: 5 }),
          change({ entered_automatically: true, event_id: null }),
          change({}),
        ],
      }),
      "changes",
    );
    expect(items.map((i) => i.enteredBy)).toEqual([
      `dodane automatycznie (${ORDER_MAIL_ADDRESS})`,
      "Anna Przykładowa",
      "zmiana automatyczna",
      "dodane automatycznie",
      null,
    ]);
  });

  it("stawka przychodowa w całym zamówieniu, stara strona w swojej walucie; sortAt z kolejnych pól", () => {
    const [item] = boardItems(
      data({
        changes: [
          change({ kind: "rate_revenue", is_whole_order: true, old_currency: "EUR", effective_date: "2026-12-31" }),
        ],
      }),
      "changes",
    );
    expect(item).toMatchObject({ title: "Stawka przychodowa", note: "całe zamówienie", sortAt: "2026-12-31" });
    expect(item.before).toMatch(/^100,00 EUR\/h$/);
    expect(item.after).toMatch(/^120,00 zł\/h$/);
    expect(boardItems(data({ changes: [change({})] }), "changes")[0].sortAt).toBe("");
  });

  it("data końca: przedłużenie na bezterminowo, skrócenie, z bezterminowego na datę", () => {
    const items = boardItems(
      data({
        changes: [
          change({ kind: "end_date", old_date: "2026-12-31", new_date: null, is_whole_order: true }),
          change({ kind: "end_date", old_date: "2027-01-31", new_date: "2026-12-31" }),
          change({ kind: "end_date", old_date: null, new_date: "2027-01-01" }),
          change({ kind: "end_date", old_date: null, new_date: null }),
        ],
      }),
      "changes",
    );
    expect(items.map((i) => i.label)).toEqual(["extension", "period", "period", "period"]);
    expect(items[0]).toMatchObject({ before: "31.12.2026", after: "bezterminowo", note: "całe zamówienie" });
    expect(items[2].before).toBe("bezterminowo");
  });

  it("kontynuacja: po zamówieniu, od współpracy, bez dowodu", () => {
    const items = boardItems(
      data({
        changes: [
          change({ kind: "order_continuation", previous_order_number: "T-0", previous_end_date: "2026-12-31" }),
          change({ kind: "order_continuation", engagement_since: "2025-01-01" }),
          change({ kind: "order_continuation" }),
        ],
      }),
      "changes",
    );
    expect(items.map((i) => i.note)).toEqual(["po zam. T-0 (do 31.12.2026)", "współpraca od 01.01.2025", null]);
    expect(items[0].after).toMatch(/^stawka przychodowa 1000,00 zł\/MD · stawka kosztowa 800,00 zł\/MD$/);
  });

  it("zmiana klienta i dodatkowy projekt bez nazw: kreski", () => {
    const items = boardItems(
      data({ changes: [change({ kind: "client_change" }), change({ kind: "additional_project" })] }),
      "changes",
    );
    expect(items.map((i) => [i.title, i.note])).toEqual([
      ["Nowe zamówienie (zmiana klienta)", "wcześniej u: —"],
      ["Nowe zamówienie (dodatkowy projekt)", "równolegle u: —"],
    ]);
    const named = boardItems(
      data({
        changes: [
          change({ kind: "client_change", previous_client_name: "Inna Firma Testowa" }),
          change({ kind: "additional_project", other_client_names: ["A", "B"] }),
        ],
      }),
      "changes",
    );
    expect(named.map((i) => i.note)).toEqual(["wcześniej u: Inna Firma Testowa", "równolegle u: A, B"]);
  });
});

describe("boardItems — wejścia, zejścia, braki", () => {
  it("wejście: zmiana klienta + szkic; bez stawek; sortAt ze startu", () => {
    const [a, b] = boardItems(
      data({
        entries: [
          entry({ previous_client_name: "Inna Firma Testowa", status: "draft", entered_at: "2026-12-30T10:00:00Z" }),
          entry({ item_key: "ent:2", rate_cost: null, rate_revenue: null, invoice_lines: null }),
        ],
      }),
      "entries",
    );
    expect(a).toMatchObject({
      title: "Nowe zamówienie (zmiana klienta)",
      note: "wcześniej u: Inna Firma Testowa · szkic",
      sortAt: "2026-12-30T10:00:00Z",
    });
    expect(a.enteredAt).not.toBeNull();
    expect(b).toMatchObject({ title: "Nowe zamówienie", note: null, sortAt: "2027-01-01", invoiceLines: null });
    expect(b.after).toBe("stawka przychodowa — · stawka kosztowa —");
  });

  it("wejście bez daty startu i znacznika czasu: pusty sortAt", () => {
    expect(boardItems(data({ entries: [entry({ start_date: null })] }), "entries")[0].sortAt).toBe("");
  });

  it("zejście z innymi zamówieniami (pola opcjonalne puste) i koniec zamówienia", () => {
    const [ex] = boardItems(
      data({ exits: [exit({ other_orders: [{ order_number: "T-2" } as never] })] }),
      "exits",
    );
    expect(ex).toMatchObject({ label: "exit", title: "Zejście", after: "31.12.2026", note: "Zakończenie współpracy" });
    expect(ex.otherOrders).toEqual([{ orderNumber: "T-2", orderStart: null, orderEnd: null, pdf: null }]);
    const [end] = boardItems(data({ ending_orders: [exit({})] }), "ending");
    expect(end).toMatchObject({ tab: "ending", label: "ending", title: "Koniec zamówienia", otherOrders: [] });
  });

  it("brak zamówienia na granicy roku", () => {
    const [g] = boardItems(data({ gaps: [gap()] }), "gaps");
    expect(g).toMatchObject({
      label: "gap",
      after: "po 31.12.2026 (wykryto 01.01.2027)",
      note: "Brak zamówienia",
      sortAt: "2027-01-01",
    });
  });

  it("pozycje jednej karty ze wszystkich podzakładek", () => {
    const all = cardItemsAllTabs(
      data({
        changes: [change({})],
        entries: [entry({ order_id: 2 })],
        exits: [exit()],
        ending_orders: [exit({ item_key: "end:1" })],
        gaps: [gap()],
      }),
      "o:1",
    );
    expect(all.map((i) => i.tab)).toEqual(["changes", "exits", "ending", "gaps"]);
    expect(cardItemsAllTabs(data(), "o:1")).toEqual([]);
  });
});

function item(overrides: Partial<BoardItem>): BoardItem {
  return {
    key: "k",
    tab: "changes",
    cardKey: "o:1",
    orderId: 1,
    orderGroupId: null,
    clientId: 10,
    clientName: "Firma Testowa",
    consultantName: "Jan Testowy",
    orderNumber: "T-1",
    orderStart: null,
    orderEnd: null,
    label: "rate_cost",
    field: "rate_cost",
    title: "Stawka kosztowa",
    before: null,
    after: null,
    note: null,
    enteredAt: null,
    enteredBy: null,
    done: null,
    pdf: null,
    sortAt: "",
    ...overrides,
  };
}

describe("kafelki, tytuły, podsumowania", () => {
  it("klient bez id: „Bez klienta”, klucz „none”", () => {
    expect(clientKey(null)).toBe("none");
    const tiles = clientTiles([item({ clientId: null }), item({ clientId: 10, done: DONE })]);
    expect(tiles.map((t) => [t.key, t.name, t.todo, t.total])).toEqual([
      ["none", "Bez klienta", 1, 1],
      ["10", "Firma Testowa", 0, 1],
    ]);
  });

  it("przy równej liczbie do zrobienia — alfabetycznie", () => {
    const tiles = clientTiles([
      item({ clientId: 2, clientName: "Beta" }),
      item({ clientId: 1, clientName: "Alfa" }),
    ]);
    expect(tiles.map((t) => t.name)).toEqual(["Alfa", "Beta"]);
  });

  it("tytuł karty bez startu i końca", () => {
    expect(cardTitle({ orderNumber: "T-1", orderStart: null, orderEnd: null, consultantName: "Jan Testowy" })).toBe(
      "Zam. T-1 · — – bezterminowo · Jan Testowy",
    );
  });

  it("podsumowanie pozycji: bez przed i po, z samym po", () => {
    expect(itemSummary(item({}))).toBe("Stawka kosztowa");
    expect(itemSummary(item({ after: "31.12.2026" }))).toBe("Stawka kosztowa: 31.12.2026");
    expect(itemSummary(item({ before: "a", after: "b" }))).toBe("Stawka kosztowa: a → b");
  });

  it("etykieta odhaczenia i miesiąca", () => {
    expect(doneLabel(DONE)).toMatch(/^Zrobione: Anna Przykładowa · 31\.12\.2026/);
    expect(doneInMonthLabel(12)).toBe("Zrobione w grudniu");
    expect(doneInMonthLabel(9)).toBe("Zrobione we wrześniu");
    expect(doneInMonthLabel(13)).toBe("Zrobione w ");
  });
});

describe("buildCards / splitCards — brzegi", () => {
  it("odhaczenia przykryte: dopasowanie po zamówieniu, po grupie i z filtrem podzakładki", () => {
    const superseded = [
      { item_key: "a", tab: "changes" as const, order_id: 1, order_group_id: null, summary: "po zamówieniu", done: DONE },
      { item_key: "b", tab: "changes" as const, order_id: null, order_group_id: 5, summary: "po grupie", done: DONE },
      { item_key: "c", tab: "entries" as const, order_id: 1, order_group_id: null, summary: "inna zakładka", done: DONE },
      { item_key: "d", tab: "changes" as const, order_id: 2, order_group_id: null, summary: "inne zamówienie", done: DONE },
    ];
    const cards = buildCards(
      [
        item({ key: "x", cardKey: "o:1" }),
        item({ key: "y", cardKey: "g:5", orderId: null, orderGroupId: 5, consultantName: "Anna Przykładowa" }),
      ],
      "todo",
      superseded,
      "changes",
    );
    const byKey = Object.fromEntries(cards.map((c) => [c.key, c.previous.map((p) => p.summary)]));
    expect(byKey).toEqual({ "o:1": ["po zamówieniu"], "g:5": ["po grupie"] });
    expect(cards.every((c) => c.changedAgain)).toBe(true);

    const noTab = buildCards([item({ key: "x" })], "todo", superseded);
    expect(noTab[0].previous.map((p) => p.summary)).toEqual(["po zamówieniu", "inna zakładka"]);
  });

  it("grupa z zamówieniem nie łapie odhaczeń po samej grupie", () => {
    const cards = buildCards(
      [item({ orderId: 1, orderGroupId: 5 })],
      "all",
      [{ item_key: "b", tab: "changes", order_id: null, order_group_id: 5, summary: "s", done: DONE }],
    );
    expect(cards[0].previous).toEqual([]);
    expect(cards[0].changedAgain).toBe(false);
  });

  it("filtr „Zrobione”: tylko odhaczone, karty bez odhaczeń znikają, splitCards nie dzieli", () => {
    const cards = buildCards(
      [
        item({ key: "a", cardKey: "o:1", done: DONE }),
        item({ key: "b", cardKey: "o:1", sortAt: "2" }),
        item({ key: "c", cardKey: "o:2", orderId: 2 }),
      ],
      "done",
    );
    expect(cards.map((c) => c.key)).toEqual(["o:1"]);
    expect(cards[0].visible.map((v) => v.item.key)).toEqual(["a"]);
    expect(splitCards(cards, "done")).toEqual({ open: cards, finished: [] });
  });

  it("karty z czymś do zrobienia przed zrobionymi, potem alfabetycznie; PDF z pierwszej pozycji, która go ma", () => {
    const pdf = { kind: "order", id: 1, month: "2026-12", client_id: 10, download_name: "a.pdf" } as never;
    const cards = buildCards(
      [
        item({ key: "a", cardKey: "o:1", consultantName: "Zofia", done: DONE }),
        item({ key: "b", cardKey: "o:2", orderId: 2, consultantName: "Ziemowit" }),
        item({ key: "c", cardKey: "o:3", orderId: 3, consultantName: "Adam" }),
        item({ key: "d", cardKey: "o:3", orderId: 3, consultantName: "Adam", pdf, sortAt: "2" }),
      ],
      "all",
    );
    expect(cards.map((c) => c.consultantName)).toEqual(["Adam", "Ziemowit", "Zofia"]);
    expect(cards[0].pdf).toBe(pdf);
    expect(splitCards(cards, "all").finished.map((c) => c.key)).toEqual(["o:1"]);
  });
});

describe("withInvoiceLines", () => {
  it("podmienia po indeksie tylko linie tego zamówienia; wejście bez linii zostaje", () => {
    const lines = [
      { index: 0, consultant: "Jan Testowy", text: "stara", edited_by_name: null, edited_at: null },
      { index: 1, consultant: "Jan Testowy", text: "bez zmian", edited_by_name: null, edited_at: null },
    ];
    const before = data({
      entries: [
        entry({ order_id: 1, invoice_lines: lines }),
        entry({ order_id: 2, invoice_lines: lines }),
        entry({ order_id: 1, item_key: "ent:3", invoice_lines: null }),
      ],
    });
    const saved = [{ index: 0, consultant: "Jan Testowy", text: "nowa", edited_by_name: "Anna Przykładowa", edited_at: "2026-12-31" }];
    const after = withInvoiceLines(before, 1, saved);
    expect(after.entries[0].invoice_lines?.map((l) => l.text)).toEqual(["nowa", "bez zmian"]);
    expect(after.entries[1].invoice_lines?.map((l) => l.text)).toEqual(["stara", "bez zmian"]);
    expect(after.entries[2].invoice_lines).toBeNull();
    expect(withInvoiceLines(before, 1, []).entries[0].invoice_lines?.[0].text).toBe("stara");
  });
});
