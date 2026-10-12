import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { clearNoteDrafts, readNoteDraft, writeNoteDraft } from "@/lib/note-drafts";

beforeEach(() => {
  sessionStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("szkic notatki z panelu osoby", () => {
  it("wraca dla tej samej osoby piszącej, rekrutacji i kandydata", () => {
    writeNoteDraft(7, 10, 42, "Oddzwonić po 15");
    expect(readNoteDraft(7, 10, 42)).toBe("Oddzwonić po 15");
  });

  it("nie przechodzi na innego kandydata, inną rekrutację ani inną osobę piszącą", () => {
    writeNoteDraft(7, 10, 42, "Oddzwonić po 15");
    expect(readNoteDraft(7, 10, 43)).toBe("");
    expect(readNoteDraft(7, 11, 42)).toBe("");
    expect(readNoteDraft(8, 10, 42)).toBe("");
  });

  it("pusty tekst i same odstępy usuwają szkic", () => {
    writeNoteDraft(7, 10, 42, "Oddzwonić");
    writeNoteDraft(7, 10, 42, "  \n ");
    expect(readNoteDraft(7, 10, 42)).toBe("");
    expect(sessionStorage.length).toBe(0);
  });

  it("bez zalogowanej osoby nic nie zapisuje i nic nie czyta", () => {
    writeNoteDraft(undefined, 10, 42, "Oddzwonić");
    expect(sessionStorage.length).toBe(0);
    expect(readNoteDraft(undefined, 10, 42)).toBe("");
  });

  it("zablokowana pamięć przeglądarki nie wywraca pola", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("QuotaExceededError");
    });
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("SecurityError");
    });
    expect(() => writeNoteDraft(7, 10, 42, "Oddzwonić")).not.toThrow();
    expect(readNoteDraft(7, 10, 42)).toBe("");
  });

  it("czyszczenie kasuje wszystkie szkice i zostawia obce klucze", () => {
    writeNoteDraft(7, 10, 42, "Pierwszy");
    writeNoteDraft(7, 11, 43, "Drugi");
    sessionStorage.setItem("unrelated_session_key", "keep");

    clearNoteDrafts();

    expect(readNoteDraft(7, 10, 42)).toBe("");
    expect(readNoteDraft(7, 11, 43)).toBe("");
    expect(sessionStorage.getItem("unrelated_session_key")).toBe("keep");
  });
});
