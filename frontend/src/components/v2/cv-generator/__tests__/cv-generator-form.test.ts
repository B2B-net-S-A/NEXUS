import { describe, expect, it } from "vitest";

import type { ChampionProfile } from "@/lib/api";
import type { RecruitmentOption } from "@/lib/cv-generator";

import {
  NO_RECRUITMENT_MISSING,
  advancedNeedsAttention,
  autoProcessChoice,
  buildGeneratePayload,
  championImportPayload,
  defaultCvSourceId,
  defaultLanguageChoice,
  defaultProcessingMode,
  languageOptionEnabled,
  languagePayload,
  missingInputs,
  cvFilenamePreview,
  processLabel,
  recruitmentPosition,
  typedCvPosition,
  type MissingInput,
} from "../cv-generator-form";
import previewCases from "@/lib/__fixtures__/cv-filename-preview-cases.json";

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
    policyPending: false,
    policyError: false,
    recruitment: recruitment(),
    recruitmentsLoading: false,
    recruitmentsError: false,
    recruitmentsCount: 1,
    cvDocumentId: 5,
    sourcesLoading: false,
    sourcesError: false,
    sourcesCount: 1,
    noteDraft: "",
    championOverride: false,
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
  it("osoba bez procesów nie ma czego wybrać — CV powstaje tylko w rekrutacji (13.10.2026)", () => {
    expect(autoProcessChoice([])).toBe("");
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
  it("przy kilku procesach trzeba wybrać jeden", () => {
    expect(missing({ recruitment: null, recruitmentsCount: 2 })).toEqual(["Proces rekrutacyjny"]);
  });
  it("osoba bez rekrutacji: CV nie powstanie, dopóki nie trafi do rekrutacji (13.10.2026)", () => {
    expect(missing({ recruitment: null, recruitmentsCount: 0 })).toEqual([NO_RECRUITMENT_MISSING]);
    expect(NO_RECRUITMENT_MISSING).toMatch(/rekrutacj/);
  });
  it("awaria listy procesów nie udaje osoby bez rekrutacji", () => {
    const got = missing({ recruitment: null, recruitmentsCount: 0, recruitmentsError: true });
    expect(got).toEqual(["Procesy kandydata — nie udało się ich wczytać, odśwież stronę."]);
  });
  it("awaria listy plików CV nie każe dodawać pliku, którego może nie brakować", () => {
    expect(missing({ sourcesError: true, sourcesCount: 0, cvDocumentId: null })).toEqual([
      "Pliki CV kandydata — nie udało się ich wczytać, odśwież stronę.",
    ]);
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
  it("reguła klienta: numer projektu wymagany także przy procesie", () => {
    const rule = { require_project_ref: true };
    expect(missing({ rule })).toEqual([
      "Ten klient wymaga numeru projektu — uzupełnij pole „Numer / nazwa projektu”.",
    ]);
    expect(missing({ rule, projectRef: "ZOB/2026/114" })).toEqual([]);
  });
  it("zrzut zgody blokuje wyłącznie przy regule spoza polityki centralnej", () => {
    expect(missing({ consentBlocksGeneration: true })).toEqual(["Zrzut zgody kandydata (RODO)"]);
    expect(missing({ consentBlocksGeneration: true, consentToken: "t" })).toEqual([]);
  });
  it("wczytywanie zasad klienta blokuje przycisk", () => {
    expect(missing({ policyPending: true })).toEqual(["Zasady CV klienta — wczytuję…"]);
  });
  it("„Z czego powstało” w trakcie wczytywania blokuje przycisk (awaria — nie)", () => {
    expect(missing({ aiSourcesLoading: true })).toEqual(["Źródła dla AI — wczytuję…"]);
    expect(missing({ aiSourcesLoading: false })).toEqual([]);
  });
});

describe("treść żądania", () => {
  it("z procesu: stage_id, klient jako asercja, bez pustych pól", () => {
    expect(
      buildGeneratePayload({
        candidateId: 1,
        recruitment: recruitment(),
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
  it("stanowisko, Champion z pliku i zrzut zgody jadą w żądaniu, notatka nie (zapisuje się w rekrutacji)", () => {
    const profile = { basics: {} } as never;
    const payload = buildGeneratePayload({
      candidateId: 2,
      recruitment: recruitment(),
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
      stage_id: 11,
      client_id: 7,
      language: "en",
      languages: "one",
      blind_cv: true,
      position: "DevOps",
      champion_profile: profile,
      consent_screenshot_token: "tok",
    });
    expect(payload.screening_notes).toBeUndefined();
    // Bez wczytanych przełączników serwer bierze domyślne — pola nie ma.
    expect(payload).not.toHaveProperty("sources");
  });
  it("przełączniki „Z czego powstało” jadą jako `sources`", () => {
    const sources = { answers: false, notes: true, transcripts: true, prep: false };
    const payload = buildGeneratePayload({
      candidateId: 2,
      recruitment: recruitment(),
      cvDocumentId: 9,
      projectRef: "",
      language: "pl",
      blind: false,
      contentMode: "tailored",
      position: "",
      championProfile: null,
      consentToken: null,
      sources,
    });
    expect(payload.sources).toEqual(sources);
    expect(payload.sources).not.toBe(sources);
  });
});

describe("pozostałe", () => {
  it("Zaawansowane rozwijają się same przy pustym wymaganym polu", () => {
    expect(advancedNeedsAttention({ positionRequired: true, position: "", projectRefRequired: false, projectRef: "" })).toBe(true);
    expect(advancedNeedsAttention({ positionRequired: true, position: "QA", projectRefRequired: false, projectRef: "" })).toBe(false);
  });
});

describe("zapis Championa z dokumentu", () => {
  it("wysyła tylko niepuste pola i nigdy notatek zespołu", () => {
    const profile = {
      basics: { role_name: "Java Developer", rate_value: null, rate_raw: "", language: "  " },
      stack: { must: [{ name: "Java" }], nice: [], notes: "" },
      project: { about: "", responsibilities: "" },
      screening_questions: [],
      insights: [],
      client_history: { status: "ok" },
      verification: { status: "done" },
      intake: { unresolved: {}, template_version: "v5" },
      _source: "champion_upload",
    } as unknown as ChampionProfile;
    expect(championImportPayload(profile)).toEqual({
      basics: { role_name: "Java Developer" },
      stack: { must: [{ name: "Java" }] },
      intake: { template_version: "v5" },
      _source: "champion_upload",
    });
  });
});

describe("defaultCvSourceId", () => {
  const file = (id: number, filename: string, is_primary = false) => ({ id, filename, is_primary });

  it("główne CV kandydata wygrywa z kolejnością listy", () => {
    expect(defaultCvSourceId([file(1, "stare.docx"), file(2, "glowne.pdf", true)])).toBe(2);
  });

  it("firmowy Word jako główny ustępuje pierwszemu z listy serwera", () => {
    expect(defaultCvSourceId([file(1, "cv.pdf"), file(2, "B2B_Jan.docx", true)])).toBe(1);
  });

  it("sam firmowy plik zostaje, a pusta lista to brak wyboru", () => {
    expect(defaultCvSourceId([file(2, "B2B_Jan.docx", true)])).toBe(2);
    expect(defaultCvSourceId([])).toBeNull();
  });
});

describe("stanowisko i nazwa pliku w formularzu", () => {
  it.each(previewCases.typed)("wpisane „$value” bez numeru klienta", ({ value, reference, expected }) => {
    expect(typedCvPosition(value, reference)).toBe(expected);
  });

  it.each(previewCases.filename)("plik $expected", ({ pattern, spaces, position, project, name, expected }) => {
    expect(
      cvFilenamePreview({ pattern, spacesToUnderscores: spaces, position, project, candidateName: name }),
    ).toBe(expected);
  });

  it("bez wzoru klienta nie ma podglądu", () => {
    expect(
      cvFilenamePreview({ pattern: null, spacesToUnderscores: false, position: "QA", project: "", candidateName: "A B" }),
    ).toBeNull();
  });

  it("pole pokazuje rolę z rekrutacji, a serwer sprzed zmiany daje nazwę od klienta", () => {
    expect(recruitmentPosition(recruitment({ cv_position: "Senior Java Developer" }))).toBe("Senior Java Developer");
    expect(recruitmentPosition(recruitment({ job_title: "ZOB-1 Java", cv_position: undefined }))).toBe("ZOB-1 Java");
    expect(recruitmentPosition(recruitment({ cv_position: "" }))).toBe("");
  });

  it("nazwa usługi bez roli w Championie: bez stanowiska nie ma generacji", () => {
    expect(missing({ recruitment: recruitment({ cv_position: "" }), position: "" })).toContain("Stanowisko");
    expect(missing({ recruitment: recruitment({ cv_position: "" }), position: "QA" })).not.toContain("Stanowisko");
    expect(missing({ recruitment: recruitment({ cv_position: "QA" }), position: "" })).not.toContain("Stanowisko");
  });

  it("lista procesów nazywa rekrutację jak jej nagłówek", () => {
    expect(
      processLabel(recruitment({
        job_title: "ZOB-3103 usługi programistyczne",
        job_working_title: "Senior Fullstack Developer · C#",
        job_client_reference: "ZOB-3156",
      })),
    ).toBe("ZOB-3156 Senior Fullstack Developer · C# · Zweryfikowany");
  });
});
