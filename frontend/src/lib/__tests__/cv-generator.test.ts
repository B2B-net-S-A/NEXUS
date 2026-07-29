import { describe, it, expect } from "vitest";
import {
  CHAMPION_ACCEPT,
  CV_CERTAIN_WARNING_PREFIXES,
  CV_CONTENT_MODES,
  DEFAULT_CV_CONTENT_MODE,
  MAX_UPLOAD_MB,
  fileValidationError,
  isCertainWarning,
  parseDispositionFilename,
} from "@/lib/cv-generator";

describe("isCertainWarning", () => {
  // Regresja: klasyfikator miał zahardkodowany polski prefiks, więc przy CV po
  // angielsku KAŻDE pewne trafienie („NOT IN SOURCE") wpadało cicho do
  // miękkich i czerwony blok nigdy się nie renderował.
  it("recognises certain findings in both document languages", () => {
    expect(
      isCertainWarning("BRAK POKRYCIA: liczba '12 osob' (Dev) nie występuje…"),
    ).toBe(true);
    expect(
      isCertainWarning("NOT IN SOURCE: figure '12 people' (Dev) does not appear…"),
    ).toBe(true);
  });

  it("treats soft hints as not certain, in both languages", () => {
    expect(isCertainWarning("WERYFIKUJ: technologia 'Kubernetes' …")).toBe(false);
    expect(isCertainWarning("VERIFY: technology 'Kubernetes' …")).toBe(false);
  });

  it("keeps both backend prefixes — dropping one silently breaks a language", () => {
    // Musi odpowiadać `_HIGH_PREFIX` w standalone_service.py.
    expect([...CV_CERTAIN_WARNING_PREFIXES]).toEqual([
      "BRAK POKRYCIA",
      "NOT IN SOURCE",
    ]);
  });
});

describe("fileValidationError", () => {
  const file = (name: string, size = 1024) =>
    new File([new Uint8Array(size)], name);

  it("accepts a .docx champion regardless of case or trailing space", () => {
    expect(fileValidationError(file("champion.docx"), CHAMPION_ACCEPT)).toBeNull();
    expect(fileValidationError(file("Champion.DOCX"), CHAMPION_ACCEPT)).toBeNull();
    expect(fileValidationError(file("champion.docx "), CHAMPION_ACCEPT)).toBeNull();
  });

  it("accepts a name containing dots before the extension", () => {
    expect(
      fileValidationError(file("Profil Championa 2026.01.20.docx"), CHAMPION_ACCEPT),
    ).toBeNull();
  });

  it("reports a missing extension instead of inventing one", () => {
    // `split(".").pop()` used to report '.profilchampiona' here.
    const err = fileValidationError(file("ProfilChampiona"), CHAMPION_ACCEPT);
    expect(err).toContain("nie ma rozszerzenia");
    expect(err).not.toContain("profilchampiona");
  });

  it("gives .doc its own actionable message", () => {
    expect(fileValidationError(file("champion.doc"), CHAMPION_ACCEPT)).toContain(
      "Word 97-2003",
    );
  });

  it("rejects a PDF champion with the allowed list", () => {
    expect(fileValidationError(file("champion.pdf"), CHAMPION_ACCEPT)).toContain(
      ".docx",
    );
  });

  it("rejects a file above the size cap", () => {
    const huge = new File([], "champion.docx");
    Object.defineProperty(huge, "size", {
      value: (MAX_UPLOAD_MB + 1) * 1024 * 1024,
    });
    expect(fileValidationError(huge, CHAMPION_ACCEPT)).toContain("za duży");
  });
});

describe("CV_CONTENT_MODES", () => {
  it("covers exactly the values the API accepts", () => {
    expect(CV_CONTENT_MODES.map((m) => m.value)).toEqual([
      "basic",
      "polished",
      "tailored",
    ]);
  });

  it("defaults to Redakcja, not the offer-tailored variant", () => {
    // Wysyłanie „tailored" bez decyzji rekrutera złamałoby wymóg części klientów
    // na profile nieprofilowane — default MUSI zostać zachowawczy.
    expect(DEFAULT_CV_CONTENT_MODE).toBe("polished");
    expect(CV_CONTENT_MODES.map((m) => m.value)).toContain(
      DEFAULT_CV_CONTENT_MODE,
    );
  });

  it("gives every option a Polish label and description", () => {
    // Kafelek bez opisu zmusza rekrutera do zgadywania — pilnujemy, żeby
    // dopisanie czwartego trybu nie przeszło z pustym tekstem.
    for (const mode of CV_CONTENT_MODES) {
      expect(mode.label.trim()).not.toBe("");
      expect(mode.description.trim()).not.toBe("");
    }
  });

  it("keeps the unprofiled-client caution on the tailored option", () => {
    const tailored = CV_CONTENT_MODES.find((m) => m.value === "tailored");
    expect(tailored?.caution).toContain("nieprofilowanych");
  });
});

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
