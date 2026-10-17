// „Ludzie → Struktura” — układ drzewa z płaskiej listy (czyste funkcje, bez zapytań).
//
// Najpierw pion (Front office, Back office, „Bez pionu”), w środku drzewo po
// przełożonym. Korzeń grupy to osoba, której przełożony jest poza grupą (inny
// pion, konto bez kartoteki, osoba, która odeszła) albo której nie ma — wtedy
// szczyt drzewa (ma podwładnych) albo „Bez przełożonego” (nie ma nikogo pod sobą).

import type { Division } from "@/lib/api/hr";
import {
  DIVISION_LABELS,
  type HrStructure,
  type StructurePerson,
} from "@/lib/api/hr-structure";

export type DivisionKey = Division | "none";

export interface TreeNode {
  person: StructurePerson;
  children: TreeNode[];
}

export interface DivisionGroup {
  key: DivisionKey;
  label: string;
  head: { user_id: number; name: string } | null;
  roots: TreeNode[];
  /** Bez przełożonego i bez podwładnych (poza headem pionu). */
  orphans: StructurePerson[];
  count: number;
}

const ORDER: DivisionKey[] = ["front_office", "back_office", "none"];

const byName = (a: StructurePerson, b: StructurePerson) =>
  a.name.localeCompare(b.name, "pl-PL") || a.user_id - b.user_id;

export function divisionKey(person: StructurePerson): DivisionKey {
  return person.division ?? "none";
}

export function buildStructure(data: HrStructure): DivisionGroup[] {
  const byId = new Map(data.people.map((person) => [person.user_id, person]));
  const heads = new Map(
    data.divisions.map((division) => [
      division.key,
      division.head_user_id && division.head_name
        ? { user_id: division.head_user_id, name: division.head_name }
        : null,
    ]),
  );
  const groups: DivisionGroup[] = [];
  for (const key of ORDER) {
    const members = data.people.filter((person) => divisionKey(person) === key);
    const head = key === "none" ? null : (heads.get(key) ?? null);
    if (key === "none" && members.length === 0) continue;
    const inGroup = (id: number | null) =>
      id !== null && byId.has(id) && divisionKey(byId.get(id)!) === key;
    const children = new Map<number, StructurePerson[]>();
    for (const person of members) {
      if (inGroup(person.manager_user_id)) {
        const list = children.get(person.manager_user_id!) ?? [];
        list.push(person);
        children.set(person.manager_user_id!, list);
      }
    }
    const isOrphan = (person: StructurePerson) =>
      person.manager_state === "none" && person.reports === 0 && person.user_id !== head?.user_id;
    const orphans = members.filter(isOrphan).sort(byName);
    const rootPeople = members
      .filter((person) => !inGroup(person.manager_user_id) && !isOrphan(person))
      .sort(
        (a, b) =>
          Number(b.user_id === head?.user_id) - Number(a.user_id === head?.user_id) ||
          Number(b.reports > 0) - Number(a.reports > 0) ||
          byName(a, b),
      );
    const visited = new Set<number>();
    const grow = (person: StructurePerson): TreeNode => {
      visited.add(person.user_id);
      const kids = (children.get(person.user_id) ?? [])
        .filter((child) => !visited.has(child.user_id))
        .sort(byName);
      return { person, children: kids.map(grow) };
    };
    const roots = rootPeople.map(grow);
    // Pętla w danych (serwer na nią nie pozwala) — nikt nie znika z ekranu.
    for (const person of [...members].sort(byName)) {
      if (!visited.has(person.user_id) && !isOrphan(person)) roots.push(grow(person));
    }
    groups.push({
      key,
      label: key === "none" ? "Bez pionu" : DIVISION_LABELS[key],
      head,
      roots,
      orphans,
      count: members.length,
    });
  }
  return groups;
}

/** Wszystkie osoby z poddrzewa (w kolejności wyświetlania). */
export function flatten(nodes: readonly TreeNode[], depth = 0): { node: TreeNode; depth: number }[] {
  return nodes.flatMap((node) => [{ node, depth }, ...flatten(node.children, depth + 1)]);
}

/** Odchodzący z podwładnymi — baner nad drzewem (D5). */
export function leavingManagers(data: HrStructure): StructurePerson[] {
  return data.people.filter((person) => person.leaving && person.reports > 0).sort(byName);
}
