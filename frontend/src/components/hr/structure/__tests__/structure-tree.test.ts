import { describe, expect, it } from "vitest";

import type { HrStructure, StructurePerson } from "@/lib/api/hr-structure";
import { managerWords } from "@/lib/api/hr-structure";

import {
  blockedManagers,
  buildStructure,
  canDropOn,
  centeredScrollLeft,
  childLayout,
  flatten,
  leavingManagers,
  todoItems,
} from "../structure-tree";

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
    expect(managerWords(["uop", "b2b"]).one).toBe("koordynator");
    expect(managerWords([]).one).toBe("koordynator");
  });
});


describe("schemat — przeciąganie karty (makieta 19.10.2026)", () => {
  const boss = person(1, "Kamil Testowy", { division: "front_office", reports: 1 });
  const lead = person(2, "Marta Fikcyjna", { division: "front_office", reports: 1, ...under(boss) });
  const recruiter = person(3, "Ewa Makietowa", { division: "front_office", ...under(lead) });
  const other = person(4, "Piotr Finansowy", { division: "back_office" });
  const data = structure([boss, lead, recruiter, other], { front_office: 1 });

  it("nie da się podpiąć pod siebie ani pod własne poddrzewo", () => {
    expect([...blockedManagers(data, 1)].sort()).toEqual([1, 2, 3]);
    expect(canDropOn(data, 1, 3)).toBe(false);
    expect(canDropOn(data, 2, 2)).toBe(false);
  });

  it("upuszczenie na obecnego przełożonego to nie zmiana", () => {
    expect(canDropOn(data, 3, 2)).toBe(false);
  });

  it("inna osoba, także z innego pionu, przyjmuje kartę", () => {
    expect(canDropOn(data, 3, 1)).toBe(true);
    expect(canDropOn(data, 3, 4)).toBe(true);
    expect(canDropOn(data, 99, 1)).toBe(false);
  });
});

describe("„Do uporządkowania”", () => {
  it("zbiera odejście przełożonego, M365, podpowiedzi, brak przełożonego i pionu", () => {
    const head = person(1, "Kamil Testowy", { division: "front_office", reports: 2 });
    const leaving = person(2, "Marta Fikcyjna", {
      division: "front_office",
      reports: 3,
      ...under(head),
      leaving: {
        case_id: 7,
        status: "active",
        last_working_day: "2026-11-30",
        reports_receiver_user_id: 1,
        reports_receiver_name: "Kamil Testowy",
        reports_handover_status: "planned",
      },
    });
    const m365 = person(3, "Ola Przykładowa", {
      division: "front_office",
      ...under(leaving),
      m365_hint: { upn: "kamil@example.com", user_id: 1, name: "Kamil Testowy", can_accept: true },
    });
    const suggested = person(4, "Kacper Nowicjusz", {
      division: "front_office",
      suggested_manager: { user_id: 1, name: "Kamil Testowy" },
    });
    const alone = person(5, "Paulina Kadrowa");
    const gone = person(6, "Zofia Recepcyjna", {
      division: "back_office",
      manager_user_id: 77,
      manager_name: "Ktoś, kto odszedł",
      manager_state: "inactive",
    });
    const items = todoItems(structure([head, leaving, m365, suggested, alone, gone], { front_office: 1 }));
    expect(items.map((item) => [item.kind, item.person.user_id])).toEqual([
      ["leaving", 2],
      ["manager_gone", 6],
      ["m365", 3],
      ["suggestion", 4],
      ["no_manager", 5],
      ["no_division", 5],
    ]);
  });

  it("head pionu bez przełożonego to nie brak", () => {
    const head = person(1, "Kamil Testowy", { division: "front_office" });
    expect(todoItems(structure([head], { front_office: 1 }))).toEqual([]);
  });
});

describe("schemat — kolumna podwładnych (prod 20.10.2026)", () => {
  // Jak na produkcji: szef → dwie osoby → po kilkadziesiąt osób bez ludzi.
  const boss = person(1, "Szef Przykładowy", { reports: 2 });
  const leadA = person(2, "Adam Prowadzący", { reports: 20, ...under(boss) });
  const leadB = person(3, "Beata Prowadząca", { reports: 3, ...under(boss) });
  const many = Array.from({ length: 20 }, (_, i) =>
    person(100 + i, `Osoba ${String(i).padStart(2, "0")}`, under(leadA)),
  );
  const few = [0, 1, 2].map((i) => person(200 + i, `Mała ${i}`, under(leadB)));
  const noDivision = (people: StructurePerson[]) =>
    buildStructure(structure(people)).find((g) => g.key === "none")!;
  const group = noDivision([boss, leadA, leadB, ...many, ...few]);
  const [root] = group.roots;

  it("do czterech podwładnych — zwykły rząd", () => {
    const b = root.children.find((node) => node.person.user_id === 3)!;
    expect(childLayout(b).stack).toEqual([]);
    expect(childLayout(b).branches).toHaveLength(3);
    expect(childLayout(root).stack).toEqual([]);
  });

  it("więcej niż czterech bez własnych ludzi — kolumna, po nazwisku", () => {
    const a = root.children.find((node) => node.person.user_id === 2)!;
    const layout = childLayout(a);
    expect(layout.branches).toEqual([]);
    expect(layout.stack.map((node) => node.person.name)).toEqual(many.map((p) => p.name));
  });

  it("mieszany zespół: przełożeni zostają w rzędzie, reszta w kolumnie", () => {
    const top = person(1, "Szef", { reports: 6 });
    const mid = person(2, "Kierownik", { reports: 1, ...under(top) });
    const sub = person(3, "Pod kierownikiem", under(mid));
    const leaves = [4, 5, 6, 7, 8].map((id) => person(id, `Liść ${id}`, under(top)));
    const g = noDivision([top, mid, sub, ...leaves]);
    const layout = childLayout(g.roots[0]);
    expect(layout.branches.map((node) => node.person.name)).toEqual(["Kierownik"]);
    expect(layout.stack.map((node) => node.person.user_id)).toEqual([4, 5, 6, 7, 8]);
  });

  it("jeden liść wśród przełożonych nie robi kolumny", () => {
    const top = person(1, "Szef", { reports: 5 });
    const mids = [2, 3, 4, 5].map((id) => person(id, `Kierownik ${id}`, { reports: 1, ...under(top) }));
    const subs = mids.map((m, i) => person(10 + i, `Pod ${i}`, under(m)));
    const leaf = person(9, "Samotny liść", under(top));
    const g = noDivision([top, ...mids, ...subs, leaf]);
    const layout = childLayout(g.roots[0]);
    expect(layout.stack).toEqual([]);
    expect(layout.branches).toHaveLength(5);
  });

  it("nikt nie znika: rząd + kolumna = wszyscy podwładni", () => {
    for (const { node } of flatten(group.roots)) {
      const { branches, stack } = childLayout(node);
      expect(branches.length + stack.length).toBe(node.children.length);
    }
  });
});

describe("schemat — otwarcie na korzeniu", () => {
  it("karta w środku szerokiego drzewa staje na środku okna", () => {
    // Prod 20.10.2026: 5384 px treści, 623 px okna, korzeń pośrodku.
    expect(centeredScrollLeft(2606, 172, 623, 5384)).toBe(2381);
  });

  it("nie wychodzi poza zakres przewijania", () => {
    expect(centeredScrollLeft(10, 172, 623, 5384)).toBe(0);
    expect(centeredScrollLeft(5300, 172, 623, 5384)).toBe(5384 - 623);
    expect(centeredScrollLeft(100, 172, 800, 600)).toBe(0);
  });
});
