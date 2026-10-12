import { describe, expect, it, vi } from "vitest";

import {
  VERSION_RELOAD_STORAGE_KEY,
  fetchDeployedSha,
  isBuildSha,
  isOtherBuild,
  reloadOnceForVersion,
} from "@/lib/app-version";

const OLD = "a".repeat(40);
const NEW = "b".repeat(40);

function memoryStorage(): Pick<Storage, "getItem" | "setItem"> & { data: Map<string, string> } {
  const data = new Map<string, string>();
  return {
    data,
    getItem: (key) => data.get(key) ?? null,
    setItem: (key, value) => void data.set(key, value),
  };
}

describe("isOtherBuild — karta a serwer", () => {
  it("inny pełny SHA na serwerze = karta działa na starej wersji", () => {
    expect(isOtherBuild(OLD, NEW)).toBe(true);
    expect(isOtherBuild(OLD, OLD)).toBe(false);
    expect(isOtherBuild(OLD, OLD.toUpperCase())).toBe(false);
  });

  it("bez pewnego SHA po obu stronach nigdy nie mówi „stara wersja”", () => {
    // Lokalnie i w testach paczka nie ma SHA; plik z builda bez SHA mówi „unknown”.
    expect(isBuildSha("")).toBe(false);
    expect(isOtherBuild("", NEW)).toBe(false);
    expect(isOtherBuild(OLD, "unknown")).toBe(false);
    expect(isOtherBuild(OLD, null)).toBe(false);
    expect(isOtherBuild(OLD, undefined)).toBe(false);
  });
});

describe("fetchDeployedSha — `/version.json` z serwera", () => {
  it("pyta z pominięciem pamięci przeglądarki i pośredników", async () => {
    const fetchImpl = vi.fn(async () => new Response(JSON.stringify({ sha: NEW })));
    await expect(fetchDeployedSha(fetchImpl, () => 1234)).resolves.toBe(NEW);
    expect(fetchImpl).toHaveBeenCalledWith("/version.json?t=1234", { cache: "no-store" });
  });

  it("awaria, wdrożenie w toku albo plik bez SHA to „nie wiem”, nie błąd", async () => {
    await expect(fetchDeployedSha(async () => new Response("", { status: 502 }))).resolves.toBeNull();
    await expect(
      fetchDeployedSha(async () => {
        throw new TypeError("Failed to fetch");
      }),
    ).resolves.toBeNull();
    await expect(fetchDeployedSha(async () => new Response("<html>"))).resolves.toBeNull();
    await expect(fetchDeployedSha(async () => new Response("{}"))).resolves.toBeNull();
  });
});

describe("reloadOnceForVersion", () => {
  it("przeładowuje raz na wersję serwera — drugi raz dopiero dla kolejnej", () => {
    const storage = memoryStorage();
    const reload = vi.fn();
    expect(reloadOnceForVersion(NEW, { storage, reload })).toBe(true);
    expect(storage.data.get(VERSION_RELOAD_STORAGE_KEY)).toBe(NEW);
    // Po przeładowaniu karta nadal stara (dokument z pamięci): bez pętli.
    expect(reloadOnceForVersion(NEW, { storage, reload })).toBe(false);
    expect(reload).toHaveBeenCalledTimes(1);
    expect(reloadOnceForVersion("c".repeat(40), { storage, reload })).toBe(true);
    expect(reload).toHaveBeenCalledTimes(2);
  });

  it("bez sessionStorage nie przeładowuje wcale (nie da się zagwarantować „raz”)", () => {
    const reload = vi.fn();
    expect(reloadOnceForVersion(NEW, { storage: null, reload })).toBe(false);
    const broken = {
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => undefined,
    };
    expect(reloadOnceForVersion(NEW, { storage: broken, reload })).toBe(false);
    expect(reload).not.toHaveBeenCalled();
  });
});
