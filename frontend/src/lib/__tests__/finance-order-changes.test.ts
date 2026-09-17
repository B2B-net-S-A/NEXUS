import { describe, expect, it } from "vitest";

import type { OrderChangeItem, OrderEntryItem, OrderGapItem } from "@/lib/api/finance";
import {
  changeMeta,
  changeTitle,
  changeValue,
  entryTags,
  formatRate,
  gapStatusLabel,
  initials,
  monthOptions,
  parseMonthValue,
  peopleLabel,
} from "@/lib/finance-order-changes";

const baseRef = {
  order_id: 1,
  order_group_id: null,
  contract_id: 2,
  client_id: 3,
  client_name: "Klient",
  consultant_name: "Jan Nowak",
  order_number: "NB-1",
};

function change(overrides: Partial<OrderChangeItem>): OrderChangeItem {
  return {
    ...baseRef,
    kind: "rate_revenue",
    occurred_at: "2026-09-10T10:00:00Z",
    effective_date: "2026-09-10",
    old_amount: 152,
    new_amount: 170,
    old_unit: "hourly",
    new_unit: "hourly",
    currency: "PLN",
    old_date: null,
    new_date: null,
    is_whole_order: false,
    source: "user",
    author_name: "Anna",
    rate_cost: null,
    rate_revenue: null,
    rate_unit: null,
    other_client_names: [],
    previous_order_number: null,
    previous_end_date: null,
    previous_client_name: null,
    start_date: null,
    ...overrides,
  };
}

describe("finance order changes formatting", () => {
  it("offers next month, the current month first after it, and history", () => {
    const options = monthOptions(new Date(2026, 8, 17));
    expect(options[0].value).toBe("2026-10");
    expect(options[1]).toMatchObject({ value: "2026-09", label: "Wrzesień 2026" });
    expect(options.at(-1)?.value).toBe("2024-09");
    expect(parseMonthValue("2026-13")).toBeNull();
    expect(parseMonthValue("2026-02")).toEqual({ year: 2026, month: 2 });
  });

  it("always shows a rate with its unit and currency", () => {
    expect(formatRate(1340, "md", "PLN")).toBe("1340,00 zł/MD");
    expect(formatRate(35, "hourly", "EUR")).toBe("35,00 EUR/h");
    expect(formatRate(null, "hourly", "PLN")).toBe("—");
  });

  it("describes old → new values, including an open-ended order", () => {
    expect(changeValue(change({}))).toBe("152,00 zł/h → 170,00 zł/h");
    expect(
      changeValue(
        change({ kind: "end_date", old_date: "2026-12-31", new_date: null }),
      ),
    ).toBe("31.12.2026 → bezterminowo");
  });

  it("describes a continuation as the previous order handing over to the new one", () => {
    const item = change({
      kind: "order_continuation",
      occurred_at: null,
      effective_date: "2026-09-01",
      rate_cost: 120,
      rate_revenue: 152,
      rate_unit: "hourly",
      previous_order_number: "NB-1980",
      previous_end_date: "2026-08-31",
      previous_client_name: "Klient",
      old_amount: null,
      new_amount: null,
    });
    expect(changeTitle(item)).toBe("Kontynuacja zamówienia");
    expect(changeValue(item)).toBe(
      "po zam. NB-1980 (do 31.08.2026) · od 01.09.2026 · " +
        "koszt 120,00 zł/h · przychód 152,00 zł/h",
    );
    // Klient i numer nowego zamówienia stoją w wierszu meta — powtórzone
    // w opisie czytałyby się jak druga, inna wartość (dowodzi tego `toBe`
    // wyżej: w opisie jest wyłącznie numer POPRZEDNIEGO zamówienia).
    expect(changeMeta(item)).toBe("Klient · zam. NB-1");
  });

  it("names both clients when a consultant moves between them", () => {
    const item = change({
      kind: "client_change",
      occurred_at: null,
      effective_date: "2026-09-08",
      rate_cost: 140,
      rate_revenue: 185,
      rate_unit: "hourly",
      previous_order_number: "UD-12",
      previous_end_date: "2026-08-29",
      previous_client_name: "Ubezpieczenia Demo",
      old_amount: null,
      new_amount: null,
    });
    expect(changeTitle(item)).toBe("Zmiana klienta");
    expect(changeValue(item)).toBe(
      "z: Ubezpieczenia Demo · zam. UD-12 (do 29.08.2026) · od 08.09.2026 · " +
        "koszt 140,00 zł/h · przychód 185,00 zł/h",
    );
    // Docelowy klient jest w wierszu meta, nie w opisie.
    expect(changeMeta(item)).toBe("Klient · zam. NB-1");
  });

  it("does not invent an author for a row that has no journal entry", () => {
    const item = change({ kind: "client_change", occurred_at: null, source: null });
    expect(changeMeta(item)).toBe("Klient · zam. NB-1");
    expect(changeMeta(change({}))).toContain("Anna");
  });

  it("marks every entry as a new consultant, drafts included", () => {
    const entry = {
      ...baseRef,
      start_date: "2026-09-01",
      end_date: null,
      rate_cost: 120,
      rate_revenue: 152,
      rate_unit: "hourly",
      currency: "PLN",
      order_type: "periodic",
      status: "active",
    } as OrderEntryItem;
    expect(entryTags(entry)).toEqual(["Nowy konsultant"]);
    expect(entryTags({ ...entry, status: "draft" })).toEqual([
      "Nowy konsultant",
      "Szkic",
    ]);
  });

  it("keeps a late-filled gap visible with the delay", () => {
    const gap: OrderGapItem = {
      ...baseRef,
      gap_id: 9,
      ended_on: "2026-08-31",
      detected_on: "2026-09-01",
      status: "filled_late",
      resolved_order_number: "NB-2",
      resolved_at: "2026-09-08T10:00:00Z",
      delay_days: 7,
    };
    expect(gapStatusLabel(gap)).toBe(
      "Uzupełnione z opóźnieniem: zam. NB-2 (7 dni po terminie)",
    );
    expect(gapStatusLabel({ ...gap, delay_days: 0 })).toBe(
      "Uzupełnione z opóźnieniem: zam. NB-2 (w dniu wykrycia braku)",
    );
    expect(gapStatusLabel({ ...gap, status: "open" })).toBe("Brak zamówienia");
  });

  it("uses Polish plural forms and initials", () => {
    expect(peopleLabel(1)).toBe("1 osoba ma");
    expect(peopleLabel(3)).toBe("3 osoby mają");
    expect(peopleLabel(5)).toBe("5 osób ma");
    expect(peopleLabel(12)).toBe("12 osób ma");
    expect(initials("Jan Nowak-Kowalski")).toBe("JK");
  });
});
