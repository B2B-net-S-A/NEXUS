import { readFileSync } from "node:fs";
import { join, resolve } from "node:path";

import { describe, expect, it } from "vitest";

import {
  PRIORITY_LEVELS,
  PRIORITY_LEVEL_LABEL,
  PRIORITY_LEVEL_OPTIONS,
  PRIORITY_LEVEL_SHORT_LABEL,
  isPriorityLevel,
  priorityLevelOf,
  rawPriorityForLevel,
  type RawJobPriority,
} from "@/lib/request-priority";

describe("priorityLevelOf", () => {
  it("poziom z serwera wygrywa z surową wartością kolumny", () => {
    expect(priorityLevelOf({ priority_level: "accepting", priority: "urgent" })).toBe(
      "accepting",
    );
    expect(priorityLevelOf({ priority_level: "p1", priority: "low" })).toBe("p1");
    expect(priorityLevelOf({ priority_level: "p2" })).toBe("p2");
  });

  it("bez poziomu liczy go z kolumny: urgent i high to P1, low to „Przyjmujemy”", () => {
    expect(priorityLevelOf({ priority: "urgent" })).toBe("p1");
    expect(priorityLevelOf({ priority: "high" })).toBe("p1");
    expect(priorityLevelOf({ priority: "medium" })).toBe("p2");
    expect(priorityLevelOf({ priority: "low" })).toBe("accepting");
  });

  it("brak danych i nieznana wartość to P2 — stan domyślny", () => {
    expect(priorityLevelOf(null)).toBe("p2");
    expect(priorityLevelOf(undefined)).toBe("p2");
    expect(priorityLevelOf({})).toBe("p2");
    expect(priorityLevelOf({ priority: null })).toBe("p2");
    expect(priorityLevelOf({ priority: "" })).toBe("p2");
    expect(priorityLevelOf({ priority: "critical" })).toBe("p2");
    // Nazwa z prototypu obiektu nie może udawać poziomu.
    expect(priorityLevelOf({ priority: "constructor" })).toBe("p2");
  });

  it("nieznany poziom z serwera nie przechodzi dalej — liczy się kolumna", () => {
    expect(priorityLevelOf({ priority_level: "p0", priority: "urgent" })).toBe("p1");
    expect(priorityLevelOf({ priority_level: "", priority: "low" })).toBe("accepting");
    expect(priorityLevelOf({ priority_level: null, priority: "medium" })).toBe("p2");
  });

  it("wielkość liter i spacje w surowej wartości nie zmieniają poziomu", () => {
    expect(priorityLevelOf({ priority: " URGENT " })).toBe("p1");
    expect(priorityLevelOf({ priority: "Low" })).toBe("accepting");
  });
});

describe("rawPriorityForLevel", () => {
  it("zapisuje urgent / medium / low", () => {
    expect(rawPriorityForLevel("p1")).toBe("urgent");
    expect(rawPriorityForLevel("p2")).toBe("medium");
    expect(rawPriorityForLevel("accepting")).toBe("low");
  });

  it("zapisana wartość wraca jako ten sam poziom", () => {
    for (const level of PRIORITY_LEVELS) {
      expect(priorityLevelOf({ priority: rawPriorityForLevel(level) })).toBe(level);
    }
  });
});

describe("etykiety", () => {
  it("pełne i krótkie nazwy trzech poziomów", () => {
    expect(PRIORITY_LEVELS).toEqual(["p1", "p2", "accepting"]);
    expect(PRIORITY_LEVEL_LABEL).toEqual({
      p1: "P1 Pilne",
      p2: "P2 Standard",
      accepting: "Przyjmujemy kandydatów",
    });
    expect(PRIORITY_LEVEL_SHORT_LABEL).toEqual({
      p1: "P1",
      p2: "P2",
      accepting: "Przyjmujemy",
    });
  });

  it("opcje wyboru idą w kolejności poziomów", () => {
    expect(PRIORITY_LEVEL_OPTIONS).toEqual([
      { value: "p1", label: "P1 Pilne" },
      { value: "p2", label: "P2 Standard" },
      { value: "accepting", label: "Przyjmujemy kandydatów" },
    ]);
  });

  it("isPriorityLevel przyjmuje tylko trzy poziomy", () => {
    expect(isPriorityLevel("p1")).toBe(true);
    expect(isPriorityLevel("accepting")).toBe(true);
    expect(isPriorityLevel("urgent")).toBe(false);
    expect(isPriorityLevel(null)).toBe(false);
    expect(isPriorityLevel(1)).toBe(false);
  });
});

// Reguła ma dwa lustra: tę funkcję i `level_of` w backendzie. Test czyta
// słownik z Pythona, żeby zmiana po jednej stronie nie przeszła po cichu.
describe("lustro backend/app/services/job_priority.py", () => {
  const source = readFileSync(
    join(resolve(process.cwd(), ".."), "backend/app/services/job_priority.py"),
    "utf8",
  );
  const block = /_VALUES_BY_LEVEL[^=]*=\s*\{([\s\S]*?)\n\}/.exec(source)?.[1] ?? "";
  const backend = [...block.matchAll(/"(\w+)":\s*\(([^)]*)\)/g)].map(
    ([, level, values]) => ({
      level,
      values: [...values.matchAll(/JobPriority\.(\w+)/g)].map((m) => m[1]),
    }),
  );

  it("backend zna te same trzy poziomy", () => {
    expect(backend.map((entry) => entry.level)).toEqual([...PRIORITY_LEVELS]);
  });

  it("każda wartość kolumny daje po obu stronach ten sam poziom", () => {
    const checked: string[] = [];
    for (const { level, values } of backend) {
      for (const value of values) {
        expect(priorityLevelOf({ priority: value })).toBe(level);
        checked.push(value);
      }
    }
    expect(checked.sort()).toEqual(["high", "low", "medium", "urgent"]);
  });

  it("front zapisuje wartość, którą backend czyta jako ten sam poziom", () => {
    for (const { level, values } of backend) {
      const raw: RawJobPriority = rawPriorityForLevel(
        level as (typeof PRIORITY_LEVELS)[number],
      );
      expect(values).toContain(raw);
    }
  });
});
