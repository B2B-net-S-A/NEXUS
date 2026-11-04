import { afterEach, describe, expect, it } from "vitest";

import {
  JOB_MEMORY_LIMIT,
  JOB_MEMORY_TTL_MS,
  RECENT_LIMIT,
  clearSearchMemory,
  markCvSeen,
  pushRecentSearch,
  readCvSeen,
  readJobSearch,
  readListSearch,
  readJobSearchReturn,
  readRecentSearches,
  recentKeywords,
  writeJobSearchReturn,
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
  it("CV oglądane w karcie: zapis dopisuje osobę z czasem, śmieci w pamięci są pomijane", () => {
    expect(readCvSeen()).toEqual({});
    const first = markCvSeen(12);
    expect(Object.keys(first)).toEqual(["12"]);
    expect(typeof first[12]).toBe("number");
    markCvSeen(34);
    expect(Object.keys(readCvSeen()).sort()).toEqual(["12", "34"]);

    window.sessionStorage.setItem("nexus.candidates.cvSeen", JSON.stringify({ 5: "wczoraj", 6: 1 }));
    expect(readCvSeen()).toEqual({ 6: 1 });
    window.sessionStorage.setItem("nexus.candidates.cvSeen", "[1,2]");
    expect(readCvSeen()).toEqual({});
  });

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

  it("powrót do okna rekrutacji: ostatnia osoba i wybrani osobno dla każdej rekrutacji", () => {
    expect(readJobSearchReturn(5)).toEqual({ lastOpenedId: null, picked: [] });
    writeJobSearchReturn(5, { lastOpenedId: 11 });
    writeJobSearchReturn(5, { picked: [11, 12] });
    writeJobSearchReturn(6, { picked: [99] });
    expect(readJobSearchReturn(5)).toEqual({ lastOpenedId: 11, picked: [11, 12] });
    expect(readJobSearchReturn(6)).toEqual({ lastOpenedId: null, picked: [99] });
  });

  it("powrót do okna rekrutacji: śmieci w pamięci są pomijane", () => {
    window.sessionStorage.setItem(
      "nexus:search-memory:job-return:5",
      JSON.stringify({ lastOpenedId: "x", picked: [1, "2", null, 3] }),
    );
    expect(readJobSearchReturn(5)).toEqual({ lastOpenedId: null, picked: [1, 3] });
    window.sessionStorage.setItem("nexus:search-memory:job-return:5", "{zepsute");
    expect(readJobSearchReturn(5)).toEqual({ lastOpenedId: null, picked: [] });
  });

  it("wylogowanie czyści całą pamięć wyszukiwań", () => {
    writeJobSearchReturn(5, { lastOpenedId: 11, picked: [11] });
    writeListSearch({ query: "q=java" });
    pushRecentSearch(7, entry("q=java"));
    window.localStorage.setItem("inny-klucz", "zostaje");
    clearSearchMemory();
    expect(readListSearch()).toBeNull();
    expect(readRecentSearches(7)).toEqual([]);
    expect(readJobSearchReturn(5)).toEqual({ lastOpenedId: null, picked: [] });
    expect(window.localStorage.getItem("inny-klucz")).toBe("zostaje");
  });
});
