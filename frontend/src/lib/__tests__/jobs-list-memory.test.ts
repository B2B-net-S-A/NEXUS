/**
 * Pamięć ostatniego widoku listy rekrutacji (13.10.2026) — wpis per osoba
 * w localStorage. Zachowanie listy: `JobsListV2Memory.test.tsx`.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  jobsListMemoryKey,
  readJobsListMemory,
  writeJobsListMemory,
} from "@/lib/jobs-list-memory";

describe("pamięć widoku listy rekrutacji", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("klucz jest per osoba; bez id nie ma pamięci", () => {
    expect(jobsListMemoryKey(7)).toBe("nexus:jobs-list-filters:7");
    expect(jobsListMemoryKey(8)).not.toBe(jobsListMemoryKey(7));
    expect(jobsListMemoryKey(null)).toBeNull();
    expect(jobsListMemoryKey(undefined)).toBeNull();

    writeJobsListMemory(null, "open=1");
    expect(window.localStorage.length).toBe(0);
    expect(readJobsListMemory(null)).toBeNull();
  });

  it("zapisany widok wraca jako parametry listy", () => {
    const key = jobsListMemoryKey(7);
    writeJobsListMemory(key, "open=1&stage=searching&client=5");

    const params = readJobsListMemory(key);
    expect(params?.get("open")).toBe("1");
    expect(params?.getAll("stage")).toEqual(["searching"]);
    expect(params?.getAll("client")).toEqual(["5"]);
    expect(readJobsListMemory(jobsListMemoryKey(8))).toBeNull();
  });

  it("pusty widok usuwa wpis", () => {
    const key = jobsListMemoryKey(7);
    writeJobsListMemory(key, "open=1");
    writeJobsListMemory(key, "");

    expect(window.localStorage.getItem("nexus:jobs-list-filters:7")).toBeNull();
    expect(readJobsListMemory(key)).toBeNull();
  });

  it("szukajka nie wraca z pamięci, a wpis bez kluczy listy to brak pamięci", () => {
    window.localStorage.setItem("nexus:jobs-list-filters:7", "q=java&open=1");
    expect(readJobsListMemory(jobsListMemoryKey(7))?.toString()).toBe("open=1");

    for (const raw of ["q=java", "status=published", "{\"zepsute\":true}", "cokolwiek"]) {
      window.localStorage.setItem("nexus:jobs-list-filters:7", raw);
      expect(readJobsListMemory(jobsListMemoryKey(7)), raw).toBeNull();
    }
  });

  it("zablokowana pamięć przeglądarki nie psuje listy", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("SecurityError");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("QuotaExceededError");
    });

    expect(readJobsListMemory(jobsListMemoryKey(7))).toBeNull();
    expect(() => writeJobsListMemory(jobsListMemoryKey(7), "open=1")).not.toThrow();
  });
});
