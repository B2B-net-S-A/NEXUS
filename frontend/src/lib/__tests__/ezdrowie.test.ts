import { describe, expect, it } from "vitest";

import {
  executiveContractOptionLabel,
  executiveContractSelectGroups,
  type ContractStructureResponse,
  type ExecutiveContractRead,
} from "@/lib/api/executiveContracts";
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

describe("executiveContractSelectGroups — bieżąca zakończona umowa zostaje w selekcie", () => {
  const structure: ContractStructureResponse = {
    framework_contracts: [
      {
        id: 2,
        name: "CeZ/145/2025 – cz. II",
        project_part: "cz2",
        status: "active",
        executive_contracts: [
          ec({ id: 10, number: "UW-1", status: "active" }),
          ec({ id: 11, number: "UW-2", status: "ended" }),
          ec({ id: 12, number: "UW-3", status: "ended" }),
        ],
      },
      {
        id: 4,
        name: "CeZ/147/2025 – cz. IV",
        project_part: "cz4",
        status: "active",
        executive_contracts: [ec({ id: 20, number: "UW-9", status: "ended", framework_contract_id: 4 })],
      },
    ],
  };

  function ec(overrides: Partial<ExecutiveContractRead>): ExecutiveContractRead {
    return {
      id: 1,
      number: "UW",
      status: "active",
      framework_contract_id: 2,
      project_part: "cz2",
      notes: null,
      consultants_count: 0,
      created_at: null,
      ...overrides,
    };
  }

  it("bez bieżącej umowy — tylko aktywne, część bez aktywnej znika", () => {
    const groups = executiveContractSelectGroups(structure, null);
    expect(groups.map((g) => g.options.map((o) => o.id))).toEqual([[10]]);
  });

  it("bieżąca zakończona umowa jest w opcjach, inne zakończone nadal odpadają", () => {
    const groups = executiveContractSelectGroups(structure, 11);
    expect(groups.map((g) => g.options.map((o) => o.id))).toEqual([[10, 11]]);
    // Część IV ma tylko zakończone umowy, żadna nie jest bieżąca — bez grupy.
    expect(groups.map((g) => g.framework_contract_id)).toEqual([2]);
    // Bieżąca zakończona w części bez aktywnej umowy odzyskuje swoją grupę.
    expect(
      executiveContractSelectGroups(structure, 20).map((g) => g.options.map((o) => o.id)),
    ).toEqual([[10], [20]]);
  });

  it("etykieta: dopisek „(zakończona)” wyłącznie przy zakończonej", () => {
    expect(executiveContractOptionLabel(ec({ number: "UW-1", status: "active" }))).toBe("UW-1");
    expect(executiveContractOptionLabel(ec({ number: "UW-2", status: "ended" }))).toBe(
      "UW-2 (zakończona)",
    );
  });
});
