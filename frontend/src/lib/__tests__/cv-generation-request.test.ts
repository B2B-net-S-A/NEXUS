import { beforeEach, afterEach, expect, it, vi } from "vitest";
import { webcrypto } from "node:crypto";

beforeEach(() => { vi.stubGlobal("crypto", webcrypto); sessionStorage.clear(); vi.resetModules(); });
afterEach(() => vi.unstubAllGlobals());

it("reuses an uncertain attempt across reload, then starts a new deliberate generation", async () => {
  let {withCvGenerationRequest} = await import("../cv-generation-request");
  const keys: string[] = [];
  await expect(withCvGenerationRequest("/generate", {a: 1, privateName: "Synthetic"}, async key => {
    keys.push(key); throw new Error("network lost");
  })).rejects.toThrow("network lost");
  expect(JSON.stringify(sessionStorage)).not.toContain("Synthetic");
  vi.resetModules();
  ({withCvGenerationRequest} = await import("../cv-generation-request"));
  await withCvGenerationRequest("/generate", {privateName: "Synthetic", a: 1}, async key => keys.push(key));
  expect(keys[1]).toBe(keys[0]);
  expect(sessionStorage.length).toBe(0);
  await withCvGenerationRequest("/generate", {a: 1, privateName: "Synthetic"}, async key => keys.push(key));
  expect(keys[2]).not.toBe(keys[0]);
});

it("different bytes with the same filename create different attempts", async () => {
  const {withCvGenerationRequest} = await import("../cv-generation-request");
  const keys: string[] = [];
  for (const content of ["ABC", "XYZ"]) {
    const file = new File([content], "same.docx");
    Object.defineProperty(file, "arrayBuffer", {value: async () => new TextEncoder().encode(content).buffer});
    const data = new FormData(); data.append("cv_file", file);
    await expect(withCvGenerationRequest("/upload", data, async key => {
      keys.push(key); throw new Error("network lost");
    })).rejects.toThrow("network lost");
  }
  expect(keys[0]).not.toBe(keys[1]);
});

it("does not automatically retry a deleted result but allows a new deliberate attempt", async () => {
  const {withCvGenerationRequest} = await import("../cv-generation-request");
  const keys: string[] = [];
  const gone = {response: {status: 410}};
  await expect(withCvGenerationRequest("/preview", {candidate_id: 1}, async key => {
    keys.push(key); throw gone;
  })).rejects.toBe(gone);
  expect(keys).toHaveLength(1);
  expect(sessionStorage.length).toBe(0);
  await withCvGenerationRequest("/preview", {candidate_id: 1}, async key => keys.push(key));
  expect(keys[1]).not.toBe(keys[0]);
});
