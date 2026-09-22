import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * `CandidateDetailV2` nie ma testu renderującego (ciężki komponent z kilkunastoma
 * zapytaniami), więc kontrakty UX profilu pilnujemy na źródle — wzorzec
 * `CandidateFormRemoteModeContract.test.tsx`. Od 09.2026 treść zakładek żyje
 * w `components/v2/candidate-profile/*`, a `CandidateDetailV2.tsx` jest
 * orkiestratorem.
 */
const SRC = join(process.cwd(), "src");
const read = (relative: string) => readFileSync(join(SRC, relative), "utf-8");

const ROOT = read("components/v2/pages/CandidateDetailV2.tsx");
const PROFILE_DIR = "components/v2/candidate-profile";
const PROFILE_FILES = readdirSync(join(SRC, PROFILE_DIR))
  .filter((name) => name.endsWith(".tsx") || name.endsWith(".ts"))
  .map((name) => ({ name, source: read(`${PROFILE_DIR}/${name}`) }));
const HEADER = read(`${PROFILE_DIR}/ProfileHeader.tsx`);
const NOTES = read(`${PROFILE_DIR}/Notes.tsx`);
const HISTORY = read(`${PROFILE_DIR}/HistoryTab.tsx`);
const PROFILE_TAB = read(`${PROFILE_DIR}/ProfileTab.tsx`);
const TIMELINE = read(`${PROFILE_DIR}/Timeline.tsx`);
const ALL = [ROOT, ...PROFILE_FILES.map((file) => file.source)].join("\n");

/** Ile plików profilu (orkiestrator + zakładki) zawiera dany fragment. */
function occurrences(fragment: string | RegExp): number {
  const sources = [ROOT, ...PROFILE_FILES.map((file) => file.source)];
  return sources.reduce((total, source) => {
    const matches =
      typeof fragment === "string"
        ? source.split(fragment).length - 1
        : (source.match(new RegExp(fragment.source, `${fragment.flags}g`)) ?? []).length;
    return total + matches;
  }, 0);
}

