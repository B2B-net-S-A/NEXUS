import { describe, expect, it } from "vitest";

import type { OrderChangeItem, OrderGapItem } from "@/lib/api/finance";
import {
  changeValue,
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
