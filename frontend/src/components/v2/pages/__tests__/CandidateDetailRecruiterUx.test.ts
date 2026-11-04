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

  it("ma primary „Przypisz do rekrutacji”, obok „Dodaj notatkę” i „Nie odebrał”, i fokusuje kompozytor", () => {
    // Pasek osoby (E1, 13.10.2026): akcje w jednym rzędzie, „Przypisz” pierwsze.
    const assign = HEADER.indexOf("Przypisz do rekrutacji");
    const addNote = HEADER.indexOf("Dodaj notatkę");
    const noAnswer = HEADER.lastIndexOf("Nie odebrał");
    expect(assign).toBeGreaterThan(-1);
    expect(addNote).toBeGreaterThan(assign);
    expect(noAnswer).toBeGreaterThan(addNote);
    expect(ROOT).toContain("onAddNote: openNoteComposer");
    expect(NOTES).toContain("textareaRef={composerTextareaRef}");
    expect(ROOT).toContain('params.delete("compose")');
  });

  it("menu „⋯” zawiera akcje paska osoby — bez martwych pozycji (D1–D3, 13.10.2026)", () => {
    for (const label of [
      "Napisz maila",
      "Zaplanuj rozmowę",
      "Zaproś na prep",
      "Edytuj dane",
      "Tagi i pule",
      "Konflikty i weta",
      "Usuń profil",
    ]) {
      expect(HEADER).toContain(label);
    }
    expect(HEADER).toContain('aria-label="Więcej akcji"');
    // „Obserwuj” (0 przypięć), „Wrzuć na targ” (strona zdjęta 21.09),
    // „Korekta imienia” (w „Edytuj dane”) i „Generuj CV” (zakładka CV) zeszły.
    expect(HEADER).not.toMatch(/useCandidateWatch|onMarketplace|IdentityEditor|onGenerateCv/);
    expect(ROOT).not.toContain("AddToMarketplaceButton");
  });

  it("nie ma przycisku CloudTalk ani statusu sprawy kontaktu (D3 — 10 połączeń, 0 spraw)", () => {
    for (const gone of ["<CallButton", "ContactStatusBadge", "ContactOutcomeSheet", "useCloudTalkEnabled"]) {
      expect(ALL).not.toContain(gone);
    }
    // Pasek „Ocena ryzyka jest chwilowo niedostępna” — trasa nie zwraca 5xx.
    expect(ROOT).not.toContain("Ocena ryzyka jest chwilowo niedostępna");
  });

  it("ma JEDNĄ kartę AI: „W skrócie” na Przeglądzie, z tekstem z CV", () => {
    expect(PROFILE_TAB).toContain("cvSummary={candidate.ai_summary ?? null}");
    expect(PROFILE_TAB).toContain('variant="compact"');
    expect(occurrences("<CandidateActivitySummaryCard")).toBe(1);
    expect(ALL).not.toContain("CandidateNotesInsightsCard");
    // Dawna karta „Screeningi” czytała nieużywaną tabelę notatek
    // screeningowych (ostatni wpis 15.04.2026) — usunięta 02.10.2026.
    // Pełna nazwa: okno „Screening” z 09.10.2026 (`ScreeningSummaryDialog`)
    // czyta stan formularza pary i jest inną rzeczą.
    expect(ALL).not.toContain("ScreeningSummaryCard");
  });

  it("odpowiedzi z rozmów screeningowych mają własną zakładkę", () => {
    // Zgłoszenie 02.10.2026: po przejściu wszystkich etapów profil nie
    // pokazywał, co kandydat odpowiedział na pytania screeningowe. Od
    // 04.10.2026 zakładka (od 13.10.2026 „Screening”) między Rekrutacjami
    // a Notatkami.
    expect(occurrences("<CandidateScreeningAnswersCard")).toBe(1);
    expect(ROOT).toMatch(/value="screening"[\s\S]{0,200}<CandidateScreeningAnswersCard[^>]*variant="tab"/);
    const recruitments = ROOT.indexOf('value: "recruitments"');
    const screening = ROOT.indexOf('value: "screening"');
    const activity = ROOT.indexOf('value: "activity"');
    expect(screening).toBeGreaterThan(recruitments);
    expect(activity).toBeGreaterThan(screening);
  });

  it("zakładki nazywają się Przegląd · Rekrutacje · Screening · Notatki · CV · Dokumenty (13.10.2026)", () => {
    const labels = [
      'label: "Przegląd"',
      'label: "Rekrutacje"',
      'label: "Screening"',
      'label: "Notatki"',
      'label: "CV"',
      'label: "Dokumenty"',
    ];
    let last = -1;
    for (const label of labels) {
      const at = ROOT.indexOf(label);
      expect(at, label).toBeGreaterThan(last);
      last = at;
    }
    // Licznik Rekrutacji = procesy w toku (E6), nie wszystkie.
    expect(ROOT).toContain("splitRecruitments(history).active.length");
    // CV i Dokumenty to osobne zakładki (E5).
    expect(ROOT).toMatch(/value="cv"[\s\S]{0,200}<CvSkillsSection/);
    expect(ROOT).toMatch(/value="documents"[\s\S]{0,200}<FilesContractsTab/);
  });

  it("ustalenia z notatek otwiera linia w karcie „Do propozycji”, nie osobna karta", () => {
    expect(ROOT).toContain('data-help="candidate.profile.notes_facts"');
    expect(occurrences("<CandidateNotesFactsCard")).toBe(1);
    expect(read(`${PROFILE_DIR}/ProfileMenuDialogs.tsx`)).toContain("<CandidateNotesFactsCard");
  });

  it("nie montuje martwego ScreeningSheet", () => {
    expect(ALL).not.toContain("ScreeningSheet");
  });

  it("nie dubluje rekrutacji widżetem pipeline'ów ani panelem stawek", () => {
    expect(ALL).not.toContain("<CandidatePipelinesWidget");
    expect(ALL).not.toContain("SellRatePanel");
    // W toku + rozwinięcie wiersza tabeli zakończonych (tylko do odczytu).
    expect(occurrences("<RecruitmentCard")).toBe(2);
    expect(ALL).not.toContain("CandidateRecentRecruitmentsCard");
  });

  it("„Wróć do rekrutacji” otwiera dok tej osoby", () => {
    expect(HEADER).toContain("href={`/jobs/${backJobId}?candidate=${candidateId}`}");
  });

  it("oś czasu mówi o zdarzeniu, nie o rodzaju gramatycznym autora", () => {
    expect(TIMELINE).not.toMatch(/zmienił etap|przypisał do etapu|dodał notatkę/);
    expect(TIMELINE).toContain('"zmiana etapu" : "przypisanie do etapu"');
  });

  it("ma jeden kompozytor notatki — u góry „Notatek”", () => {
    expect(occurrences("<NoteComposer")).toBe(1);
    expect(HISTORY).toContain("<NoteComposer");
  });

  it("używa jednego stylu potwierdzenia (ConfirmV2)", () => {
    expect(ALL).not.toContain("<ConfirmModal");
    expect(ALL).not.toMatch(/window\.confirm/);
    expect(occurrences("<ConfirmV2")).toBeGreaterThanOrEqual(3);
  });

  it("wywołania nawigacji używają kanonicznych kluczy, nie starych zakładek", () => {
    expect(ALL).not.toMatch(/onOpenTab\??\(\s*"(pliki|timeline|rekrutacje|umowa|notatki)"/);
    expect(ALL).not.toContain("onOpenTab");
  });
});

