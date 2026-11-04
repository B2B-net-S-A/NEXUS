import { describe, expect, it } from "vitest";

import {
  breakdownReasonChips,
  proposalReasonChips,
  reasonChips,
  shortChipLabel,
  withKeptRows,
} from "../reason-chips";

describe("reasonChips — powód w wierszu", () => {
  it("najpierw po jednym z każdego rodzaju, najwyżej trzy; reszta idzie do „+N”", () => {
    expect(
      reasonChips({ met: ["Java", "Spring", "SQL"], gap: ["Kafka"], ask: ["5 lat w bankowości"] }),
    ).toEqual({
      shown: [
        { tone: "met", label: "Java" },
        { tone: "gap", label: "Kafka" },
        { tone: "ask", label: "5 lat w bankowości" },
      ],
      hidden: [
        { tone: "met", label: "Spring" },
        { tone: "met", label: "SQL" },
      ],
    });
  });

  it("brak jednego rodzaju = kolejne pozycje pozostałych", () => {
    expect(reasonChips({ met: ["Java", "Spring", "SQL"], gap: ["Kafka"] })).toEqual({
      shown: [
        { tone: "met", label: "Java" },
        { tone: "gap", label: "Kafka" },
        { tone: "met", label: "Spring" },
      ],
      hidden: [{ tone: "met", label: "SQL" }],
    });
    expect(reasonChips({})).toEqual({ shown: [], hidden: [] });
  });

  it("ta sama etykieta raz, puste pomijane", () => {
    expect(reasonChips({ met: ["Java", " "], gap: ["java"], ask: ["Java"] })).toEqual({
      shown: [{ tone: "met", label: "Java" }],
      hidden: [],
    });
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
    ).toEqual({
      shown: [
        { tone: "met", label: "Angular" },
        { tone: "ask", label: "TypeScript" },
        { tone: "met", label: "Scala" },
      ],
      hidden: [{ tone: "ask", label: "5 lat w finansach" }],
    });
    expect(proposalReasonChips(undefined)).toEqual({ shown: [], hidden: [] });
  });

  it("technologia sprzed ponad 3 lat = „zapytaj” z rokiem", () => {
    expect(
      proposalReasonChips([
        { label: "java", level: "must", status: "met", verified: false },
        { label: "angular", level: "must", status: "unknown", verified: false, lastUsedYear: 2020 },
      ]).shown,
    ).toEqual([
      { tone: "met", label: "java" },
      { tone: "ask", label: "angular · 2020" },
    ]);
  });

  it("wyszukiwanie: rozbicie dopasowania i must-have zdaniem", () => {
    expect(
      breakdownReasonChips({ matching_must: ["Angular"], gap_must: ["TypeScript"] }, ["5 lat w finansach"]).shown,
    ).toEqual([
      { tone: "met", label: "Angular" },
      { tone: "gap", label: "TypeScript" },
      { tone: "ask", label: "5 lat w finansach" },
    ]);
    expect(breakdownReasonChips(null, [])).toEqual({ shown: [], hidden: [] });
  });

  it("etykieta do 18 znaków, dłuższa skrócona wielokropkiem", () => {
    expect(shortChipLabel("TypeScript")).toBe("TypeScript");
    expect(shortChipLabel("Doświadczenie w KYC")).toBe("Doświadczenie w K…");
    expect(shortChipLabel("Minimum 5 lat doświadczenia w projektach")).toBe("Minimum 5 lat doś…");
    expect([...shortChipLabel("Minimum 5 lat doświadczenia w projektach")]).toHaveLength(18);
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
