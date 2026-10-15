import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { clearCvRewriteDrafts, readCvRewriteDraft, writeCvRewriteDraft } from "@/lib/cv-rewrite-drafts";

beforeEach(() => {
  sessionStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("szkic listy poprawek CV („Co poprawić?”)", () => {
  it("wraca z podziałem na linie dla tej samej osoby i wiersza etapu", () => {
    writeCvRewriteDraft(7, 21, "1. krócej\n2. więcej o Kafce");
    expect(readCvRewriteDraft(7, 21)).toBe("1. krócej\n2. więcej o Kafce");
  });

  it("nie przechodzi na inny etap ani na inną osobę piszącą", () => {
    writeCvRewriteDraft(7, 21, "krócej");
    expect(readCvRewriteDraft(7, 22)).toBe("");
    expect(readCvRewriteDraft(8, 21)).toBe("");
  });

  it("pusty tekst i same odstępy usuwają szkic", () => {
    writeCvRewriteDraft(7, 21, "krócej");
    writeCvRewriteDraft(7, 21, "  \n ");
    expect(sessionStorage.length).toBe(0);
  });

  it("bez zalogowanej osoby nic nie zapisuje i nic nie czyta", () => {
    writeCvRewriteDraft(undefined, 21, "krócej");
    expect(sessionStorage.length).toBe(0);
    expect(readCvRewriteDraft(undefined, 21)).toBe("");
  });

  it("zablokowana pamięć przeglądarki nie wywraca pola", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("quota", "QuotaExceededError");
    });
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    expect(() => writeCvRewriteDraft(7, 21, "krócej")).not.toThrow();
    expect(readCvRewriteDraft(7, 21)).toBe("");
  });

  it("wylogowanie kasuje tylko szkice list poprawek", () => {
    writeCvRewriteDraft(7, 21, "krócej");
    writeCvRewriteDraft(7, 22, "dłużej");
    sessionStorage.setItem("nexus:note-draft:v1:7:10:42", "notatka");
    clearCvRewriteDrafts();
    expect(readCvRewriteDraft(7, 21)).toBe("");
    expect(readCvRewriteDraft(7, 22)).toBe("");
    expect(sessionStorage.getItem("nexus:note-draft:v1:7:10:42")).toBe("notatka");
  });
});
