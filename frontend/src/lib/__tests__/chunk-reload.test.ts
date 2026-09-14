import { describe, expect, it, vi } from "vitest";

import {
  CHUNK_RELOAD_STORAGE_KEY,
  CHUNK_RELOAD_WINDOW_MS,
  isChunkLoadError,
  reloadOnceForChunkError,
} from "@/lib/chunk-reload";

function memoryStorage(): Pick<Storage, "getItem" | "setItem"> & { data: Map<string, string> } {
  const data = new Map<string, string>();
  return {
    data,
    getItem: (key) => data.get(key) ?? null,
    setItem: (key, value) => void data.set(key, value),
  };
}

describe("isChunkLoadError", () => {
  it("rozpoznaje warianty Next/webpack/Vite, pomija inne błędy", () => {
    const chunk = Object.assign(new Error("Loading chunk 8123 failed."), { name: "ChunkLoadError" });
    expect(isChunkLoadError(chunk)).toBe(true);
    expect(isChunkLoadError(new Error("Loading CSS chunk app-layout failed"))).toBe(true);
    expect(isChunkLoadError(new TypeError("Failed to fetch dynamically imported module: /x.js"))).toBe(true);
    expect(isChunkLoadError(new Error("Network Error"))).toBe(false);
    expect(isChunkLoadError(undefined)).toBe(false);
  });
});

describe("reloadOnceForChunkError", () => {
  it("przeładowuje raz na okno — druga porażka nie tworzy pętli", () => {
    const storage = memoryStorage();
    const reload = vi.fn();
    let clock = 1_000_000;
    const deps = { storage, reload, now: () => clock };
    const error = { name: "ChunkLoadError", message: "Loading chunk 1 failed" };

    expect(reloadOnceForChunkError(error, deps)).toBe(true);
    expect(storage.data.get(CHUNK_RELOAD_STORAGE_KEY)).toBe(String(clock));
    clock += 5_000;
    expect(reloadOnceForChunkError(error, deps)).toBe(false);
    expect(reload).toHaveBeenCalledTimes(1);

    clock += CHUNK_RELOAD_WINDOW_MS;
    expect(reloadOnceForChunkError(error, deps)).toBe(true);
    expect(reload).toHaveBeenCalledTimes(2);
  });

  it("nie przeładowuje przy innych błędach ani bez sessionStorage", () => {
    const reload = vi.fn();
    expect(reloadOnceForChunkError(new Error("boom"), { storage: memoryStorage(), reload })).toBe(false);
    expect(
      reloadOnceForChunkError({ name: "ChunkLoadError" }, { storage: null, reload }),
    ).toBe(false);
    expect(reload).not.toHaveBeenCalled();
  });
});
