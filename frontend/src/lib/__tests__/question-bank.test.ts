import { describe, expect, it } from "vitest";

import {
  EMPTY_FILTERS,
  clientOptions,
  filterPositions,
  groupByPosition,
  isSectionHeading,
  managerOptions,
  positionAsText,
  questionCount,
  type BankQuestion,
} from "@/lib/question-bank";

function q(over: Partial<BankQuestion>): BankQuestion {
  return {
    id: 1,
    text: "Czy zna Pan SQL?",
    client_id: 1,
    client_name: "Klient A",
    source: "debrief",
    roles: [{ job_id: 10, title: "Analityk danych · SQL · 3+ lata", job_number: "100", manager: "Manager A" }],
    managers: ["Manager A"],
    asked_count: 1,
    last_asked_at: "2026-11-23T12:00:00Z",
    answer: null,
    answer_source: null,
    ...over,
  };
}

const rows = [
  q({ id: 1, answer: "Tak, SELECT i JOIN.", answer_source: "ai" }),
  q({ id: 4, text: "Bazy danych", answer_source: "none" }),
  q({
    id: 2,
    text: "Doświadczenie z Excelem?",
    client_id: 2,
    client_name: "Klient B",
    managers: ["Manager B"],
    roles: [{ job_id: 20, title: "Tester", job_number: null, manager: "Manager B" }],
    last_asked_at: "2026-11-24T12:00:00Z",
  }),
  q({ id: 3, text: "Pytanie z arkusza?", source: "archive", roles: [], managers: [], asked_count: 0, last_asked_at: null }),
];

describe("groupByPosition", () => {
  const positions = groupByPosition(rows);

  it("jedna pozycja na rekrutację, archiwum Excela na kliencie i na końcu", () => {
    expect(positions.map((p) => p.key)).toEqual(["20", "10", "excel-1"]);
  });

  it("nazwa stanowiska bez dopisku z technologiami", () => {
    const analityk = positions.find((p) => p.key === "10")!;
    expect(analityk.name).toBe("Analityk danych");
    expect(analityk.techLine).toBe("SQL · 3+ lata");
    expect(analityk.jobNumber).toBe("100");
  });

  it("pytanie z dwóch rekrutacji jest w obu", () => {
    const shared = q({
      id: 9,
      roles: [
        { job_id: 10, title: "Analityk", job_number: null, manager: null },
        { job_id: 11, title: "Analityk 2", job_number: null, manager: null },
      ],
    });
    expect(groupByPosition([shared]).map((p) => p.key).sort()).toEqual(["10", "11"]);
  });

  it("śródtytuł z debriefu nie liczy się do pytań", () => {
    expect(questionCount(positions.find((p) => p.key === "10")!)).toBe(1);
  });
});

describe("isSectionHeading", () => {
  it("nagłówek to tylko wpis oznaczony przez nocny bieg, nie krótki tekst", () => {
    expect(isSectionHeading({ answer_source: "none" })).toBe(true);
    expect(isSectionHeading({ answer_source: null })).toBe(false);
    expect(isSectionHeading({ answer_source: "ai" })).toBe(false);
  });

  it("krótkie pytanie bez pytajnika liczy się jako pytanie", () => {
    const p = groupByPosition([q({ id: 7, text: "Playwright" })])[0];
    expect(questionCount(p)).toBe(1);
  });
});

describe("filterPositions", () => {
  const positions = groupByPosition(rows);

  it("bez filtrów zwraca wszystko", () => {
    expect(filterPositions(positions, EMPTY_FILTERS)).toHaveLength(3);
  });

  it("klient i manager", () => {
    expect(filterPositions(positions, { ...EMPTY_FILTERS, clientId: 2 }).map((p) => p.key)).toEqual(["20"]);
    expect(filterPositions(positions, { ...EMPTY_FILTERS, manager: "Manager A" }).map((p) => p.key)).toEqual(["10"]);
  });

  it("stanowisko po nazwie i numerze bez wielkości liter i ogonków; treść pytania", () => {
    expect(filterPositions(positions, { ...EMPTY_FILTERS, search: "ANALITYK" }).map((p) => p.key)).toEqual(["10"]);
    expect(filterPositions(positions, { ...EMPTY_FILTERS, search: "100" }).map((p) => p.key)).toEqual(["10"]);
    expect(filterPositions(positions, { ...EMPTY_FILTERS, text: "doswiadczenie" }).map((p) => p.key)).toEqual(["20"]);
  });
});

describe("opcje filtrów i tekst do schowka", () => {
  const positions = groupByPosition(rows);

  it("klienci po liczbie stanowisk, managerowie tylko wybranego klienta", () => {
    expect(clientOptions(positions).map((c) => [c.id, c.count])).toEqual([
      [1, 2],
      [2, 1],
    ]);
    expect(managerOptions(positions, 2)).toEqual(["Manager B"]);
    expect(managerOptions(positions, null)).toEqual(["Manager A", "Manager B"]);
  });

  it("tekst ze śródtytułem, numeracją i odpowiedzią tylko na życzenie", () => {
    const analityk = positions.find((p) => p.key === "10")!;
    expect(positionAsText(analityk, false)).toBe("100 · Analityk danych · Klient A\n1. Czy zna Pan SQL?\n\nBAZY DANYCH");
    expect(positionAsText(analityk, true)).toContain("   Odpowiedź: Tak, SELECT i JOIN.");
  });
});