describe("profil kandydata — kontrakt zmian UX rekrutera", () => {
  it("orkiestrator jest mały — zakładki żyją w osobnych plikach", () => {
    expect(ROOT.split("\n").length).toBeLessThan(1200);
    for (const file of [
      "ProfileHeader.tsx",
      "ProfileTab.tsx",
      "RecruitmentsTab.tsx",
      "HistoryTab.tsx",
      "FilesContractsTab.tsx",
    ]) {
      expect(PROFILE_FILES.map((f) => f.name)).toContain(file);
    }
  });

  it("ma „Dodaj notatkę” obok primary „Przypisz do rekrutacji” i fokusuje kompozytor", () => {
    const addNote = HEADER.indexOf("Dodaj notatkę");
    const assign = HEADER.indexOf("Przypisz do rekrutacji");
    expect(addNote).toBeGreaterThan(-1);
    expect(assign).toBeGreaterThan(addNote);
    expect(ROOT).toContain("onAddNote: openNoteComposer");
    expect(NOTES).toContain("textareaRef={composerTextareaRef}");
    expect(ROOT).toContain('params.delete("compose")');
  });

  it("menu „⋯” zawiera wszystkie akcje nagłówka", () => {
    for (const label of [
      "Napisz maila",
      "Zaplanuj rozmowę",
      "Zaproś na prep",
      "Generuj CV",
      "Edytuj dane",
      "Wrzuć na targ",
      "Usuń profil",
    ]) {
      expect(HEADER).toContain(label);
    }
    expect(HEADER).toContain('aria-label="Więcej akcji"');
  });

  it("pokazuje CallButton tylko przy włączonym CloudTalku", () => {
    expect(HEADER).toMatch(/canWrite && canCall \? \(\s*<CallButton/);
  });

  it("ma JEDNĄ kartę AI: „Podsumowanie” z akapitem z CV", () => {
    expect(PROFILE_TAB).toContain("cvSummary={candidate.ai_summary ?? null}");
    expect(PROFILE_TAB).toContain('title="Podsumowanie"');
    expect(occurrences("<CandidateActivitySummaryCard")).toBe(1);
    expect(ALL).not.toContain("CandidateNotesInsightsCard");
    // Dawna, przyklejona karta „Podsumowanie screeningów” nie wraca na zakładkę
    // Profil. Wynik screeningów (dane strukturalne, nie AI) jest jedną
    // kompaktową kartą na zakładce Rekrutacje — screening dotyczy procesu.
    expect(PROFILE_TAB).not.toContain("ScreeningSummary");
    expect(occurrences("<ScreeningSummaryCard")).toBe(1);
    expect(read(`${PROFILE_DIR}/RecruitmentsTab.tsx`)).toContain("<ScreeningSummaryCard");
  });

  it("nie montuje martwego ScreeningSheet", () => {
    expect(ALL).not.toContain("ScreeningSheet");
  });

  it("nie dubluje rekrutacji widżetem pipeline'ów ani panelem stawek", () => {
    expect(ALL).not.toContain("<CandidatePipelinesWidget");
    expect(ALL).not.toContain("SellRatePanel");
    expect(occurrences("<RecruitmentCard")).toBe(2); // aktywne + zakończone
    expect(occurrences("<CandidateRecentRecruitmentsCard")).toBe(1);
  });

  it("„Wróć do rekrutacji” otwiera dok tej osoby", () => {
    expect(HEADER).toContain("href={`/jobs/${backJobId}?candidate=${candidateId}`}");
  });

  it("oś czasu mówi o zdarzeniu, nie o rodzaju gramatycznym autora", () => {
    expect(TIMELINE).not.toMatch(/zmienił etap|przypisał do etapu|dodał notatkę/);
    expect(TIMELINE).toContain('"zmiana etapu" : "przypisanie do etapu"');
  });

  it("ma jeden kompozytor notatki — u góry Historii", () => {
    expect(occurrences("<NoteComposer")).toBe(1);
    expect(HISTORY).toContain("<NoteComposer");
  });

  it("używa jednego stylu potwierdzenia (ConfirmV2)", () => {
    expect(ALL).not.toContain("<ConfirmModal");
    expect(ALL).not.toMatch(/window\.confirm/);
    expect(occurrences("<ConfirmV2")).toBeGreaterThanOrEqual(4);
  });

  it("wywołania nawigacji używają kanonicznych kluczy, nie starych zakładek", () => {
    expect(ALL).not.toMatch(/onOpenTab\??\(\s*"(pliki|timeline|rekrutacje|umowa|notatki)"/);
    expect(ALL).not.toContain("onOpenTab");
  });
});

describe("profil kandydata — każdy fakt w jednym miejscu", () => {
  it("lokalizacja, dostępność i stawka B2B żyją tylko w pasku faktów", () => {
    // `formatCandidateLocation` i jednolinijkowiec z lokalizacją/dostępnością
    // wypisywały te fakty w nagłówku i w zakładce Profil obok paska faktów.
    expect(ALL).not.toContain("formatCandidateLocation");
    expect(ALL).not.toContain("getCandidateSummaryLine");
    expect(ALL).not.toContain("MapPin");
    expect(ALL).not.toContain("availability_status");
    expect(occurrences("<CandidateProfileFactsBar")).toBe(1);
  });

  it("zakładka Profil nie ma siatki kluczowych faktów ani mini-feedu 5 zdarzeń", () => {
    expect(PROFILE_TAB).not.toContain("FactTile");
    expect(PROFILE_TAB).not.toContain("timeline(candidate.id, 5)");
    expect(PROFILE_TAB).not.toContain("Firmy z CV");
    expect(PROFILE_TAB).toContain("recentActivity.items.slice(0, 2)");
  });

  it("dane handlowe mają nagłówek tylko przy treści", () => {
    const recruitments = read(`${PROFILE_DIR}/RecruitmentsTab.tsx`);
    expect(recruitments).toContain("has-[[data-commercial-slot]>*]:block");
    expect(occurrences("<RateHistoryWidget")).toBe(1);
    expect(recruitments).toMatch(/<SuggestedJobsWidget[\s\S]{0,200}hideWhenEmpty/);
  });

  it("puste stany kart rekrutacji nie krzyczą „Brandowane: brak”", () => {
    expect(ALL).not.toContain("Brandowane: brak");
    expect(ALL).not.toContain("Brak draftu. Draft tworzy się");
  });
});
