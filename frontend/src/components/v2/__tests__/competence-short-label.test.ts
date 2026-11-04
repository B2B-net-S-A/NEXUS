import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({
  default: {},
  competenceCategoriesApi: { list: vi.fn() },
}));

import { competenceShortLabel } from "@/components/v2/CompetenceCategoryBadge";

describe("competenceShortLabel", () => {
  it("cztery kategorie mają krótkie nazwy", () => {
    expect(competenceShortLabel("infrastructure_operations")).toBe("Infra");
    expect(competenceShortLabel("software_development")).toBe("Dev");
    expect(competenceShortLabel("security_quality")).toBe("QA");
    expect(competenceShortLabel("management_delivery")).toBe("PM & BA");
  });

  it("wycofane „Dane i AI” należy dziś do Infry — tak jak kolor plakietki", () => {
    expect(competenceShortLabel("data_ai")).toBe("Infra");
  });

  it("nieznany slug i brak slugu dają null — wołający pokazuje pełną nazwę", () => {
    expect(competenceShortLabel("marketing")).toBeNull();
    expect(competenceShortLabel("")).toBeNull();
    expect(competenceShortLabel(null)).toBeNull();
    expect(competenceShortLabel(undefined)).toBeNull();
    // Nazwa z prototypu obiektu nie może udawać kategorii.
    expect(competenceShortLabel("constructor")).toBeNull();
  });
});
