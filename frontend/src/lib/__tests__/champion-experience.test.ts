import { describe, expect, it } from "vitest";

import { experienceCheckRows } from "@/components/v2/screening/ScreeningForm";
import {
  addExperienceItems,
  experienceToText,
  experienceItemLabel,
  hasExperience,
  readExperienceEvidence,
} from "@/lib/champion-experience";

describe("sekcja 4 — pozycje i etykiety", () => {
  it("dodawanie z tekstu dzieli po przecinku/średniku i pomija duplikaty bez wielkości liter", () => {
    const items = addExperienceItems([{ name: "ISTQB", level: "must" }], "istqb; PSD2, PCI DSS");
    expect(items.map((i) => i.name)).toEqual(["ISTQB", "PSD2", "PCI DSS"]);
  });

  it("lata pokazujemy tylko przy dziedzinie, z polską odmianą", () => {
    expect(experienceItemLabel("domains", { name: "płatności", level: "must", min_years: 2 })).toBe(
      "płatności · min. 2 lata",
    );
    expect(experienceItemLabel("domains", { name: "karty", level: "must", min_years: 5 })).toBe(
      "karty · min. 5 lat",
    );
    expect(experienceItemLabel("certifications", { name: "ISTQB", level: "must", min_years: 3 })).toBe(
      "ISTQB",
    );
    expect(hasExperience(undefined)).toBe(false);
  });

  it("plakietki czytają tylko poprawne wpisy `breakdown.experience`", () => {
    expect(readExperienceEvidence(undefined)).toEqual([]);
    expect(
      readExperienceEvidence({
        experience: [
          { kind: "domains", name: "płatności", level: "must", status: "met", source: "sektor w CV" },
          { kind: "domains", name: "zły", status: "missing" },
          null,
        ],
      }),
    ).toHaveLength(1);
  });
});

describe("screening — „Sprawdź w rozmowie”", () => {
  it("pozycje sekcji 4 łączą się z zapisanym werdyktem po rodzaju i nazwie", () => {
    const rows = experienceCheckRows(
      {
        experience: {
          domains: [{ name: "Płatności", level: "must", min_years: 2 }],
          certifications: [{ name: "ISTQB", level: "nice" }],
        },
      },
      [{ kind: "domains", name: "płatności", status: "confirmed" }],
    );
    expect(rows).toEqual([
      {
        kind: "domains",
        name: "Płatności",
        label: "Płatności · min. 2 lata",
        level: "must",
        status: "confirmed",
      },
      { kind: "certifications", name: "ISTQB", label: "ISTQB", level: "nice", status: "unknown" },
    ]);
  });

  it("profil bez sekcji 4 nie dokłada listy", () => {
    expect(experienceCheckRows({}, undefined)).toEqual([]);
  });
});

describe("okno „Uzgodnij profil” — sekcja 4 jako tekst", () => {
  it("znaczniki „(min. N lat)” i „(mile)” — gramatyka, którą czyta serwer", () => {
    expect(
      experienceToText([
        { name: "płatności kartowe", level: "must", min_years: 2 },
        { name: "e-commerce", level: "nice", min_years: null },
      ]),
    ).toBe("płatności kartowe (min. 2 lat)\ne-commerce (mile)");
    expect(experienceToText(undefined)).toBe("");
  });
});
