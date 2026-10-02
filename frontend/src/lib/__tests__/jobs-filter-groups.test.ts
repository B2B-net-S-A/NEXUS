import { describe, expect, it } from "vitest";

import {
  deadlineSummary,
  jobsActiveFilterCount,
  namesSummary,
  openedSummary,
  prioritySummary,
  whoSummary,
} from "@/lib/jobs-filter-groups";

const names: Record<number, string> = { 1: "Anna Kowal", 2: "Piotr Mazur", 3: "Marta Nowicka" };
const nameOf = (id: number) => names[id];

describe("deadlineSummary", () => {
  it("brak filtra to brak podsumowania", () => {
    expect(deadlineSummary("any")).toBeNull();
  });
  it("preset niesie swoją nazwę", () => {
    expect(deadlineSummary("next7")).toBe("najbliższe 7 dni");
  });
  it("zakres pokazuje daty, a pusty zakres — samą nazwę", () => {
    expect(deadlineSummary("range", { from: "2026-10-01", to: "2026-10-31" })).toBe("01.10–31.10");
    expect(deadlineSummary("range", { to: "2026-10-31" })).toBe("do 31.10");
    expect(deadlineSummary("range", {})).toBe("zakres dat");
  });
});

describe("namesSummary", () => {
  it("jedna, dwie i więcej pozycji", () => {
    expect(namesSummary([1], nameOf)).toBe("Anna Kowal");
    expect(namesSummary([1, 2], nameOf)).toBe("Anna Kowal, Piotr Mazur");
    expect(namesSummary([1, 2, 3], nameOf)).toBe("Anna Kowal i 2 więcej");
  });
  it("nie zgaduje nazwy, której jeszcze nie znamy", () => {
    expect(namesSummary([1, 99], nameOf)).toBeNull();
  });
});

describe("whoSummary — filtr „Rekruter”", () => {
  it("zalogowana osoba to „ja”, rekrutacja bez Rekrutera to „bez rekrutera”", () => {
    expect(whoSummary([1], false, 1, nameOf)).toBe("ja");
    expect(whoSummary([1, 2], true, 1, nameOf)).toBe("ja, Piotr Mazur, bez rekrutera");
    expect(whoSummary([], true, 1, nameOf)).toBe("bez rekrutera");
    expect(whoSummary([], false, 1, nameOf)).toBeNull();
  });
});

describe("prioritySummary", () => {
  it("krótkie nazwy w kolejności ekranu, brak wyboru to brak podsumowania", () => {
    expect(prioritySummary([])).toBeNull();
    expect(prioritySummary(["p1"])).toBe("P1");
    expect(prioritySummary(["accepting", "p1"])).toBe("P1, Przyjmujemy");
    expect(prioritySummary(["p2", "accepting", "p1"])).toBe("P1, P2, Przyjmujemy");
  });
});

describe("openedSummary — „Data otwarcia”", () => {
  it("pokazuje daty, które naprawdę filtrują", () => {
    expect(openedSummary({})).toBeNull();
    expect(openedSummary({ from: "2026-09-01", to: "2026-09-30" })).toBe("01.09–30.09");
    expect(openedSummary({ from: "2026-09-01" })).toBe("od 01.09");
    expect(openedSummary({ to: "2026-09-30" })).toBe("do 30.09");
  });
  it("odwrócony zakres i niedokończona data nie udają ustawionego filtra", () => {
    expect(openedSummary({ from: "2026-09-30", to: "2026-09-01" })).toBe("popraw zakres");
    expect(openedSummary({ from: "0002-09-01" })).toBe("niepełna data");
    // Druga, poprawna granica filtruje mimo niedokończonej pierwszej.
    expect(openedSummary({ from: "0002-09-01", to: "2026-09-30" })).toBe("do 30.09");
  });
});

describe("jobsActiveFilterCount", () => {
  const empty = {
    stages: [],
    clientIds: [],
    deliveryLeadIds: [],
    workedBy: [],
    nobodyWorking: false,
    ccIds: [],
    deadline: "any" as const,
    sent: "any" as const,
    priorityLevels: [],
    openedRange: {},
  };
  it("pusty pasek to zero", () => {
    expect(jobsActiveFilterCount(empty)).toBe(0);
  });
  it("każdy przycisk liczy się raz, niezależnie od liczby wybranych pozycji", () => {
    expect(
      jobsActiveFilterCount({
        ...empty,
        stages: ["searching", "champion"],
        clientIds: [3, 7],
        workedBy: [1],
        nobodyWorking: true,
        deadline: "overdue",
      }),
    ).toBe(4);
  });
  it("priorytet i data otwarcia liczą się po razie", () => {
    expect(
      jobsActiveFilterCount({
        ...empty,
        priorityLevels: ["p1", "accepting"],
        openedRange: { from: "2026-09-01", to: "2026-09-30" },
      }),
    ).toBe(2);
    // Sama data „od” (także odwrócony zakres) to ustawiony filtr — da się go wyczyścić.
    expect(jobsActiveFilterCount({ ...empty, openedRange: { from: "2026-09-01" } })).toBe(1);
  });
});
