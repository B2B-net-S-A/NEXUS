import { describe, expect, it } from "vitest";

import { dockNavigationOrder } from "@/lib/board-dock-order";

const card = (candidate_id: number, dim = false) => ({ candidate_id, dim });

describe("dockNavigationOrder — kolejność widoczna na Tablicy", () => {
  const columns = [
    { items: [card(1), card(2)] }, // Nowi
    { items: [] }, // pusta kolumna
    { items: [card(3, true), card(4)] }, // Zweryfikowany (3 przygaszona filtrem)
  ];

  it("kolumny od lewej, karty od góry; pierwsza karta w „Nowi” jest pierwsza", () => {
    expect(dockNavigationOrder(columns, () => false, 1)).toEqual([1, 2, 3, 4]);
  });

  it("karty przygaszone filtrem pomija, poza kartą otwartą w doku", () => {
    expect(dockNavigationOrder(columns, (c) => c.dim, 1)).toEqual([1, 2, 4]);
    expect(dockNavigationOrder(columns, (c) => c.dim, 3)).toEqual([1, 2, 3, 4]);
  });
});
