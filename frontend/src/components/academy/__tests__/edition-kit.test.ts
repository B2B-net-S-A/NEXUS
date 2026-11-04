import { describe, expect, it } from "vitest";

import {
  assignItem,
  freeModels,
  kitPayload,
  proposeKits,
  splitComplete,
} from "@/components/academy/edition-kit";
import type { EquipmentCategory, EquipmentItem } from "@/lib/api/equipment";

function item(
  id: number,
  modelId: number,
  category: EquipmentCategory,
  inventory: string | null,
): EquipmentItem {
  return {
    id,
    model: {
      id: modelId,
      category,
      name: `Model ${modelId}`,
      manufacturer: null,
      price_pln: "100.00",
      is_active: true,
    },
    category,
    inventory_number: inventory,
    serial_number: `TEST-${id}`,
    imei: null,
    iccid: null,
    phone_number: null,
    access_card_number: null,
    status: "na_stanie",
    ownership: "nasz",
    purchase_date: null,
    location: null,
    notes: null,
    holder: null,
    issue_protocol: null,
  };
}

// Laptopy: model 1 (numery 10, 9, 101 — kolejność naturalna 9, 10, 101), telefon: model 2.
const ITEMS = [
  item(1, 1, "laptop", "10"),
  item(2, 1, "laptop", "9"),
  item(3, 1, "laptop", "101"),
  item(4, 2, "telefon", "T-2"),
  item(5, 2, "telefon", "T-1"),
];

describe("freeModels", () => {
  it("groups free items by model in register category order", () => {
    expect(freeModels([...ITEMS].reverse())).toEqual([
      { modelId: 1, name: "Model 1", category: "laptop", free: 3 },
      { modelId: 2, name: "Model 2", category: "telefon", free: 2 },
    ]);
  });
});

describe("proposeKits", () => {
  it("hands out items by natural inventory order and leaves gaps when stock ends", () => {
    const plan = proposeKits([100, 200, 300], [1, 2], ITEMS);
    expect(plan).toEqual({
      100: { 1: 2, 2: 5 },
      200: { 1: 1, 2: 4 },
      300: { 1: 3, 2: null },
    });
    expect(splitComplete(plan, [1, 2])).toEqual({ ready: [100, 200], incomplete: [300] });
  });

  it("treats an empty kit as incomplete for everyone", () => {
    expect(splitComplete(proposeKits([100], [], ITEMS), [])).toEqual({
      ready: [],
      incomplete: [100],
    });
  });
});

describe("assignItem", () => {
  it("swaps an item already given to someone else instead of duplicating it", () => {
    const plan = proposeKits([100, 200], [1], ITEMS);
    const swapped = assignItem(plan, 100, 1, 1);
    expect(swapped).toEqual({ 100: { 1: 1 }, 200: { 1: 2 } });
    expect(plan).toEqual({ 100: { 1: 2 }, 200: { 1: 1 } });
  });

  it("clears a cell without touching other people", () => {
    const plan = proposeKits([100, 200], [1, 2], ITEMS);
    const cleared = assignItem(plan, 200, 2, null);
    expect(cleared[200]).toEqual({ 1: 1, 2: null });
    expect(cleared[100]).toBe(plan[100]);
    expect(splitComplete(cleared, [1, 2]).incomplete).toEqual([200]);
  });
});

describe("kitPayload", () => {
  it("sends only participants with a complete kit, one line per model", () => {
    const plan = proposeKits([100, 200, 300], [1, 2], ITEMS);
    const { ready } = splitComplete(plan, [1, 2]);
    expect(kitPayload(plan, [1, 2], ready)).toEqual([
      { application_id: 100, lines: [{ item_id: 2 }, { item_id: 5 }] },
      { application_id: 200, lines: [{ item_id: 1 }, { item_id: 4 }] },
    ]);
  });
});
