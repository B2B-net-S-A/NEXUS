import { describe, expect, it } from "vitest";

import {
  breakdownReasonChips,
  proposalReasonChips,
  reasonChips,
  withKeptRows,
} from "../reason-chips";

describe("reasonChips — powód w wierszu", () => {
  it("najpierw po jednym z każdego rodzaju, najwyżej trzy", () => {
    expect(
      reasonChips({ met: ["Java", "Spring", "SQL"], gap: ["Kafka"], ask: ["5 lat w bankowości"] }),
    ).toEqual([
      { tone: "met", label: "Java" },
      { tone: "gap", label: "Kafka" },
      { tone: "ask", label: "5 lat w bankowości" },
    ]);
  });

  it("brak jednego rodzaju = kolejne pozycje pozostałych", () => {
    expect(reasonChips({ met: ["Java", "Spring", "SQL"], gap: ["Kafka"] })).toEqual([
      { tone: "met", label: "Java" },
      { tone: "gap", label: "Kafka" },
      { tone: "met", label: "Spring" },
    ]);
    expect(reasonChips({})).toEqual([]);
  });

  it("ta sama etykieta raz, puste pomijane", () => {
    expect(reasonChips({ met: ["Java", " "], gap: ["java"], ask: ["Java"] })).toEqual([
      { tone: "met", label: "Java" },
    ]);
  });

  it("propozycja: must-have przed mile widzianymi, nieznane = „zapytaj”", () => {
    expect(
      proposalReasonChips(
        [
          { label: "Scala", level: "nice", status: "met", verified: false },
          { label: "Angular", level: "must", status: "met", verified: false },
          { label: "RxJS", level: "nice", status: "not_met", verified: false },
          { label: "TypeScript", level: "must", status: "unknown", verified: false },
        ],
        ["5 lat w finansach"],
      ),
    ).toEqual([
      { tone: "met", label: "Angular" },
      { tone: "ask", label: "TypeScript" },
      { tone: "met", label: "Scala" },
    ]);
    expect(proposalReasonChips(undefined)).toEqual([]);
  });

  it("wyszukiwanie: rozbicie dopasowania i must-have zdaniem", () => {
    expect(
      breakdownReasonChips({ matching_must: ["Angular"], gap_must: ["TypeScript"] }, ["5 lat w finansach"]),
    ).toEqual([
      { tone: "met", label: "Angular" },
      { tone: "gap", label: "TypeScript" },
      { tone: "ask", label: "5 lat w finansach" },
    ]);
    expect(breakdownReasonChips(null, [])).toEqual([]);
  });
});

describe("withKeptRows — dodani zostają w swoim miejscu", () => {
  const id = (v: { id: number }) => v.id;
  it("wstawia brakujące w zapamiętane miejsce, żywy wiersz wygrywa", () => {
    const live = [{ id: 1 }, { id: 3 }];
    const kept = new Map([
      [2, { value: { id: 2 }, index: 1 }],
      [3, { value: { id: 3, stale: true } as { id: number }, index: 2 }],
      [9, { value: { id: 9 }, index: 40 }],
    ]);
    expect(withKeptRows(live, kept, id)).toEqual([{ id: 1 }, { id: 2 }, { id: 3 }, { id: 9 }]);
    expect(withKeptRows(live, new Map(), id)).toEqual(live);
  });
});