describe("profil kandydata — każdy fakt w jednym miejscu", () => {
  it("lokalizacja, dostępność i stawka B2B żyją tylko w karcie „Do propozycji”", () => {
    // `formatCandidateLocation` i jednolinijkowiec z lokalizacją/dostępnością
    // wypisywały te fakty w nagłówku i w zakładce Profil obok paska faktów.
    expect(ALL).not.toContain("formatCandidateLocation");
    expect(ALL).not.toContain("getCandidateSummaryLine");
    expect(ALL).not.toContain("MapPin");
    // Jedyny wyjątek (D4, 13.10.2026): status „szuka aktywnie” jest pigułką
    // przy nazwisku — wiersz „Dostępność” w karcie pokazuje wtedy sam termin.
    expect(occurrences("availability_status")).toBe(
      occurrences("<AvailabilityPill status={candidate.availability_status}"),
    );
    expect(occurrences("<AvailabilityPill status={candidate.availability_status}")).toBe(1);
    expect(occurrences("<CandidateProfileFactsBar")).toBe(1);
    expect(ROOT).toContain('layout="proposal"');
  });

  it("Przegląd mówi „kim jest i co trzeba zrobić” — bez siatki faktów i osi czasu (E2)", () => {
    expect(PROFILE_TAB).not.toContain("FactTile");
    expect(PROFILE_TAB).not.toContain("timeline(");
    expect(PROFILE_TAB).not.toContain("Firmy z CV");
    expect(PROFILE_TAB).toContain("Do zrobienia");
    expect(PROFILE_TAB).toContain("recruitmentsAwaitingUs");
    expect(PROFILE_TAB).toContain("Ostatnia rozmowa");
    // Oś czasu ładuje się dopiero w „Notatkach i historii”.
    expect(ROOT).not.toContain("/timeline?limit=");
    expect(HISTORY).toContain("/timeline?limit=");
  });

  it("Rekrutacje: jedna sekcja „Pasujące rekrutacje”, liczona dopiero po „Pokaż” (D5, 13.10.2026)", () => {
    const recruitments = read(`${PROFILE_DIR}/RecruitmentsTab.tsx`);
    expect(recruitments).not.toContain("data-commercial-slot");
    expect(ALL).not.toContain("<RateHistorySummary");
    // Rekomendacje montowane warunkowo — bez zapytania przy wejściu w zakładkę.
    expect(recruitments).toMatch(/suggestedOpen \? \([\s\S]{0,400}<SuggestedJobsWidget/);
    // Dawna osobna sekcja „Dopasowanie do rekrutacji” zeszła do wiersza.
    expect(recruitments).not.toContain('id="candidate-matching-section"');
    expect(recruitments).toContain("Ocena dopasowania");
  });

  it("puste stany kart rekrutacji nie krzyczą „Brandowane: brak”", () => {
    expect(ALL).not.toContain("Brandowane: brak");
    expect(ALL).not.toContain("Brak draftu. Draft tworzy się");
  });

  it("„Następny/Poprzedni” podmieniają adres, a powrót prowadzi do wyszukiwania (28.10.2026)", () => {
    // `push` dokładał krok historii na każdy profil — „Wstecz” cofał po jednym.
    const nav = ROOT.slice(ROOT.indexOf("const navOnNavigate"), ROOT.indexOf("const candidateNav ="));
    expect(nav).toContain("router.replace(`/candidates/${next.candidateId}");
    expect(nav).not.toContain("router.push(");
    expect(nav).toContain("withJobSearchBackRef");
    expect(ROOT).toContain("`/jobs/${backJobSearchId}?win=add&wintab=manual`");
    expect(ROOT).toContain("listBackHref(urlNav.filters)");
  });
});
