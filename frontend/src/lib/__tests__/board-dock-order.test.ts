import { describe, expect, it } from "vitest";

import {
  dockNavigationOrder,
  nextColumnWithPeople,
  queueColumnAfterOpen,
  returnToQueueTarget,
} from "@/lib/board-dock-order";

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

describe("kolejka panelu w jednej kolumnie (D1, 14.10.2026)", () => {
  it("osoba z obecnej kolejki zostawia kolejkę", () => {
    expect(queueColumnAfterOpen("def:1", 2, [1, 2, 3], "def:1")).toBe("def:1");
  });

  it("osoba z innej kolumny Tablicy przenosi kolejkę do swojej kolumny", () => {
    expect(queueColumnAfterOpen("def:1", 9, [1, 2, 3], "def:2")).toBe("def:2");
    expect(queueColumnAfterOpen(null, 9, [], "def:2")).toBe("def:2");
  });

  it("osoba spoza kolumn Tablicy (zamknięta) zostawia kolejkę", () => {
    expect(queueColumnAfterOpen("def:1", 9, [1, 2, 3], null)).toBe("def:1");
  });

  it("„Wróć do kolejki” prowadzi do osoby, która stała za wypadniętą", () => {
    expect(returnToQueueTarget([1, 3, 4], [2, 3, 4])).toBe(3);
  });

  it("gdy za wypadniętą nikogo nie ma — pierwsza osoba kolejki; pusta kolejka — nic", () => {
    expect(returnToQueueTarget([1, 3], [5])).toBe(1);
    expect(returnToQueueTarget([], [5])).toBeNull();
  });

  it("„Dalej” wskazuje pierwszą kolumnę na prawo, w której ktoś jest", () => {
    const columns = [
      { key: "new", items: [card(1)] },
      { key: "screening", items: [] },
      { key: "verified", items: [card(3)] },
    ];
    expect(nextColumnWithPeople(columns, 0)?.key).toBe("verified");
    expect(nextColumnWithPeople(columns, 2)).toBeNull();
  });
});
