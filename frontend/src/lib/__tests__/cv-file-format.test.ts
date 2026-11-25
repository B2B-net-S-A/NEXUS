import { describe, expect, it } from "vitest";

import { cvDownloadPlan, cvFileFormat, wordClassicWarning } from "@/lib/cv-file-format";

describe("cvDownloadPlan — co pobiera rekruter przy układzie i formacie klienta", () => {
  it("bez wymagań zostaje jak dotąd: klasyczne → Word, PDF w menu; Nowe CV → PDF i Word", () => {
    expect(cvDownloadPlan(null, "classic")).toEqual({ primary: ["docx"], inMenu: ["pdf"], warnWordClassic: false });
    expect(cvDownloadPlan(undefined, "new")).toEqual({ primary: ["pdf", "docx"], inMenu: [], warnWordClassic: false });
  });

  it("Word: Word na wierzchu; przy Nowym CV ostrzeżenie, bo Word jest klasyczny", () => {
    expect(cvDownloadPlan("docx", "classic")).toEqual({ primary: ["docx"], inMenu: ["pdf"], warnWordClassic: false });
    expect(cvDownloadPlan("docx", "new")).toEqual({ primary: ["docx"], inMenu: ["pdf"], warnWordClassic: true });
  });

  it("PDF: PDF na wierzchu, Word w menu, bez ostrzeżenia w obu układach", () => {
    expect(cvDownloadPlan("pdf", "classic")).toEqual({ primary: ["pdf"], inMenu: ["docx"], warnWordClassic: false });
    expect(cvDownloadPlan("pdf", "new")).toEqual({ primary: ["pdf"], inMenu: ["docx"], warnWordClassic: false });
  });

  it("oba: oba pliki na wierzchu; przy Nowym CV ostrzeżenie", () => {
    expect(cvDownloadPlan("both", "classic")).toEqual({ primary: ["docx", "pdf"], inMenu: [], warnWordClassic: false });
    expect(cvDownloadPlan("both", "new")).toEqual({ primary: ["docx", "pdf"], inMenu: [], warnWordClassic: true });
  });
});

describe("cvFileFormat", () => {
  it("nieznana wartość z serwera = bez wymagań", () => {
    expect(cvFileFormat("docx")).toBe("docx");
    expect(cvFileFormat("both")).toBe("both");
    expect(cvFileFormat("xls")).toBeNull();
    expect(cvFileFormat(null)).toBeNull();
  });

  it("ostrzeżenie mówi, czego klient chce", () => {
    expect(wordClassicWarning("docx")).toMatch(/^Klient chce Worda, a wybrane jest Nowe CV/);
    expect(wordClassicWarning("both")).toMatch(/^Klient chce Worda i PDF/);
  });
});
