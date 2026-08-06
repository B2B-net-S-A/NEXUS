import { describe, expect, it } from "vitest";

import {
  EZDROWIE_CLIENT_ID,
  PROJECT_PARTS,
  filterConsultantsByPart,
  isEzdrowieClient,
  projectPartLabel,
} from "@/lib/ezdrowie";

describe("ezdrowie — części umowy (ticket #3)", () => {
  it("bramka po client_id, nie po nazwie", () => {
    expect(isEzdrowieClient(EZDROWIE_CLIENT_ID)).toBe(true);
    expect(isEzdrowieClient(12)).toBe(false);
    expect(isEzdrowieClient(null)).toBe(false);
    expect(isEzdrowieClient(undefined)).toBe(false);
  });

  it("słownik: 5 części, cz.3 celowo nie istnieje", () => {
    expect(PROJECT_PARTS.map((p) => p.value)).toEqual([
      "cz1",
      "cz2",
      "cz4",
      "cz5",
      "cz6",
    ]);
    expect(PROJECT_PARTS.some((p) => p.value === ("cz3" as string))).toBe(false);
  });

  it("etykieta PL z fallbackiem na surowy kod", () => {
    expect(projectPartLabel("cz2")).toBe("E-zdrowie cz.2");
    expect(projectPartLabel("nieznane")).toBe("nieznane");
    expect(projectPartLabel(null)).toBeNull();
  });

  it("filtr: 'all' = pełna lista; część zawęża; NULL tylko pod 'all'", () => {
    const consultants = [
      { id: 1, project_part: "cz2" },
      { id: 2, project_part: "cz4" },
      { id: 3, project_part: null }, // nieuzupełniony auto-draft
    ];
    expect(filterConsultantsByPart(consultants, "all")).toHaveLength(3);
    expect(filterConsultantsByPart(consultants, "cz2").map((c) => c.id)).toEqual([
      1,
    ]);
    expect(filterConsultantsByPart(consultants, "cz6")).toHaveLength(0);
    // Konsultant bez części NIE pokazuje się pod żadnym częściowym filtrem.
    expect(
      filterConsultantsByPart(consultants, "cz4").some((c) => c.id === 3),
    ).toBe(false);
  });
});
