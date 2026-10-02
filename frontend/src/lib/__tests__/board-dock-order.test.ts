import { describe, expect, it } from "vitest";

import { dockNavigationOrder } from "@/lib/board-dock-order";

const card = (candidate_id: number) => ({ candidate_id });

describe("dockNavigationOrder — kolejność widoczna na Tablicy", () => {
  it("kolumny od lewej, karty od góry; pierwsza karta w „Nowi” jest pierwsza", () => {
    const columns = [
      { items: [card(1), card(2)] }, // Nowi
      { items: [] }, // pusta kolumna
      { items: [card(3), card(4)] }, // Zweryfikowany
    ];
    expect(dockNavigationOrder(columns)).toEqual([1, 2, 3, 4]);
  });

  it("osoba widoczna w dwóch kolumnach wchodzi raz — przy pierwszej", () => {
    const columns = [{ items: [card(1), card(2)] }, { items: [card(2), card(3)] }];
    expect(dockNavigationOrder(columns)).toEqual([1, 2, 3]);
  });
});
