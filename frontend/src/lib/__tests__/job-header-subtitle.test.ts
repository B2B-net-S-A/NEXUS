/**
 * Skróty nazwiska i terminu (`lib/job-header-subtitle.ts`).
 */

import { describe, expect, it } from "vitest";

import { formatDeadlineShort, shortenPersonName } from "@/lib/job-header-subtitle";

describe("shortenPersonName", () => {
  it("skraca nazwisko do inicjału, imię zostaje w całości", () => {
    expect(shortenPersonName("Marta Kowalska")).toBe("Marta K.");
    expect(shortenPersonName("Anna Nowak-Kowalska")).toBe("Anna N.");
    expect(shortenPersonName("  Jan   Maria  Rokita ")).toBe("Jan Maria R.");
  });

  it("jednoczłonowe zostaje bez zmian, puste daje null", () => {
    expect(shortenPersonName("Madonna")).toBe("Madonna");
    expect(shortenPersonName("")).toBeNull();
    expect(shortenPersonName(null)).toBeNull();
    expect(shortenPersonName(undefined)).toBeNull();
  });
});

describe("formatDeadlineShort", () => {
  it("2026-09-30 → 30.09; rok pomijamy", () => {
    expect(formatDeadlineShort("2026-09-30")).toBe("30.09");
    expect(formatDeadlineShort("2026-09-30T12:00:00Z")).toBe("30.09");
  });

  it("brak albo śmieć daje null, nie „Invalid Date”", () => {
    expect(formatDeadlineShort(null)).toBeNull();
    expect(formatDeadlineShort("kiedyś")).toBeNull();
  });
});
