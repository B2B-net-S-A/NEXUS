import { describe, expect, it } from "vitest";

import type { RecruitmentOption } from "@/lib/cv-generator";

import {
  OTHER_CLIENT_CHOICE,
  advancedNeedsAttention,
  autoProcessChoice,
  buildGeneratePayload,
  buildUploadFormData,
  defaultLanguageChoice,
  defaultProcessingMode,
  formatCvListDate,
  languageOptionEnabled,
  languagePayload,
  missingInputs,
  processLabel,
  type MissingInput,
} from "../cv-generator-form";

function recruitment(partial: Partial<RecruitmentOption> = {}): RecruitmentOption {
  return {
    stage_id: 11,
    job_id: 501,
    job_title: "Senior Java Developer",
    stage: "verified",
    has_champion: true,
    has_notes: true,
    has_cv: true,
    notes_chars: 800,
    ready: true,
    client_id: 7,
    client_name: "PKO BP",
    ...partial,
  };
}

function missing(partial: Partial<MissingInput> = {}): string[] {
  return missingInputs({
    flow: "person",
    policyPending: false,
    policyError: false,
    candidateId: 1,
    processChoice: "11",
    recruitment: recruitment(),
    recruitmentsLoading: false,
    otherClient: null,
    cvDocumentId: 5,
    sourcesLoading: false,
    sourcesCount: 1,
    noteDraft: "",
    championOverride: false,
    uploadFile: null,
    uploadDecisionPending: false,
    uploadClient: null,
    uploadChampion: false,
    uploadNotes: "",
    rule: null,
    position: "",
    projectRef: "",
    consentBlocksGeneration: false,
    consentToken: null,
    ...partial,
  });
}

describe("proces wybierany sam", () => {
  const a = recruitment({ stage_id: 1, job_id: 10 });
  const b = recruitment({ stage_id: 2, job_id: 20 });

  it("rekrutacja, z której otwarto generator, wygrywa", () => {
    expect(autoProcessChoice([a, b], 20)).toBe("2");
  });
  it("jedyny proces wybieramy sami, przy kilku decyduje rekruter", () => {
    expect(autoProcessChoice([a])).toBe("1");
    expect(autoProcessChoice([a, b])).toBe("");
  });
  it("osoba bez procesów ląduje na „Inny klient”", () => {
    expect(autoProcessChoice([])).toBe(OTHER_CLIENT_CHOICE);
  });
  it("prefill spoza listy procesów nie zgaduje innego", () => {
    expect(autoProcessChoice([a, b], 999)).toBe("");
  });
  it("etykieta: stanowisko · klient · etap", () => {
    expect(processLabel(a)).toBe("Senior Java Developer · PKO BP · Zweryfikowany");
    expect(processLabel(recruitment({ client_name: null }))).toContain("bez klienta");
  });
});

describe("domyślna obróbka i język", () => {
  it("Champion → Pod rekrutację, brak → Redakcja", () => {
    expect(defaultProcessingMode(true)).toBe("tailored");
    expect(defaultProcessingMode(false)).toBe("polished");
  });
  it("język wymuszony wygrywa i blokuje pozostałe opcje", () => {
    const policy = { forced: "en" as const, requiresBoth: true };
    expect(defaultLanguageChoice(policy)).toBe("en");
    expect(languageOptionEnabled("both", policy)).toBe(false);
    expect(languageOptionEnabled("pl", policy)).toBe(false);
    expect(languageOptionEnabled("en", policy)).toBe(true);
  });
  it("klient wymagający obu wersji ma domyślnie „Obie”", () => {
    expect(defaultLanguageChoice({ forced: null, requiresBoth: true })).toBe("both");
    expect(defaultLanguageChoice({ forced: null, requiresBoth: false })).toBe("pl");
  });
  it("„Obie” = język główny PL + languages=both", () => {
    expect(languagePayload("both")).toEqual({ language: "pl", languages: "both" });
    expect(languagePayload("en")).toEqual({ language: "en", languages: "one" });
  });
});

describe("braki do wygenerowania CV", () => {
  it("komplet z procesu = pusta lista", () => {
    expect(missing()).toEqual([]);
  });
  it("bez osoby prosi tylko o kandydata", () => {
    expect(missing({ candidateId: null })).toEqual(["Kandydat"]);
  });
  it("„Inny klient” wymaga klienta — zawsze", () => {
    expect(missing({ processChoice: OTHER_CLIENT_CHOICE, recruitment: null })).toEqual(["Klient"]);
    expect(missing({ processChoice: OTHER_CLIENT_CHOICE, recruitment: null, otherClient: { id: 3, name: "X" } })).toEqual([]);
  });
  it("kandydat bez pliku CV dostaje wskazówkę, gdzie go dodać", () => {
    expect(missing({ sourcesCount: 0, cvDocumentId: null })).toEqual([
      "Plik CV kandydata — dodaj go na profilu kandydata",
    ]);
  });
  it("notatka dopisana w miejscu liczy się do minimum klienta", () => {
    const needsNotes = recruitment({ notes_chars: 0, has_notes: false, required_notes_min_chars: 50, ready: false });
    expect(missing({ recruitment: needsNotes })[0]).toMatch(/co najmniej 50 znaków \(jest 0\)/);
    expect(missing({ recruitment: needsNotes, noteDraft: "x".repeat(60) })).toEqual([]);
  });
  it("Champion z pliku (tylko to CV) spełnia wymóg klienta", () => {
    const needsChampion = recruitment({ has_champion: false, required_champion: true, ready: false });
    expect(missing({ recruitment: needsChampion })).toContain("Profil Championa — ten klient go wymaga");
    expect(missing({ recruitment: needsChampion, championOverride: true })).toEqual([]);
  });
  it("osoba spoza bazy: plik → decyzja → klient", () => {
    const file = new File(["x"], "cv.pdf");
    const base = { flow: "upload" as const, candidateId: null };
    expect(missing(base)).toEqual(["Plik CV"]);
    expect(missing({ ...base, uploadFile: file, uploadDecisionPending: true })).toEqual([
      "Decyzja: dodać osobę do bazy czy generować bez dodawania",
    ]);
    expect(missing({ ...base, uploadFile: file })).toEqual(["Klient"]);
    expect(missing({ ...base, uploadFile: file, uploadClient: { id: 1, name: "A" } })).toEqual([]);
  });
  it("reguła klienta: numer projektu i stanowisko bez procesu", () => {
    const rule = { require_project_ref: true, require_position: true };
    const got = missing({ processChoice: OTHER_CLIENT_CHOICE, recruitment: null, otherClient: { id: 1, name: "A" }, rule });
    expect(got).toEqual([
      "Ten klient wymaga numeru projektu — uzupełnij pole „Numer / nazwa projektu”.",
      "Ten klient wymaga stanowiska — uzupełnij pole „Stanowisko”.",
    ]);
  });
  it("zrzut zgody blokuje wyłącznie przy regule spoza polityki centralnej", () => {
    expect(missing({ consentBlocksGeneration: true })).toEqual(["Zrzut zgody kandydata (RODO)"]);
    expect(missing({ consentBlocksGeneration: true, consentToken: "t" })).toEqual([]);
  });
  it("wczytywanie zasad klienta blokuje przycisk", () => {
    expect(missing({ policyPending: true })).toEqual(["Zasady CV klienta — wczytuję…"]);
  });
});

