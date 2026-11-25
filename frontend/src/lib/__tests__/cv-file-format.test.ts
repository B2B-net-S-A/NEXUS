import { describe, expect, it } from "vitest";

import { cvDownloadPlan, cvFileFormat, withClassicLayout, wordLabel } from "@/lib/cv-file-format";

describe("cvDownloadPlan — co pobiera rekruter przy układzie i formacie klienta", () => {
  it("bez wymagań: klasyczne → Word, PDF w menu; Nowe CV → PDF i Word, klasyczny Word w menu", () => {
    expect(cvDownloadPlan(null, "classic")).toEqual({ primary: ["docx"], inMenu: ["pdf"] });
    expect(cvDownloadPlan(undefined, "new")).toEqual({ primary: ["pdf", "docx"], inMenu: ["docx_classic"] });
  });

  it("Word: Word na wierzchu (przy Nowym CV w nowym wyglądzie), reszta w menu", () => {
    expect(cvDownloadPlan("docx", "classic")).toEqual({ primary: ["docx"], inMenu: ["pdf"] });
    expect(cvDownloadPlan("docx", "new")).toEqual({ primary: ["docx"], inMenu: ["pdf", "docx_classic"] });
  });

  it("PDF: PDF na wierzchu, Word w menu", () => {
    expect(cvDownloadPlan("pdf", "classic")).toEqual({ primary: ["pdf"], inMenu: ["docx"] });
    expect(cvDownloadPlan("pdf", "new")).toEqual({ primary: ["pdf"], inMenu: ["docx", "docx_classic"] });
  });

  it("oba: Word i PDF na wierzchu", () => {
    expect(cvDownloadPlan("both", "classic")).toEqual({ primary: ["docx", "pdf"], inMenu: [] });
    expect(cvDownloadPlan("both", "new")).toEqual({ primary: ["docx", "pdf"], inMenu: ["docx_classic"] });
  });

  it("klasyczny Word jest tylko przy Nowym CV", () => {
    for (const format of [null, "docx", "pdf", "both"] as const) {
      const plan = cvDownloadPlan(format, "classic");
      expect([...plan.primary, ...plan.inMenu]).not.toContain("docx_classic");
    }
  });
});

describe("cvFileFormat i adresy", () => {
  it("nieznana wartość z serwera = bez wymagań", () => {
    expect(cvFileFormat("docx")).toBe("docx");
    expect(cvFileFormat("both")).toBe("both");
    expect(cvFileFormat("xls")).toBeNull();
    expect(cvFileFormat(null)).toBeNull();
  });

  it("„Word (klasyczne)” dopisuje layout=classic, także po innych parametrach", () => {
    expect(withClassicLayout("/api/x/docx", false)).toBe("/api/x/docx");
    expect(withClassicLayout("/api/x/docx", true)).toBe("/api/x/docx?layout=classic");
    expect(withClassicLayout("/api/x/docx?intent=download", true)).toBe("/api/x/docx?intent=download&layout=classic");
    expect(wordLabel("docx")).toBe("Pobierz Word");
    expect(wordLabel("docx_classic")).toBe("Word (klasyczne)");
  });
});
