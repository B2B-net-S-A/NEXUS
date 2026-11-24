import { describe, expect, it } from "vitest";

import {
  EMPTY_FILTERS,
  filterQuestions,
  managerOptions,
  questionsAsText,
  type BankQuestion,
} from "@/lib/question-bank";

function q(over: Partial<BankQuestion>): BankQuestion {
  return {
    id: 1,
    text: "Czy zna Pan SQL?",
    client_id: 1,
    client_name: "Klient A",
    source: "debrief",
    roles: [{ job_id: 10, title: "Analityk danych", job_number: "100", manager: "Manager A" }],
    managers: ["Manager A"],
    asked_count: 1,
    last_asked_at: "2026-11-23T12:00:00Z",
    ...over,
  };
}

const rows = [
  q({ id: 1 }),
  q({ id: 2, text: "Doświadczenie z Excelem?", client_id: 2, client_name: "Klient B", managers: ["Manager B"], roles: [{ job_id: 20, title: "Tester", job_number: null, manager: "Manager B" }] }),
  q({ id: 3, text: "Pytanie z arkusza", source: "archive", roles: [], managers: [], asked_count: 0 }),
];

describe("filterQuestions", () => {
  it("bez filtrów zwraca wszystko", () => {
    expect(filterQuestions(rows, EMPTY_FILTERS)).toHaveLength(3);
  });

  it("filtruje po kliencie, managerze i źródle", () => {
    expect(filterQuestions(rows, { ...EMPTY_FILTERS, clientId: 2 }).map((r) => r.id)).toEqual([2]);
    expect(filterQuestions(rows, { ...EMPTY_FILTERS, manager: "Manager A" }).map((r) => r.id)).toEqual([1]);
    expect(filterQuestions(rows, { ...EMPTY_FILTERS, source: "archive" }).map((r) => r.id)).toEqual([3]);
  });

  it("stanowisko i treść bez wielkości liter i polskich znaków; numer też trafia", () => {
    expect(filterQuestions(rows, { ...EMPTY_FILTERS, role: "ANALITYK" }).map((r) => r.id)).toEqual([1]);
    expect(filterQuestions(rows, { ...EMPTY_FILTERS, role: "100" }).map((r) => r.id)).toEqual([1]);
    expect(filterQuestions(rows, { ...EMPTY_FILTERS, text: "doswiadczenie" }).map((r) => r.id)).toEqual([2]);
  });

  it("pytanie bez rekrutacji nie przechodzi filtra stanowiska", () => {
    expect(filterQuestions(rows, { ...EMPTY_FILTERS, role: "arkusz" })).toEqual([]);
  });
});

describe("managerOptions i questionsAsText", () => {
  it("managerowie tylko wybranego klienta", () => {
    expect(managerOptions(rows, 2)).toEqual(["Manager B"]);
    expect(managerOptions(rows, null)).toEqual(["Manager A", "Manager B"]);
  });

  it("tekst do prepu grupuje po stanowisku", () => {
    expect(questionsAsText([rows[0], rows[2]])).toBe(
      "100 · Analityk danych\n- Czy zna Pan SQL?\n\nBez stanowiska\n- Pytanie z arkusza",
    );
  });
});
