import { describe, expect, it } from "vitest";

import {
  attemptLabel,
  orderScreeningColumn,
  returnNotice,
  screeningGroupLabel,
  screeningGroupOf,
} from "@/lib/screening-column-groups";

// 18.11.2026 12:00 w Warszawie (środa).
const WEDNESDAY = new Date("2026-11-18T11:00:00Z");
const FRIDAY = new Date("2026-11-20T11:00:00Z");

describe("screeningGroupOf", () => {
  it("rozmowa (arkusz albo odpowiedzi w karcie) wygrywa z próbami", () => {
    expect(screeningGroupOf({ id: 1, screening_done: true, contact_attempts: 2 })).toBe("after_call");
    expect(screeningGroupOf({ id: 1, card: { answers: 3 }, contact_attempts: 1 })).toBe("after_call");
  });
  it("próby bez rozmowy = „Nie odebrał”, reszta = „Do telefonu”", () => {
    expect(screeningGroupOf({ id: 1, screening_done: false, contact_attempts: 1 })).toBe("no_answer");
    expect(screeningGroupOf({ id: 1, card: { answers: 0 } })).toBe("to_call");
    expect(screeningGroupOf({ id: 1 })).toBe("to_call");
  });
});

describe("orderScreeningColumn", () => {
  it("grupy po kolei, w grupie najpierw najbliższy powrót, potem kolejność serwera", () => {
    const items = [
      { id: 1, screening_done: true },
      { id: 2, contact_attempts: 1, returns_to_new_on: "2026-11-20" },
      { id: 3 },
      { id: 4, returns_to_new_on: "2026-11-19" },
      { id: 5, contact_attempts: 2, returns_to_new_on: "2026-11-19" },
      { id: 6 },
    ];
    const { items: out, groups } = orderScreeningColumn(items);
    expect(out.map((i) => i.id)).toEqual([4, 3, 6, 5, 2, 1]);
    expect(groups.get(1)).toBe("after_call");
    expect(groups.get(5)).toBe("no_answer");
  });
});

describe("napisy", () => {
  it("nagłówki z liczbą kart", () => {
    expect(screeningGroupLabel("to_call", 4)).toBe("Do telefonu · 4");
    expect(screeningGroupLabel("no_answer", 2)).toBe("Nie odebrał · do 3 prób · 2");
    expect(screeningGroupLabel("after_call", 1)).toBe("Po rozmowie · dokończ arkusz · 1");
  });
  it("próba N z 3, po trzeciej prośba o wynik", () => {
    expect(attemptLabel(0)).toBeNull();
    expect(attemptLabel(2)).toBe("próba 2 z 3");
    expect(attemptLabel(4)).toBe("próba 3 z 3 · wpisz wynik albo odrzuć");
  });
});

describe("returnNotice", () => {
  it("jutro i dziś", () => {
    expect(returnNotice("2026-11-19", "screening", WEDNESDAY)).toBe("Wraca do „Nowych” jutro");
    expect(returnNotice("2026-11-18", "screening", WEDNESDAY)).toBe("Wraca do „Nowych” dziś");
    expect(returnNotice("2026-11-19", "new", WEDNESDAY)).toBe("„Biorę” wygasa jutro");
  });
  it("w piątek przed powrotem w poniedziałek mówi dzień tygodnia", () => {
    expect(returnNotice("2026-11-23", "screening", FRIDAY)).toBe("Wraca do „Nowych” w poniedziałek");
  });
  it("dalszy termin i brak terminu nic nie mówią", () => {
    expect(returnNotice("2026-11-20", "screening", WEDNESDAY)).toBeNull();
    expect(returnNotice(null, "screening", WEDNESDAY)).toBeNull();
    expect(returnNotice(undefined, "new", WEDNESDAY)).toBeNull();
  });
});