describe("treść żądania", () => {
  it("z procesu: stage_id, klient jako asercja, bez pustych pól", () => {
    expect(
      buildGeneratePayload({
        candidateId: 1,
        recruitment: recruitment(),
        otherClient: null,
        cvDocumentId: 5,
        projectRef: " ZOB/2026/114 ",
        language: "both",
        blind: false,
        contentMode: "tailored",
        position: "",
        championProfile: null,
        consentToken: null,
      }),
    ).toEqual({
      candidate_id: 1,
      stage_id: 11,
      client_id: 7,
      cv_document_id: 5,
      project_ref: "ZOB/2026/114",
      language: "pl",
      languages: "both",
      blind_cv: false,
      content_mode: "tailored",
    });
  });
  it("bez procesu: stage_id null, jawny klient, stanowisko i Champion z pliku", () => {
    const profile = { basics: {} } as never;
    const payload = buildGeneratePayload({
      candidateId: 2,
      recruitment: null,
      otherClient: { id: 15, name: "Polkomtel" },
      cvDocumentId: 9,
      projectRef: "",
      language: "en",
      blind: true,
      contentMode: "polished",
      position: "DevOps",
      championProfile: profile,
      consentToken: "tok",
    });
    expect(payload).toMatchObject({
      stage_id: null,
      client_id: 15,
      language: "en",
      languages: "one",
      blind_cv: true,
      position: "DevOps",
      champion_profile: profile,
      consent_screenshot_token: "tok",
    });
  });
  it("notatka bez procesu idzie w żądaniu, z procesem — nie (zapisuje się w rekrutacji)", () => {
    const base = {
      candidateId: 2,
      cvDocumentId: 9,
      projectRef: "",
      language: "pl" as const,
      blind: false,
      contentMode: "polished" as const,
      position: "",
      championProfile: null,
      consentToken: null,
      notes: "  stawka 150, klient A  ",
    };
    const noProcess = buildGeneratePayload({
      ...base,
      recruitment: null,
      otherClient: { id: 15, name: "Polkomtel" },
    });
    expect(noProcess.screening_notes).toBe("stawka 150, klient A");
    const withProcess = buildGeneratePayload({ ...base, recruitment: recruitment(), otherClient: null });
    expect(withProcess.screening_notes).toBeUndefined();
  });
  it("upload: klient wymagany w formularzu, profil tylko razem z plikiem Championa", () => {
    const cv = new File(["x"], "cv.pdf");
    const fd = buildUploadFormData({
      file: cv,
      client: { id: 3, name: "A" },
      projectRef: "",
      language: "both",
      blind: false,
      contentMode: "polished",
      position: "",
      notes: "  ",
      championFile: null,
      championProfile: { x: 1 } as never,
      consentToken: null,
    });
    expect(fd.get("cv_file")).toBe(cv);
    expect(fd.get("client_id")).toBe("3");
    expect(fd.get("languages")).toBe("both");
    expect(fd.get("screening_notes")).toBeNull();
    expect(fd.get("champion_profile_json")).toBeNull();
    expect(fd.get("must_requirements")).toBeNull();
  });
});

describe("pozostałe", () => {
  it("Zaawansowane rozwijają się same przy pustym wymaganym polu", () => {
    expect(advancedNeedsAttention({ positionRequired: true, position: "", projectRefRequired: false, projectRef: "" })).toBe(true);
    expect(advancedNeedsAttention({ positionRequired: true, position: "QA", projectRefRequired: false, projectRef: "" })).toBe(false);
  });
  it("data na liście: dziś / wczoraj / dd.mm", () => {
    const now = new Date(2026, 8, 23, 14, 0);
    expect(formatCvListDate(new Date(2026, 8, 23, 12, 40).toISOString(), now)).toMatch(/^dziś 12:40$/);
    expect(formatCvListDate(new Date(2026, 8, 22, 16, 2).toISOString(), now)).toMatch(/^wczoraj 16:02$/);
    expect(formatCvListDate(new Date(2026, 8, 19, 9, 0).toISOString(), now)).toBe("19.09");
    expect(formatCvListDate(null, now)).toBe("");
  });
});
