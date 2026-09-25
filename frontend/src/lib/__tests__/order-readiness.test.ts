import { describe, expect, it } from "vitest";

import {
  buildReadinessChecklist,
  parseBudgetInput,
  READINESS_CHAMPION_ANCHOR,
  READINESS_MESSAGES,
  readinessKeyFor,
} from "@/lib/order-readiness";

describe("order-readiness", () => {
  it("rozpoznaje zdania bramki serwera, a obce zostawia bez klucza", () => {
    expect(readinessKeyFor(READINESS_MESSAGES.budget)).toBe("budget");
    expect(readinessKeyFor(` ${READINESS_MESSAGES.work_mode} `)).toBe("work_mode");
    expect(readinessKeyFor("Konflikt pól Championa.")).toBeNull();
  });

  it("dni i miasto biura liczą się tylko przy hybrydzie/biurze", () => {
    // 7 podstawowych + wymagania do wyszukiwania (25.09.2026).
    expect(buildReadinessChecklist([], "remote").total).toBe(8);
    expect(buildReadinessChecklist([], "hybrid").total).toBe(10);
    // Serwer pyta o dni → pozycje biura wchodzą niezależnie od kolumny.
    const withOffice = buildReadinessChecklist([READINESS_MESSAGES.office_days], null);
    expect(withOffice.total).toBe(10);
    expect(withOffice.done).toContain("office_city");
    expect(withOffice.done).not.toContain("office_days");
  });

  it("zdanie spoza lustra jest brakiem i powiększa mianownik", () => {
    const checklist = buildReadinessChecklist(["Coś innego."], "remote");
    expect(checklist.missing).toEqual([{ key: null, label: "Coś innego.", message: "Coś innego." }]);
    expect(checklist.total).toBe(9);
    expect(checklist.doneCount).toBe(8);
  });

  it("budżet: liczba w (0, 2000], przecinek jak kropka", () => {
    expect(parseBudgetInput("150")).toEqual({ value: 150 });
    expect(parseBudgetInput("152,5")).toEqual({ value: 152.5 });
    expect(parseBudgetInput("")).toHaveProperty("error");
    expect(parseBudgetInput("0")).toHaveProperty("error");
    expect(parseBudgetInput("2001")).toHaveProperty("error");
    expect(parseBudgetInput("150 zł")).toHaveProperty("error");
  });

  it("brak wymagań do wyszukiwania prowadzi do ich karty w Championie", () => {
    const checklist = buildReadinessChecklist([READINESS_MESSAGES.search], "remote");
    expect(checklist.missing).toEqual([
      {
        key: "search",
        label: "Wymagania do wyszukiwania",
        message: READINESS_MESSAGES.search,
      },
    ]);
    expect(READINESS_CHAMPION_ANCHOR.search).toBe("champion-search-requirements");
  });
});
