import { describe, expect, it } from "vitest";
import {
  candidateGridLayout,
  selectableCandidateColumns,
  toggleCandidateColumn,
  visibleCandidateColumns,
  withStageMatchColumn,
} from "@/lib/candidate-table-columns";

const ids = (hidden: string[] | null) => visibleCandidateColumns(hidden).map((c) => c.id);

describe("kolumny tabeli kandydatów", () => {
  it("domyślnie ukrywa dodatkowe kolumny", () => {
    expect(ids(null)).toEqual([
      "candidate",
      "position",
      "phone",
      "rate",
      "availability",
      "process",
      "cv",
      "assign",
    ]);
  });

  it("„Ostatniego odrzucenia” nie ma od 18.11.2026 — ani domyślnie, ani w „Kolumny”", () => {
    // Stary cytat wyglądał w niej na dzisiejszy; dwie ostatnie informacje
    // o osobie są w linii „Ostatnio z osobą” pod wierszem.
    const at = (hidden: string[] | null, options: { wide?: boolean; forJob?: boolean }) =>
      visibleCandidateColumns(hidden, options).map((c) => c.id as string);
    expect(at(null, { wide: true })).not.toContain("last_rejection");
    expect(selectableCandidateColumns().map((c) => c.id as string)).not.toContain("last_rejection");
    // Szeroki ekran ma te same kolumny domyślne co laptop.
    expect(at(null, { wide: true })).toEqual(at(null, {}));
  });

  it("zapisany wybór z dawną kolumną i jej znacznikami działa dalej, a kolejne przełączenie je zdejmuje", () => {
    const saved = ["email", "last_rejection", "last_rejection:hidden", "last_rejection:shown"];
    expect(ids(saved)).toEqual(ids(["email"]));
    expect(toggleCandidateColumn(saved, "location")).toEqual(["email", "location"]);
  });

  it("kolumn wymaganych nie da się ukryć, nieznane id są ignorowane", () => {
    expect(ids(["candidate", "assign", "nieznana"])).toContain("candidate");
    expect(ids(["candidate", "assign"])).toContain("assign");
  });

  it("przełączenie dokłada i zdejmuje kolumnę", () => {
    const withEmail = toggleCandidateColumn(null, "email");
    expect(ids(withEmail)).toContain("email");
    const withoutPhone = toggleCandidateColumn(withEmail, "phone");
    expect(ids(withoutPhone)).not.toContain("phone");
    expect(toggleCandidateColumn(withoutPhone, "phone")).not.toContain("phone");
  });

  it("szablon siatki ma kolumnę zaznaczenia, a minimalna szerokość liczy kolumny, odstępy i padding", () => {
    const layout = candidateGridLayout(visibleCandidateColumns(null));
    expect(layout.template.startsWith("32px ")).toBe(true);
    // 8 kolumn danych → 8 odstępów gap-3 (12 px) + px-4 z obu stron (32 px).
    // Bez odstępów i paddingu wiersz był szerszy od kontenera i ucinał „Przypisz”.
    expect(layout.minWidth).toBe(32 + 168 + 150 + 132 + 72 + 88 + 112 + 52 + 104 + 8 * 12 + 32);
  });
});

describe("„Szukaj ręcznie” z rekrutacji", () => {
  it("ma kolumnę dopasowania, a telefon domyślnie schowany — tabela mieści się w oknie", () => {
    const forJob = visibleCandidateColumns(null, { forJob: true }).map((c) => c.id);
    expect(forJob).toContain("fit");
    expect(forJob).not.toContain("phone");
    expect(ids(null)).not.toContain("fit");
    expect(candidateGridLayout(visibleCandidateColumns(null, { forJob: true })).minWidth).toBeLessThanOrEqual(1040);
  });
});

describe("„Dodany na etap” (filtr etapu, 19.10.2026)", () => {
  it("nie ma jej w wyborze „Kolumny” ani bez filtra", () => {
    expect(selectableCandidateColumns().map((c) => c.id)).not.toContain("stage_match");
    expect(ids(null)).not.toContain("stage_match");
    expect(withStageMatchColumn(visibleCandidateColumns(null), false).map((c) => c.id)).toEqual(
      ids(null),
    );
  });

  it("z filtrem stoi za „Kandydatem”; na laptopie w miejscu „Ostatniego stanowiska” i tabela dalej się mieści", () => {
    const laptop = withStageMatchColumn(visibleCandidateColumns(null), true);
    expect(laptop.map((c) => c.id)).toEqual([
      "candidate",
      "stage_match",
      "phone",
      "rate",
      "availability",
      "process",
      "cv",
      "assign",
    ]);
    expect(candidateGridLayout(laptop).minWidth).toBeLessThanOrEqual(
      candidateGridLayout(visibleCandidateColumns(null)).minWidth,
    );
    const wide = withStageMatchColumn(visibleCandidateColumns(null, { wide: true }), true, {
      wide: true,
    }).map((c) => c.id);
    expect(wide.slice(0, 3)).toEqual(["candidate", "stage_match", "position"]);
  });
});
