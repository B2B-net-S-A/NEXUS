import { describe, expect, it } from "vitest";

import {
  confirmationsLeft,
  confirmedCountLabel,
  confirmLeftSentence,
  cvFileChoices,
  cvFileDetail,
  NO_CONFIRMATIONS,
  rewriteSourceFileId,
  sourceCvWarning,
} from "@/lib/cv-generate-confirm";
import type { CvAiSourceFile } from "@/lib/cv-ai-sources";

const FILE: CvAiSourceFile = {
  document_id: 7,
  filename: "Jan_Kowalski_CV.pdf",
  uploaded_at: "2026-10-14T09:00:00Z",
  is_primary: false,
  outdated: false,
  stage_original: true,
};

describe("potwierdzenia przed generacją CV (21.10.2026)", () => {
  it("na starcie wszystkie trzy kroki czekają, „Generuj” jest zablokowane", () => {
    const left = confirmationsLeft(NO_CONFIRMATIONS, { fileId: 7, noteDraft: "" });
    expect(left).toEqual(["file", "answers", "notes"]);
    expect(confirmedCountLabel(left)).toBe("Potwierdzone 0 z 3");
    expect(confirmLeftSentence(left)).toBe("Potwierdź jeszcze: plik, odpowiedzi, notatki");
  });

  it("trzy potwierdzenia odblokowują generację", () => {
    const left = confirmationsLeft({ file: 7, answers: true, notes: "" }, { fileId: 7, noteDraft: "" });
    expect(left).toEqual([]);
    expect(confirmLeftSentence(left)).toBeNull();
    expect(confirmedCountLabel(left)).toBe("Potwierdzone 3 z 3");
  });

  it("zmiana pliku po potwierdzeniu zdejmuje potwierdzenie pliku", () => {
    expect(confirmationsLeft({ file: 7, answers: true, notes: "" }, { fileId: 8, noteDraft: "" })).toEqual(["file"]);
  });

  it("bez pliku krok pliku nie może być potwierdzony", () => {
    expect(confirmationsLeft({ file: 7, answers: true, notes: "" }, { fileId: null, noteDraft: "" })).toEqual(["file"]);
  });

  it("dopisanie notatki po „Nie mam nic do dodania” wymaga potwierdzenia jeszcze raz", () => {
    const confirmed = { file: 7, answers: true, notes: "" };
    expect(confirmationsLeft(confirmed, { fileId: 7, noteDraft: "prowadził migrację" })).toEqual(["notes"]);
    // Same spacje na końcu nie zmieniają treści.
    expect(
      confirmationsLeft({ ...confirmed, notes: "prowadził migrację" }, { fileId: 7, noteDraft: "prowadził migrację  " }),
    ).toEqual([]);
  });
});

describe("pliki do wyboru", () => {
  it("opis mówi, czym jest plik", () => {
    expect(cvFileDetail(FILE)).toBe("Oryginał CV w tej rekrutacji · wgrane 14.10.2026");
    expect(cvFileDetail({ ...FILE, stage_original: false, is_primary: true, outdated: false })).toBe(
      "główne CV profilu · wgrane 14.10.2026",
    );
    expect(cvFileDetail({ ...FILE, stage_original: false, outdated: true, uploaded_at: null })).toBe("nieaktualne");
  });

  it("serwer bez listy plików: jedyny wybór to plik domyślny", () => {
    expect(cvFileChoices({ original_cv: { document_id: 3, filename: "cv.pdf", uploaded_at: null } })).toEqual([
      { document_id: 3, filename: "cv.pdf", uploaded_at: null, is_primary: false, outdated: false, stage_original: false },
    ]);
    expect(cvFileChoices({ original_cv: null, cv_files: [] })).toEqual([]);
    expect(cvFileChoices({ original_cv: null, cv_files: [FILE] })).toEqual([FILE]);
  });
});

describe("„Powstało z” — kiedy źródło gotowego CV jest podejrzane", () => {
  const original = { ...FILE };
  const used = (extra: Partial<{ document_id: number; filename: string; outdated: boolean; stage_original: boolean; removed: boolean }> = {}) => ({
    document_id: 7,
    filename: "Jan_Kowalski_CV.pdf",
    outdated: false,
    stage_original: true,
    removed: false,
    ...extra,
  });

  it("oryginał rekrutacji i CV sprzed zmiany — bez ramki", () => {
    expect(sourceCvWarning({ original_cv: null, cv_files: [original], last_source_cv: used() })).toBeNull();
    expect(sourceCvWarning({ original_cv: null, cv_files: [original], last_source_cv: null })).toBeNull();
    expect(sourceCvWarning(undefined)).toBeNull();
  });

  it("CV dla klienta, nieaktualne, usunięte i inny plik niż oryginał — ramka z nazwą oryginału", () => {
    const b2b = used({ document_id: 9, filename: "Jan_Kowalski_B2B_Orlen.docx", stage_original: false });
    expect(sourceCvWarning({ original_cv: null, cv_files: [original], last_source_cv: b2b })).toBe(
      "CV powstało z Jan_Kowalski_B2B_Orlen.docx — to „CV dla klienta”, nie CV kandydata. Oryginał CV w tej rekrutacji to Jan_Kowalski_CV.pdf.",
    );
    expect(
      sourceCvWarning({ original_cv: null, cv_files: [original], last_source_cv: used({ document_id: 8, filename: "stare.docx", stage_original: false, outdated: true }) }),
    ).toBe("CV powstało z pliku stare.docx, oznaczonego jako nieaktualny. Oryginał CV w tej rekrutacji to Jan_Kowalski_CV.pdf.");
    expect(
      sourceCvWarning({ original_cv: null, cv_files: [original], last_source_cv: used({ document_id: 8, filename: "x.pdf", stage_original: false, removed: true }) }),
    ).toMatch(/którego nie ma już w profilu/);
    expect(
      sourceCvWarning({ original_cv: null, cv_files: [original], last_source_cv: used({ document_id: 8, filename: "inne.pdf", stage_original: false }) }),
    ).toBe("CV powstało z inne.pdf, a nie z Oryginału CV tej rekrutacji. Oryginał CV w tej rekrutacji to Jan_Kowalski_CV.pdf.");
  });

  it("bez kopii oryginału w rekrutacji zwykły plik nie budzi ramki", () => {
    expect(
      sourceCvWarning({ original_cv: null, cv_files: [{ ...original, stage_original: false }], last_source_cv: used({ stage_original: false }) }),
    ).toBeNull();
  });
});

describe("rewriteSourceFileId — „Napisz od nowa” z pliku poprawianego CV (audyt 22.10)", () => {
  const used = { document_id: 9, filename: "Jan_CV_2026.pdf", outdated: false, stage_original: false, removed: false };

  it("bierze plik, z którego powstało CV", () => {
    expect(rewriteSourceFileId({ last_source_cv: used })).toBe(9);
  });

  it("usunięty, nieaktualny, „CV dla klienta” albo nieznany — plik domyślny", () => {
    expect(rewriteSourceFileId({ last_source_cv: { ...used, removed: true } })).toBeNull();
    expect(rewriteSourceFileId({ last_source_cv: { ...used, outdated: true } })).toBeNull();
    expect(rewriteSourceFileId({ last_source_cv: { ...used, filename: "Jan_B2B_Orlen.docx" } })).toBeNull();
    expect(rewriteSourceFileId({ last_source_cv: null })).toBeNull();
    expect(rewriteSourceFileId(undefined)).toBeNull();
  });
});
