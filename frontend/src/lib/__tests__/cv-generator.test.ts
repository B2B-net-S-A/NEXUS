import { describe, it, expect } from "vitest";
import warningCases from "../__fixtures__/cv-warning-cases.json";
import {
  CHAMPION_ACCEPT,
  classifyCvWarnings,
  CV_CERTAIN_WARNING_PREFIXES,
  CV_CONTENT_MODES,
  DEFAULT_CV_CONTENT_MODE,
  MAX_UPLOAD_MB,
  extractErrorDetail,
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

describe("extractErrorDetail", () => {
  const axiosError = (status: number, data: unknown) => ({ response: { status, data } });

  it("reads the quota reason with usage numbers instead of a generic failure", async () => {
    const err = axiosError(503, {
      detail: {
        feature: "cv_generator",
        reason: "Miesięczny limit generacji CV został wyczerpany.",
        used: 40,
        limit: 40,
      },
    });
    expect(await extractErrorDetail(err)).toBe(
      "Miesięczny limit generacji CV został wyczerpany. (wykorzystano 40/40)",
    );
  });

  it("returns the reason alone when numbers are absent", async () => {
    const err = axiosError(503, {
      detail: { feature: "cv_generator", reason: "AI jest wyłączone przez administratora.", used: null, limit: null },
    });
    expect(await extractErrorDetail(err)).toBe("AI jest wyłączone przez administratora.");
  });

  it("translates a validation array into text, never an object", async () => {
    const err = axiosError(422, {
      detail: [{ type: "string_too_long", loc: ["body", "project_ref"], msg: "String should have at most 120 characters" }],
    });
    const message = await extractErrorDetail(err);
    expect(typeof message).toBe("string");
    expect(message).toBe("project_ref: String should have at most 120 characters");
  });

  it("keeps a plain string detail", async () => {
    expect(await extractErrorDetail(axiosError(422, { detail: "Ten klient wymaga stanowiska." }))).toBe(
      "Ten klient wymaga stanowiska.",
    );
  });

  it("reads JSON detail out of a Blob body (responseType: blob)", async () => {
    const blob = new Blob([JSON.stringify({ detail: { reason: "Limit wyczerpany.", used: 3, limit: 3 } })], {
      type: "application/json",
    });
    expect(await extractErrorDetail(axiosError(503, blob))).toBe("Limit wyczerpany. (wykorzystano 3/3)");
    const plain = new Blob([JSON.stringify({ detail: "Brak pliku." })]);
    expect(await extractErrorDetail(axiosError(404, plain))).toBe("Brak pliku.");
    expect(await extractErrorDetail(axiosError(500, new Blob(["<html>"])))).toBe("");
  });

  it("returns an empty string when there is nothing to show", async () => {
    expect(await extractErrorDetail(new Error("Network Error"))).toBe("");
    expect(await extractErrorDetail(null)).toBe("");
  });
});


describe("classifyCvWarnings — prawdziwe teksty backendu", () => {
  it.each(warningCases.cases.map((c) => [c.text, c.group, c.kind] as const))(
    "%s → %s",
    (text, group, kind) => {
      const result = classifyCvWarnings([text]);
      const bucket = group === "info" ? result.info : result.review;
      expect(bucket).toHaveLength(1);
      expect(bucket[0].kind).toBe(kind);
    },
  );

  it("nieznany tekst trafia do „Do sprawdzenia”, nigdy do informacji", () => {
    const result = classifyCvWarnings(["Zupełnie nowy komunikat"]);
    expect(result.review.map((w) => w.text)).toEqual(["Zupełnie nowy komunikat"]);
    expect(result.info).toEqual([]);
  });

  it("zlicza rodzaje informacji do jednej linii i pomija duplikaty", () => {
    const overlap = "WERYFIKUJ: nakładające się okresy zatrudnienia: 'A' (2020) i 'B' (2021)";
    const result = classifyCvWarnings([
      overlap,
      overlap,
      "WERYFIKUJ: nakładające się okresy zatrudnienia: 'C' (2019) i 'D' (2019)",
      "NICE-TO-HAVE: Grafana",
      "",
    ]);
    expect(result.infoKinds).toEqual([
      { kind: "nakładające się okresy", count: 2 },
      { kind: "brakujące NICE-TO-HAVE", count: 1 },
    ]);
  });
});
