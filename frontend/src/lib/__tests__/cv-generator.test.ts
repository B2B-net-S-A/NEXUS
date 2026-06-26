import { describe, it, expect } from "vitest";
import { parseDispositionFilename } from "@/lib/cv-generator";

describe("parseDispositionFilename", () => {
  it("decodes the RFC 5987 filename* parameter so Polish characters survive", () => {
    const disposition =
      "attachment; filename=\"CV_B2B_Kamil_Szukajlo.docx\"; filename*=UTF-8''CV_B2B_Kamil_Szukaj%C5%82o.docx";
    expect(parseDispositionFilename(disposition, "fallback.docx")).toBe(
      "CV_B2B_Kamil_Szukajło.docx",
    );
  });

  it("prefers filename* even when the ASCII filename appears first", () => {
    const disposition =
      "attachment; filename=\"plik.docx\"; filename*=UTF-8''Za%C5%BC%C3%B3%C5%82%C4%87.docx";
    expect(parseDispositionFilename(disposition, "fallback.docx")).toBe(
      "Zażółć.docx",
    );
  });

  it("falls back to the ASCII filename when filename* is absent", () => {
    const disposition = 'attachment; filename="CV_B2B_Anna_Kowalska.docx"';
    expect(parseDispositionFilename(disposition, "fallback.docx")).toBe(
      "CV_B2B_Anna_Kowalska.docx",
    );
  });

  it("returns the fallback when no filename is present", () => {
    expect(parseDispositionFilename("attachment", "fallback.docx")).toBe(
      "fallback.docx",
    );
  });
});
