import { afterEach, describe, expect, it } from "vitest";

import {
  JOB_MEMORY_LIMIT,
  JOB_MEMORY_TTL_MS,
  RECENT_LIMIT,
  clearSearchMemory,
  pushRecentSearch,
  readJobSearch,
  readListSearch,
  readRecentSearches,
  recentKeywords,
  writeJobSearch,
  writeListSearch,
} from "@/lib/search-memory";

const entry = (query: string, keywords: string[] = []) => ({
  kind: "list" as const,
  jobId: null,
  label: query,
  query,
  keywords,
  total: null,
});

afterEach(() => {
  clearSearchMemory();
  window.localStorage.clear();
  window.sessionStorage.clear();
});

describe("search-memory", () => {
  it("ostatnie wyszukiwanie listy: nowe filtry zerują przewinięcie i wyróżnienie", () => {
    writeListSearch({ query: "q_all=Java" });
    writeListSearch({ query: "q_all=Java", scrollTop: 640, lastOpenedId: 12 });
    expect(readListSearch()).toMatchObject({ query: "q_all=Java", scrollTop: 640, lastOpenedId: 12 });
    writeListSearch({ query: "q_all=Kafka" });
    expect(readListSearch()).toMatchObject({ query: "q_all=Kafka", scrollTop: 0, lastOpenedId: null });
  });

  it("uszkodzony zapis nie wywraca odczytu", () => {
    window.sessionStorage.setItem("nexus:search-memory:list", "{nie json");
    expect(readListSearch()).toBeNull();
    window.localStorage.setItem("nexus:search-memory:recent:7", '[{"kind":"x"}, 5]');
    expect(readRecentSearches(7)).toEqual([]);
  });

  it("ostatnie wyszukiwania: bez powtórzeń, najnowsze pierwsze, najwyżej 10", () => {
    for (let i = 0; i < RECENT_LIMIT + 3; i += 1) pushRecentSearch(7, entry(`q=${i}`));
    pushRecentSearch(7, entry("q=5"));
    const rows = readRecentSearches(7);
    expect(rows).toHaveLength(RECENT_LIMIT);
    expect(rows[0].query).toBe("q=5");
    expect(rows.filter((r) => r.query === "q=5")).toHaveLength(1);
    // Inny użytkownik ma własną listę.
    expect(readRecentSearches(8)).toEqual([]);
    expect(readRecentSearches(null)).toEqual([]);
  });

  it("ostatnio używane słowa: najnowsze pierwsze, bez powtórzeń", () => {
    pushRecentSearch(7, entry("a", ["Java", "Kafka"]));
    pushRecentSearch(7, entry("b", ["kafka", "Spring Boot"]));
    expect(recentKeywords(7)).toEqual(["kafka", "Spring Boot", "Java"]);
  });

  it("wyszukiwanie rekrutacji wygasa po 30 dniach i trzyma najwyżej 50 rekrutacji", () => {
    const now = 1_800_000_000_000;
    writeJobSearch(7, 1, { q: "java" }, now);
    expect(readJobSearch(7, 1, now + 1000)?.request).toEqual({ q: "java" });
    expect(readJobSearch(7, 1, now + JOB_MEMORY_TTL_MS + 1)).toBeNull();
    for (let id = 2; id <= JOB_MEMORY_LIMIT + 5; id += 1) writeJobSearch(7, id, { q: String(id) }, now + id);
    expect(readJobSearch(7, 1, now + 100)).toBeNull();
    expect(readJobSearch(7, JOB_MEMORY_LIMIT + 5, now + 100)?.request).toEqual({
      q: String(JOB_MEMORY_LIMIT + 5),
    });
  });

  it("wylogowanie czyści całą pamięć wyszukiwań", () => {
    writeListSearch({ query: "q=java" });
    pushRecentSearch(7, entry("q=java"));
    window.localStorage.setItem("inny-klucz", "zostaje");
    clearSearchMemory();
    expect(readListSearch()).toBeNull();
    expect(readRecentSearches(7)).toEqual([]);
    expect(window.localStorage.getItem("inny-klucz")).toBe("zostaje");
  });
});
