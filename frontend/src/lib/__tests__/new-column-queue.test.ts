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

  it("co 5. miejsce oddaje najlepszej osobie bez procesu i oznacza tylko przeskok", () => {
    const fresh = (id: number, score: number) =>
      system(id, score, { entry_autofill: { score, decided: false, cautions: [], fresh: true } });
    const known = (id: number, score: number) =>
      system(id, score, {
        entry_autofill: {
          score,
          decided: false,
          cautions: [],
          known: { points: 10, client_points: 6, note_points: 4, verified_at_client: 1, last_note_days: 3 },
        },
      });
    const { items, ranks, freshSlots } = orderNewColumn([
      known(1, 80),
      known(2, 79),
      known(3, 78),
      known(4, 77),
      known(5, 76),
      known(6, 75),
      fresh(7, 60),
      fresh(8, 70),
    ]);
    expect(items.map((i) => i.id)).toEqual([1, 2, 3, 4, 8, 5, 6, 7]);
    expect(ranks.get(8)).toBe(5);
    expect([...freshSlots]).toEqual([8]);
  });

  it("osoba bez procesu, która i tak stoi na swoim miejscu, nie dostaje napisu", () => {
    const fresh = (id: number, score: number) =>
      system(id, score, { entry_autofill: { score, decided: false, cautions: [], fresh: true } });
    const { items, freshSlots } = orderNewColumn([
      fresh(1, 90),
      fresh(2, 89),
      fresh(3, 88),
      fresh(4, 87),
      fresh(5, 86),
    ]);
    expect(items.map((i) => i.id)).toEqual([1, 2, 3, 4, 5]);
    expect(freshSlots.size).toBe(0);
  });

  it("osoba bez procesu z ostrzeżeniem albo brakiem krytycznej nie przeskakuje", () => {
    const caution = system(6, 95, {
      entry_autofill: { score: 95, decided: false, cautions: [{ key: "budget" }], fresh: true },
    });
    const gap = system(7, 94, { entry_autofill: { score: 94, decided: false, cautions: [], fresh: true } });
    const { items, freshSlots } = orderNewColumn(
      [system(1, 80), system(2, 79), system(3, 78), system(4, 77), system(5, 76), caution, gap],
      new Map([[70, ["angular"]]]),
    );
    expect(items.map((i) => i.id)).toEqual([1, 2, 3, 4, 5, 6, 7]);
    expect(freshSlots.size).toBe(0);
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
