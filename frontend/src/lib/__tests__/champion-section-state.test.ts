import { describe, expect, it } from "vitest";

import { EMPTY_CHAMPION_PROFILE, type ChampionProfile } from "@/lib/api";
import {
  CHAMPION_PROSE_SECTION_IDS,
  CHAMPION_SECTIONS,
  championSectionState,
  championSectionsEmptyCount,
  hasChampionAiProvenance,
} from "@/lib/champion-section-state";

const FILLED: ChampionProfile = {
  ...EMPTY_CHAMPION_PROFILE,
  basics: { ...EMPTY_CHAMPION_PROFILE.basics, role_name: "Senior Python Developer" },
  search: { ...EMPTY_CHAMPION_PROFILE.search, keywords: "python, fastapi" },
  stack: { must: [{ name: "Python" }], nice: [], notes: "" },
  project: { about: "Migracja platformy płatności.", responsibilities: "" },
  screening_questions: [
    { id: "q1", question: "Kafka?", ideal_answer: "tak", deal_breaker: "nie" },
  ],
  client: {
    ...EMPTY_CHAMPION_PROFILE.client,
    selling_points: "Greenfield, długi kontrakt.",
  },
};

describe("hasChampionAiProvenance", () => {
  it("false gdy brak profilu", () => {
    expect(hasChampionAiProvenance(null)).toBe(false);
    expect(hasChampionAiProvenance(undefined)).toBe(false);
  });

  it("false gdy profil nie niesie _source ani _parser", () => {
    expect(hasChampionAiProvenance(EMPTY_CHAMPION_PROFILE)).toBe(false);
    expect(hasChampionAiProvenance(FILLED)).toBe(false);
  });

  it("true gdy profil niesie _source (import z Traffita / champion_upload)", () => {
    expect(hasChampionAiProvenance({ ...FILLED, _source: "champion_upload" })).toBe(
      true,
    );
    expect(
      hasChampionAiProvenance({
        ...FILLED,
        _source: "traffit_recruitment_file:42",
      }),
    ).toBe(true);
  });

  it("true gdy profil niesie WYŁĄCZNIE _parser (bez _source)", () => {
    expect(
      hasChampionAiProvenance({ ...FILLED, _source: null, _parser: "v6" }),
    ).toBe(true);
  });
});

describe("championSectionState", () => {
  it("pusty profil (bez znacznika pochodzenia) — każda sekcja jest pusta", () => {
    for (const section of CHAMPION_SECTIONS) {
      expect(championSectionState(section.id, EMPTY_CHAMPION_PROFILE)).toBe("empty");
    }
  });

  it("wypełniony profil bez znacznika pochodzenia — każda wypełniona sekcja jest 'filled', nigdy 'ai'", () => {
    for (const section of CHAMPION_SECTIONS) {
      expect(championSectionState(section.id, FILLED)).toBe("filled");
    }
  });

  it("wypełniony profil ZE znacznikiem pochodzenia — każda wypełniona sekcja jest 'ai'", () => {
    const profile: ChampionProfile = { ...FILLED, _source: "champion_upload" };
    for (const section of CHAMPION_SECTIONS) {
      expect(championSectionState(section.id, profile)).toBe("filled");
    }
  });

  it("znacznik pochodzenia NIE zamienia pustej sekcji w 'ai' — pusta zostaje pusta", () => {
    const profile: ChampionProfile = {
      ...EMPTY_CHAMPION_PROFILE,
      basics: { ...EMPTY_CHAMPION_PROFILE.basics, role_name: "Senior Python Developer" },
      _source: "champion_upload",
    };
    expect(championSectionState("basics", profile)).toBe("filled");
    // Sekcje, których import nie dotknął, zostają puste — nie zgadujemy.
    expect(championSectionState("search", profile)).toBe("empty");
    expect(championSectionState("client", profile)).toBe("empty");
  });

  it("sekcja 'basics' liczy się jako wypełniona, gdy wypełnione jest choć jedno pole liczbowe (0 to legalna wartość)", () => {
    const profile: ChampionProfile = {
      ...EMPTY_CHAMPION_PROFILE,
      basics: { ...EMPTY_CHAMPION_PROFILE.basics, onsite_days_per_week: 0 },
    };
    expect(championSectionState("basics", profile)).toBe("filled");
  });

  it("sekcja 'search' liczy dyskwalifikatory jako wypełnienie, nawet bez słów kluczowych", () => {
    const profile: ChampionProfile = {
      ...EMPTY_CHAMPION_PROFILE,
      search: { ...EMPTY_CHAMPION_PROFILE.search, disqualifiers: ["brak polskiego"] },
    };
    expect(championSectionState("search", profile)).toBe("filled");
  });

  it("sekcja 'stack' liczy same notatki (bez pozycji must/nice) jako wypełnienie", () => {
    const profile: ChampionProfile = {
      ...EMPTY_CHAMPION_PROFILE,
      stack: { must: [], nice: [], notes: "Java 17+, Java 8 nie interesuje" },
    };
    expect(championSectionState("stack", profile)).toBe("filled");
  });

  it("sekcja 'client' liczy same branże (sectors) jako wypełnienie", () => {
    const profile: ChampionProfile = {
      ...EMPTY_CHAMPION_PROFILE,
      client: { ...EMPTY_CHAMPION_PROFILE.client, sectors: ["banking"] },
    };
    expect(championSectionState("client", profile)).toBe("filled");
  });

  it("CHAMPION_SECTIONS ma dokładnie sześć wpisów z unikalnymi kotwicami", () => {
    expect(CHAMPION_SECTIONS).toHaveLength(6);
    const anchors = new Set(CHAMPION_SECTIONS.map((s) => s.anchor));
    expect(anchors.size).toBe(6);
  });
});

