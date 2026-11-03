import { describe, expect, it } from "vitest";
import {
  daysAgoText,
  knownFactLabels,
  newColumnSection,
  orderNewColumn,
  waitsInSystemQueue,
} from "@/lib/new-column-queue";

const system = (id: number, score: number, extra: object = {}) => ({
  id,
  candidate_id: id * 10,
  entry_source: "system",
  entry_autofill: { score, decided: false, cautions: [] },
  ...extra,
});
const team = (id: number) => ({ id, candidate_id: id * 10, entry_source: "added_manual" });

describe("orderNewColumn", () => {
  it("odwraca paczkę od systemu: najwyższy wynik pierwszy, zespół na górze", () => {
    // Kolejność z serwera: od najmłodszego, więc w paczce od najniższego wyniku.
    const { items, ranks, total } = orderNewColumn([team(1), system(2, 75), system(3, 76), team(4), system(5, 79)]);
    expect(items.map((i) => i.id)).toEqual([1, 4, 5, 3, 2]);
    expect(ranks.get(5)).toBe(1);
    expect(ranks.get(2)).toBe(3);
    expect(ranks.has(1)).toBe(false);
    expect(total).toBe(3);
  });

  it("kartę, którą ktoś wziął, traktuje jak kartę zespołu", () => {
    const decided = system(2, 90, { entry_autofill: { score: 90, decided: true, cautions: [] } });
    const claimed = system(3, 88, { claim_user_id: 7 });
    expect(waitsInSystemQueue(decided)).toBe(false);
    expect(waitsInSystemQueue(claimed)).toBe(false);
    const { items, ranks } = orderNewColumn([system(1, 70), decided, claimed]);
    expect(items.map((i) => i.id)).toEqual([2, 3, 1]);
    expect(ranks.get(1)).toBe(1);
  });

  it("ostrzeżenie za osobami bez uwag, brak krytycznej na samym końcu", () => {
    const caution = system(2, 80, { entry_autofill: { score: 80, decided: false, cautions: [{ key: "budget" }] } });
    const gap = system(3, 90);
    const { items } = orderNewColumn([gap, caution, system(4, 70)], new Map([[30, ["angular"]]]));
    expect(items.map((i) => i.id)).toEqual([4, 2, 3]);
  });

  it("remis wyniku rozstrzyga numer osoby, więc kolejność jest stała", () => {
    const { items } = orderNewColumn([system(3, 75), system(1, 75), system(2, 75)]);
    expect(items.map((i) => i.id)).toEqual([1, 2, 3]);
  });

  it("karta od systemu bez migawki zostaje u góry i nie psuje kolejki", () => {
    const { items, total } = orderNewColumn([{ id: 9, candidate_id: 90, entry_source: "system", entry_autofill: null }, system(1, 70)]);
    expect(items.map((i) => i.id)).toEqual([9, 1]);
    expect(total).toBe(1);
  });
});

describe("nowi w bazie najpierw (03.11.2026)", () => {
  const fresh = (id: number, score: number) =>
    system(id, score, { entry_autofill: { score, decided: false, cautions: [], fresh_first: true } });

  it("nowa w bazie wyprzedza wyższy wynik, między nowymi liczy się wynik", () => {
    const { items, ranks, freshFirst } = orderNewColumn([system(1, 95), fresh(2, 71), fresh(3, 74)]);
    expect(items.map((i) => i.id)).toEqual([3, 2, 1]);
    expect(ranks.get(3)).toBe(1);
    expect(freshFirst).toBe(true);
  });

  it("wyprzedza też punkty „znamy tę osobę”", () => {
    const familiar = system(1, 78, {
      entry_autofill: {
        score: 78,
        decided: false,
        cautions: [],
        known: { points: 14, client_points: 6, note_points: 8, verified_at_client: 2, last_note_days: 5 },
      },
    });
    expect(orderNewColumn([familiar, fresh(2, 70)]).items.map((i) => i.id)).toEqual([2, 1]);
  });

  it("brak krytycznej cofa nową na koniec", () => {
    const { items, freshFirst } = orderNewColumn([fresh(1, 90), system(2, 70)], new Map([[10, ["angular"]]]));
    expect(items.map((i) => i.id)).toEqual([2, 1]);
    expect(freshFirst).toBe(false);
  });

  it("bez nowych w bazie kolejka jest jak dotąd", () => {
    expect(orderNewColumn([system(1, 70), system(2, 80)]).freshFirst).toBe(false);
  });
});

describe("znamy tę osobę", () => {
  const known = (points: number) => ({
    points,
    client_points: points,
    note_points: 0,
    verified_at_client: 1,
    last_note_days: null,
  });

  it("punkty podnoszą kartę ponad osobę z wyższym wynikiem", () => {
    const familiar = system(2, 72, { entry_autofill: { score: 72, decided: false, cautions: [], known: known(6) } });
    const { items, ranks } = orderNewColumn([system(1, 75), familiar]);
    expect(items.map((i) => i.id)).toEqual([2, 1]);
    expect(ranks.get(2)).toBe(1);
  });

  it("punkty nie przebijają brakującej krytycznej", () => {
    const familiar = system(2, 90, { entry_autofill: { score: 90, decided: false, cautions: [], known: known(15) } });
    const { items } = orderNewColumn([familiar, system(1, 60)], new Map([[20, ["java"]]]));
    expect(items.map((i) => i.id)).toEqual([1, 2]);
  });

  it("opisuje powody krótko i pomija te bez punktów", () => {
    expect(
      knownFactLabels({ points: 14, client_points: 6, note_points: 8, verified_at_client: 7, last_note_days: 2 }),
    ).toEqual(["U klienta · 7×", "Notatka 2 dni temu"]);
    expect(
      knownFactLabels({ points: 8, client_points: 0, note_points: 8, verified_at_client: 0, last_note_days: 1 }),
    ).toEqual(["Notatka wczoraj"]);
    expect(knownFactLabels(null)).toEqual([]);
    expect(daysAgoText(0)).toBe("dziś");
  });
});

describe("newColumnSection", () => {
  it("dzieli na zespół, pięć pierwszych i resztę", () => {
    expect(newColumnSection(undefined)).toBe("team");
    expect(newColumnSection(1)).toBe("call_first");
    expect(newColumnSection(5)).toBe("call_first");
    expect(newColumnSection(6)).toBe("rest");
  });
});
