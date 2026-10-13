import { describe, expect, it } from "vitest";

import { dayBaselineRank } from "@/components/v2/league/league-rank-memory";

function memoryStorage(): Storage {
  const data = new Map<string, string>();
  return {
    get length() {
      return data.size;
    },
    clear: () => data.clear(),
    getItem: (key) => data.get(key) ?? null,
    key: (index) => [...data.keys()][index] ?? null,
    removeItem: (key) => void data.delete(key),
    setItem: (key, value) => void data.set(key, String(value)),
  };
}

const LEAGUE = "quarterly_champions_recruiter:Q4 2026";

describe("dayBaselineRank", () => {
  it("pierwszy widok dnia zapisuje miejsce, kolejne je zwracają", () => {
    const storage = memoryStorage();
    expect(dayBaselineRank(storage, 7, LEAGUE, 6, "2026-10-13")).toBe(6);
    expect(dayBaselineRank(storage, 7, LEAGUE, 4, "2026-10-13")).toBe(6);
  });

  it("nowy dzień i nowy kwartał zaczynają od bieżącego miejsca", () => {
    const storage = memoryStorage();
    dayBaselineRank(storage, 7, LEAGUE, 6, "2026-10-13");
    expect(dayBaselineRank(storage, 7, LEAGUE, 4, "2026-10-14")).toBe(4);
    expect(dayBaselineRank(storage, 7, "quarterly_champions_recruiter:Q1 2027", 9, "2026-10-14")).toBe(9);
  });

  it("każda osoba ma własny wpis", () => {
    const storage = memoryStorage();
    dayBaselineRank(storage, 7, LEAGUE, 6, "2026-10-13");
    expect(dayBaselineRank(storage, 8, LEAGUE, 2, "2026-10-13")).toBe(2);
  });

  it("bez pamięci albo z zepsutym wpisem — bez wyjątku", () => {
    expect(dayBaselineRank(null, 7, LEAGUE, 6, "2026-10-13")).toBeNull();
    const storage = memoryStorage();
    storage.setItem("nexus:league-rank:7", "{nie-json");
    expect(dayBaselineRank(storage, 7, LEAGUE, 5, "2026-10-13")).toBe(5);
    const throwing = { ...memoryStorage(), setItem: () => { throw new Error("pełna"); } } as Storage;
    expect(dayBaselineRank(throwing, 7, LEAGUE, 5, "2026-10-13")).toBe(5);
  });
});