describe("CHAMPION_SECTIONS — kolejność kroku 02", () => {
  it("kolejność jest robocza (1 · 3 · 2 · 4 · 5 · 6), numeracja szablonowa", () => {
    expect(CHAMPION_SECTIONS.map((s) => s.id)).toEqual([
      "basics",
      "stack",
      "search",
      "project",
      "screening_questions",
      "client",
    ]);
    // Etykieta drugiego wpisu niesie numer 3 — wiąże ekran ze wzorem Word,
    // po którym poruszają się Delivery Leadowie.
    expect(CHAMPION_SECTIONS[1].label.startsWith("3 · ")).toBe(true);
  });

  it("grupa „proza” to dokładnie sekcje 2 · 4 · 5, wszystkie obecne w CHAMPION_SECTIONS", () => {
    expect([...CHAMPION_PROSE_SECTION_IDS]).toEqual([
      "search",
      "project",
      "screening_questions",
    ]);
    const known = new Set(CHAMPION_SECTIONS.map((s) => s.id));
    for (const id of CHAMPION_PROSE_SECTION_IDS) {
      expect(known.has(id)).toBe(true);
    }
  });
});

describe("championSectionsEmptyCount", () => {
  it("pusty profil — wszystkie trzy sekcje grupy są puste", () => {
    expect(
      championSectionsEmptyCount(CHAMPION_PROSE_SECTION_IDS, EMPTY_CHAMPION_PROFILE),
    ).toBe(3);
  });

  it("wypełniony profil — zero pustych", () => {
    expect(championSectionsEmptyCount(CHAMPION_PROSE_SECTION_IDS, FILLED)).toBe(0);
  });

  it("liczy TĄ SAMĄ regułą co chip pojedynczej sekcji", () => {
    const profile: ChampionProfile = {
      ...EMPTY_CHAMPION_PROFILE,
      project: { about: "Migracja platformy płatności.", responsibilities: "" },
    };
    expect(championSectionsEmptyCount(CHAMPION_PROSE_SECTION_IDS, profile)).toBe(2);
    // Nagłówek grupy nie może twierdzić czegoś innego niż sekcja pod nim.
    expect(championSectionState("project", profile)).toBe("filled");
    expect(championSectionState("search", profile)).toBe("empty");
    expect(championSectionState("screening_questions", profile)).toBe("empty");
  });

  it("pusta lista sekcji daje zero (bez dzielenia przez nic)", () => {
    expect(championSectionsEmptyCount([], EMPTY_CHAMPION_PROFILE)).toBe(0);
  });
});
