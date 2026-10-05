import { describe, expect, it } from "vitest";
import {
  entrySourceLabel,
  furthestBoardColumnLabel,
  recruitmentOutcome,
  recruitmentStageLabel,
  recruitmentStagePath,
} from "@/lib/recruitment-stage-label";
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
    expect(entrySourceLabel("added_manual")).toBeNull();
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

describe("ścieżka etapów i wynik zakończonego procesu (04.10.2026)", () => {
  const label = (stage: string | null | undefined) => `etap:${stage ?? "?"}`;

  it("układa ruchy od najstarszego i nie powtarza tej samej kolumny", () => {
    expect(
      recruitmentStagePath(
        [
          { stage: "hired", moved_at: "2026-09-20T10:00:00Z" },
          { stage: "hired", moved_at: "2026-09-19T10:00:00Z" },
          { stage: "cv_sent", moved_at: "2026-09-10T10:00:00Z" },
          { stage: "verified", moved_at: "2026-09-05T10:00:00Z" },
        ],
        label,
      ),
    ).toEqual(["Zweryfikowany", "CV wysłane", "Zatrudniony"]);
    expect(recruitmentStagePath(null, label)).toEqual([]);
  });

  it("najdalsza kolumna pomija zamkniętych", () => {
    expect(
      furthestBoardColumnLabel([
        { stage: "rejected" },
        { stage: "client_interview" },
        { stage: "verified" },
      ]),
    ).toBe("Rozmowa u klienta");
    expect(furthestBoardColumnLabel([{ stage: "rejected" }])).toBeNull();
  });

  it("wynik: zatrudnienie, odrzucenie, rezygnacja, zamknięta rekrutacja", () => {
    expect(recruitmentOutcome({ latest_stage: "hired" })).toEqual({
      label: "Zatrudniony",
      tone: "success",
    });
    expect(recruitmentOutcome({ latest_stage: "rejected" }).label).toBe("Odrzucony");
    expect(recruitmentOutcome({ latest_stage: "withdrawn" }).label).toBe("Zrezygnował");
    expect(recruitmentOutcome({ latest_stage: "verified", job_status: "closed" }).label).toBe(
      "Rekrutacja zamknięta",
    );
  });
});
