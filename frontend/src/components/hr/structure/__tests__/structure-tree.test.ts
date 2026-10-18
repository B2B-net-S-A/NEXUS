import { describe, expect, it } from "vitest";

import type { HrStructure, StructurePerson } from "@/lib/api/hr-structure";
import { managerWords } from "@/lib/api/hr-structure";

import { buildStructure, flatten, leavingManagers } from "../structure-tree";

function person(
  user_id: number,
  name: string,
  extra: Partial<StructurePerson> = {},
): StructurePerson {
  return {
    user_id,
    name,
    email: `osoba${user_id}@example.com`,
    job_title: null,
    department: null,
    employment_type: "b2b",
    employment_status: "active",
    division: null,
    manager_user_id: null,
    manager_name: null,
    manager_state: "none",
    reports: 0,
    leaving: null,
    m365_hint: null,
    suggested_manager: null,
    ...extra,
  };
}

function structure(people: StructurePerson[], heads: Partial<Record<string, number>> = {}): HrStructure {
  const byId = new Map(people.map((p) => [p.user_id, p]));
  return {
    people,
    outside_managers: [],
    divisions: (["front_office", "back_office"] as const).map((key) => ({
      key,
      label: key === "front_office" ? "Front office" : "Back office",
      head_user_id: heads[key] ?? null,
      head_name: heads[key] ? (byId.get(heads[key]!)?.name ?? null) : null,
      head_active: Boolean(heads[key]),
    })),
    total: people.length,
    without_manager: 0,
    inactive_manager: 0,
    m365_mismatches: 0,
  };
}

const under = (manager: StructurePerson, extra: Partial<StructurePerson> = {}) => ({
  manager_user_id: manager.user_id,
  manager_name: manager.name,
  manager_state: "ok" as const,
  ...extra,
});

describe("drzewo Struktury", () => {
  const head = person(1, "Paweł Przykładowy", { division: "front_office", reports: 1 });
  const lead = person(2, "Marta Fikcyjna", {
    division: "front_office",
    reports: 2,
    ...under(head),
  });
  const ola = person(3, "Ola Testowa", { division: "front_office", ...under(lead) });
  const anna = person(4, "Anna Wzorcowa", { division: "front_office", ...under(lead) });
  const orphan = person(5, "Filip Bezpionowy", { division: "front_office" });
  const back = person(6, "Celina Opiekuńcza", { division: "back_office", ...under(lead) });
  const nobody = person(7, "Dawid Demo");

  const groups = buildStructure(structure([anna, back, head, lead, nobody, ola, orphan], { front_office: 1 }));

  it("grupuje po pionie w stałej kolejności, „Bez pionu” na końcu", () => {
    expect(groups.map((group) => group.key)).toEqual(["front_office", "back_office", "none"]);
    expect(groups[0].head).toEqual({ user_id: 1, name: "Paweł Przykładowy" });
    expect(groups[0].count).toBe(5);
  });

  it("w pionie drzewo po przełożonym, head na górze, podwładni po nazwisku", () => {
    const rows = flatten(groups[0].roots).map(({ node, depth }) => [node.person.name, depth]);
    expect(rows).toEqual([
      ["Paweł Przykładowy", 0],
      ["Marta Fikcyjna", 1],
      ["Anna Wzorcowa", 2],
      ["Ola Testowa", 2],
    ]);
  });

  it("przełożony z innego pionu robi z osoby korzeń jej pionu", () => {
    expect(groups[1].roots.map((node) => node.person.name)).toEqual(["Celina Opiekuńcza"]);
  });

  it("bez przełożonego i bez podwładnych — osobna lista, head się do niej nie liczy", () => {
    expect(groups[0].orphans.map((p) => p.name)).toEqual(["Filip Bezpionowy"]);
    expect(groups[2].orphans.map((p) => p.name)).toEqual(["Dawid Demo"]);
    expect(groups[2].roots).toEqual([]);
  });

  it("nikt nie znika przy pętli w danych", () => {
    const a = person(10, "A Pętla", { reports: 1, manager_user_id: 11, manager_state: "ok" });
    const b = person(11, "B Pętla", { reports: 1, manager_user_id: 10, manager_state: "ok" });
    const only = buildStructure(structure([a, b])).find((group) => group.key === "none")!;
    expect(flatten(only.roots).map(({ node }) => node.person.user_id).sort()).toEqual([10, 11]);
  });

  it("baner: odchodzący z podwładnymi", () => {
    const leaving = {
      case_id: 9,
      status: "active" as const,
      last_working_day: "2091-11-30",
      reports_receiver_user_id: 1,
      reports_receiver_name: "Paweł Przykładowy",
      reports_handover_status: "planned" as const,
    };
    const data = structure([{ ...lead, leaving }, { ...ola, leaving }]);
    expect(leavingManagers(data).map((p) => p.user_id)).toEqual([2]);
  });
});

describe("przełożony czy koordynator", () => {
  it("B2B i zlecenie — koordynator, UoP — przełożony, mieszane — oba", () => {
    expect(managerWords(["b2b", "zlecenie"]).one).toBe("koordynator");
    expect(managerWords(["uop"]).ofOne).toBe("przełożonego");
    expect(managerWords(["uop", "b2b"]).one).toBe("przełożony lub koordynator");
    expect(managerWords([]).one).toBe("przełożony lub koordynator");
  });
});
