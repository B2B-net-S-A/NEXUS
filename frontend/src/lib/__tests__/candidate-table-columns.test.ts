import { describe, expect, it } from "vitest";
import {
  candidateGridLayout,
  toggleCandidateColumn,
  visibleCandidateColumns,
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

  it("szeroki ekran pokazuje domyślnie także „Ostatnią rozmowę”; laptop i „Szukaj ręcznie” — nie", () => {
    const wide = visibleCandidateColumns(null, { wide: true }).map((c) => c.id);
    expect(wide).toContain("last_contact");
    // Laptop: domyślna tabela mieści się na styk, kolumna zostaje do włączenia.
    expect(ids(null)).not.toContain("last_contact");
    expect(
      visibleCandidateColumns(null, { forJob: true, wide: true }).map((c) => c.id),
    ).not.toContain("last_contact");
    // Zapisany wybór osoby wygrywa z domyślnym układem szerokiego ekranu.
    expect(
      visibleCandidateColumns(["last_contact"], { wide: true }).map((c) => c.id),
    ).not.toContain("last_contact");
    // Przełączenie innej kolumny na szerokim ekranie nie chowa „Ostatniej rozmowy”.
    const afterToggle = toggleCandidateColumn(null, "email", { wide: true });
    expect(afterToggle).not.toContain("last_contact");
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
