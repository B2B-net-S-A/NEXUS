import { describe, expect, it } from "vitest";

import {
  EZDROWIE_CLIENT_ID,
  PART_ROMAN,
  PROJECT_PARTS,
  filterConsultantsByExecutiveContract,
  filterConsultantsByPart,
  isEzdrowieClient,
  isSameAssignmentFilter,
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

describe("ezdrowie — umowy wykonawcze (struktura umów)", () => {
  const consultants = [
    { id: 1, executive_contract: { id: 10 } },
    { id: 2, executive_contract: { id: 11 } },
    { id: 3, executive_contract: null }, // legacy: sprzed wdrożenia struktury
    { id: 4 }, // odpowiedź bez pola — traktowana jak NULL
  ];

  it("PART_ROMAN pokrywa dokładnie słownik części", () => {
    expect(Object.keys(PART_ROMAN).sort()).toEqual(
      PROJECT_PARTS.map((p) => p.value).sort(),
    );
    expect(PART_ROMAN.cz2).toBe("II");
    expect(PART_ROMAN.cz6).toBe("VI");
  });

  it("'all' = pełna lista, także osoby bez przypisania", () => {
    expect(filterConsultantsByExecutiveContract(consultants, "all")).toHaveLength(4);
  });

  it("'unassigned' = wyłącznie NULL (i brak pola)", () => {
    expect(
      filterConsultantsByExecutiveContract(consultants, "unassigned").map((c) => c.id),
    ).toEqual([3, 4]);
  });

  it("konkretna umowa zawęża do jej konsultantów; NULL nigdy tam nie trafia", () => {
    const hit = filterConsultantsByExecutiveContract(consultants, {
      executiveContractId: 10,
    });
    expect(hit.map((c) => c.id)).toEqual([1]);
    expect(
      filterConsultantsByExecutiveContract(consultants, { executiveContractId: 99 }),
    ).toHaveLength(0);
  });

  it("isSameAssignmentFilter porównuje po wartości, nie po referencji", () => {
    expect(isSameAssignmentFilter("all", "all")).toBe(true);
    expect(isSameAssignmentFilter("all", "unassigned")).toBe(false);
    expect(
      isSameAssignmentFilter({ executiveContractId: 1 }, { executiveContractId: 1 }),
    ).toBe(true);
    expect(
      isSameAssignmentFilter({ executiveContractId: 1 }, { executiveContractId: 2 }),
    ).toBe(false);
    expect(isSameAssignmentFilter({ executiveContractId: 1 }, "unassigned")).toBe(
      false,
    );
  });
});
