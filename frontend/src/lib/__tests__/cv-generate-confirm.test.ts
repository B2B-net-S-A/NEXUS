import { describe, expect, it } from "vitest";

import {
  confirmationsLeft,
  confirmedCountLabel,
  confirmLeftSentence,
  cvFileChoices,
  cvFileDetail,
  NO_CONFIRMATIONS,
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
