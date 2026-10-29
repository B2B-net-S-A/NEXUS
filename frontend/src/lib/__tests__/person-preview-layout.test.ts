/**
 * Pamięć układu podglądu w panelu osoby (zwinięte CV / wymagania,
 * 13.10.2026) — wpis per osoba w localStorage. Zachowanie panelu:
 * `PersonPanelSide.test.tsx`, `CandidatePreviewPane.test.tsx`.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  DEFAULT_PERSON_PREVIEW_LAYOUT,
  personPreviewLayoutKey,
  readPersonPreviewLayout,
  writePersonPreviewLayout,
} from "@/lib/person-preview-layout";

describe("pamięć układu podglądu w panelu osoby", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("klucz jest per osoba; bez id nie ma pamięci", () => {
    expect(personPreviewLayoutKey(7)).toBe("nexus:person-preview-layout:7");
    expect(personPreviewLayoutKey(8)).not.toBe(personPreviewLayoutKey(7));
    expect(personPreviewLayoutKey(null)).toBeNull();
    expect(personPreviewLayoutKey(undefined)).toBeNull();

    writePersonPreviewLayout(null, { cvCollapsed: true, infoCollapsed: false, columnWidth: null, compact: false });
    expect(window.localStorage.length).toBe(0);
    expect(readPersonPreviewLayout(null)).toEqual(DEFAULT_PERSON_PREVIEW_LAYOUT);
  });

  it("bez wpisu oba elementy są otwarte", () => {
    expect(DEFAULT_PERSON_PREVIEW_LAYOUT).toEqual({
      cvCollapsed: false,
      infoCollapsed: false,
      columnWidth: null,
      compact: false,
    });
    expect(readPersonPreviewLayout(personPreviewLayoutKey(7))).toEqual(DEFAULT_PERSON_PREVIEW_LAYOUT);
  });

  it("zapisany układ wraca tylko tej osobie", () => {
    const key = personPreviewLayoutKey(7);
    writePersonPreviewLayout(key, { cvCollapsed: true, infoCollapsed: true, columnWidth: null, compact: false });

    expect(readPersonPreviewLayout(key)).toEqual({ cvCollapsed: true, infoCollapsed: true, columnWidth: null, compact: false });
    expect(readPersonPreviewLayout(personPreviewLayoutKey(8))).toEqual(DEFAULT_PERSON_PREVIEW_LAYOUT);
  });

  it("zepsuty wpis to układ domyślny, pole po polu", () => {
    const key = personPreviewLayoutKey(7);
    for (const raw of ["cokolwiek", "null", "[]", "{\"cvCollapsed\":\"tak\"}", "{}"]) {
      window.localStorage.setItem("nexus:person-preview-layout:7", raw);
      expect(readPersonPreviewLayout(key), raw).toEqual(DEFAULT_PERSON_PREVIEW_LAYOUT);
    }
    window.localStorage.setItem("nexus:person-preview-layout:7", "{\"infoCollapsed\":true,\"cvCollapsed\":1}");
    expect(readPersonPreviewLayout(key)).toEqual({ ...DEFAULT_PERSON_PREVIEW_LAYOUT, infoCollapsed: true });
  });

  it("szerokość kolumny i tryb rozmowy wracają; zepsute wartości to domyślne (29.10.2026)", () => {
    const key = personPreviewLayoutKey(7);
    writePersonPreviewLayout(key, { cvCollapsed: false, infoCollapsed: false, columnWidth: 640, compact: true });
    expect(readPersonPreviewLayout(key)).toEqual({ cvCollapsed: false, infoCollapsed: false, columnWidth: 640, compact: true });

    for (const width of ["640", -5, 0, null, "NaN"]) {
      window.localStorage.setItem("nexus:person-preview-layout:7", JSON.stringify({ columnWidth: width, compact: "tak" }));
      expect(readPersonPreviewLayout(key), String(width)).toEqual(DEFAULT_PERSON_PREVIEW_LAYOUT);
    }
    window.localStorage.setItem("nexus:person-preview-layout:7", JSON.stringify({ columnWidth: 612.6 }));
    expect(readPersonPreviewLayout(key).columnWidth).toBe(613);
  });

  it("zablokowana pamięć przeglądarki nie psuje panelu", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("SecurityError");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("QuotaExceededError");
    });
    const key = personPreviewLayoutKey(7);

    expect(() => writePersonPreviewLayout(key, { cvCollapsed: true, infoCollapsed: false, columnWidth: null, compact: false })).not.toThrow();
    expect(readPersonPreviewLayout(key)).toEqual(DEFAULT_PERSON_PREVIEW_LAYOUT);
  });
});
