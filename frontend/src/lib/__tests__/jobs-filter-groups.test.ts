import { describe, expect, it } from "vitest";

import {
  deadlineSummary,
  jobsActiveFilterCount,
  namesSummary,
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

describe("whoSummary", () => {
  it("zalogowana osoba to „ja”, request bez osoby to „nikt”", () => {
    expect(whoSummary([1], false, 1, nameOf)).toBe("ja");
    expect(whoSummary([1, 2], true, 1, nameOf)).toBe("ja, Piotr Mazur, nikt");
    expect(whoSummary([], true, 1, nameOf)).toBe("nikt");
    expect(whoSummary([], false, 1, nameOf)).toBeNull();
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
});
