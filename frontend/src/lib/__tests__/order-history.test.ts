import { describe, expect, it } from "vitest";

import type { OrderHistoryEntry } from "@/lib/api/orderGroups";
import {
  ALL_PEOPLE,
  changesLabel,
  filterOrderHistory,
  mdImportHref,
} from "@/lib/order-history";

function entry(overrides: Partial<OrderHistoryEntry>): OrderHistoryEntry {
  return {
    key: "k",
    category: "order",
    event_type: "utworzenie",
    type_label: "Utworzenie zamówienia",
    created_at: "2026-09-01T10:00:00Z",
    author_id: null,
    author_name: null,
    summary: "",
    order_id: null,
    person_name: null,
    person_names: [],
    changes: [],
    balance_before: null,
    balance_after: null,
    details: [],
    import_id: null,
    import_period_month: null,
    import_people: null,
    import_md: null,
    related_group_id: null,
    related_order_number: null,
    ...overrides,
  };
}

const ENTRIES = [
  entry({ key: "created" }),
  entry({ key: "added", category: "consultants", person_names: ["Konrad Teper"] }),
  entry({ key: "import", category: "consumption", person_names: ["Konrad Teper", "Paweł Łaski"] }),
  entry({ key: "edit", category: "edits", person_names: ["Paweł Łaski"] }),
];

describe("filterOrderHistory", () => {
  it("„Wszystko” i wszyscy — pełna lista w tej samej kolejności", () => {
    expect(
      filterOrderHistory(ENTRIES, { category: "all", person: ALL_PEOPLE }).map((e) => e.key),
    ).toEqual(["created", "added", "import", "edit"]);
  });

  it("typ zdarzenia zawęża do kategorii", () => {
    expect(
      filterOrderHistory(ENTRIES, { category: "consumption", person: ALL_PEOPLE }).map(
        (e) => e.key,
      ),
    ).toEqual(["import"]);
    expect(
      filterOrderHistory(ENTRIES, { category: "edits", person: ALL_PEOPLE }).map((e) => e.key),
    ).toEqual(["edit"]);
  });

  it("osoba: wpisy tej osoby, także import obejmujący kilka osób; wpis bez osoby odpada", () => {
    expect(
      filterOrderHistory(ENTRIES, { category: "all", person: "Paweł Łaski" }).map((e) => e.key),
    ).toEqual(["import", "edit"]);
  });

  it("oba filtry naraz", () => {
    expect(
      filterOrderHistory(ENTRIES, { category: "consultants", person: "Paweł Łaski" }),
    ).toEqual([]);
  });
});

describe("changesLabel", () => {
  it.each([
    [1, "1 zmiana"],
    [2, "2 zmiany"],
    [4, "4 zmiany"],
    [5, "5 zmian"],
    [6, "6 zmian"],
    [12, "12 zmian"],
    [22, "22 zmiany"],
  ])("%i → %s", (count, label) => {
    expect(changesLabel(count)).toBe(label);
  });
});

it("mdImportHref prowadzi do zakładki „Importy MD” z otwartym importem", () => {
  expect(mdImportHref(18, 2)).toBe("/clients/18?tab=importy-md&import=2");
});
