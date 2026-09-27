import { describe, expect, it } from "vitest";
import { entrySourceLabel, recruitmentStageLabel } from "@/lib/recruitment-stage-label";
import { cardStageBadge } from "@/lib/board-card-badges";

const raw = (stage: string | null | undefined) =>
  stage === "rejected" ? "Odrzucony" : stage === "posting" ? "Ogłoszenia" : String(stage);

describe("runda 10 (F04) — etap i źródło rekrutacji na profilu", () => {
  it("ręczne przypisanie na etapie „Ogłoszenia” profil nazywa jak Tablica: „Nowi”", () => {
    expect(recruitmentStageLabel("posting", "Ogłoszenia", raw)).toBe("Nowi");
    expect(recruitmentStageLabel("posting", null, raw)).toBe("Nowi");
  });

  it("etap QC z kodem interview trafia do „QC CV” po nazwie, jak na Tablicy", () => {
    expect(recruitmentStageLabel("interview", "QC CV", raw)).toBe("QC CV");
    expect(recruitmentStageLabel("interview", "Przepuszczony przez DZ", raw)).toBe("QC CV");
  });

  it("zamknięci zachowują własną etykietę (Odrzucony), nie „Zamknięci”", () => {
    expect(recruitmentStageLabel("rejected", "Odrzucony", raw)).toBe("Odrzucony");
  });

  it("źródło z procesu, nie z nazwy etapu", () => {
    expect(entrySourceLabel("added_manual")).toBe("Dodany ręcznie");
    expect(entrySourceLabel("application")).toBe("Z ogłoszenia");
    expect(entrySourceLabel(null)).toBeNull();
    expect(entrySourceLabel("coś_nowego")).toBeNull();
  });

  it("karta nie mówi „Z ogłoszenia” osobie dodanej ręcznie", () => {
    expect(cardStageBadge({ entry_source: "added_manual" }, "posting")).toBeNull();
    expect(cardStageBadge({ entry_source: "application" }, "posting")).toBe("posting");
    // Proces sprzed 0352 (źródło nieznane) — zostaje dawny znacznik.
    expect(cardStageBadge({ entry_source: null }, "posting")).toBe("posting");
    expect(cardStageBadge({ entry_source: "added_manual" }, "prep")).toBe("prep");
  });
});
