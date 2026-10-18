/**
 * Dane harnessu „Technologie klienta” (`/preview/hr-client-tech`) — wyłącznie
 * fikcyjne. Liczby źródeł T/R/K/N i obszary jak w makiecie 10, działy z menedżerem,
 * „Nasi / w bazie” i „Luki do dopytania” jak w makiecie 8 etapu 2; daty „ostatnio”
 * liczymy od „dziś” przeglądarki, żeby mapa nie starzała się z kalendarzem.
 */

import type {
  ClientTechMap,
  DepartmentTechnology,
  MapDepartment,
  MapTechnology,
  PersonRef,
  TechGap,
  TechSource,
  UnlinkedTechCards,
} from "@/lib/api/care";

import { HR_CAST, HR_CLIENTS, HR_CONSULTANTS, shiftDay } from "../hr-fixtures";

export const MAP_CLIENT = HR_CLIENTS.bank;

const ref = (person: { id: number; name: string }): PersonRef => ({ id: person.id, name: person.name });

export const CARE_OWNERS: PersonRef[] = [ref(HR_CAST.natalia), ref(HR_CAST.kamil), ref(HR_CAST.adam)];

function tech(
  skillId: number,
  name: string,
  areas: string[],
  [cards, jobs, consultants, notes]: [number, number, number, number],
  lastSeen: string,
  mustJobs = 0,
): MapTechnology {
  const counts: Record<TechSource, number> = { cards, jobs, consultants, notes };
  return {
    skill_id: skillId,
    name,
    category: null,
    counts,
    source_count: Object.values(counts).filter(Boolean).length,
    must_jobs: mustJobs,
    consultant_months: consultants * 9,
    areas,
    last_seen: lastSeen,
    stale: false,
  };
}

function deptTech(
  skillId: number,
  name: string,
  [cards, jobs, consultants, notes]: [number, number, number, number],
  lastSeen: string,
): DepartmentTechnology {
  const counts: Record<TechSource, number> = { cards, jobs, consultants, notes };
  return {
    skill_id: skillId,
    name,
    counts,
    source_count: Object.values(counts).filter(Boolean).length,
    last_seen: lastSeen,
    stale: false,
  };
}

/** Działy klienta (D16) — te same co w „Strukturze u klienta”, z menedżerem z drzewa. */
function departments(today: string): MapDepartment[] {
  const lastCard = shiftDay(today, -13);
  // Kolejność jak z serwera — po nazwie działu.
  return [
    {
      area: { id: 304, name: "CI/CD i chmura" },
      technologies: [],
      technologies_total: 0,
      managers: [],
      consultants: 0,
      last_seen: null,
      has_fresh_source: false,
      base: { skills: [], count: null },
    },
    {
      area: { id: 303, name: "Data" },
      technologies: [deptTech(808, "Azure Data Factory", [1, 0, 0, 0], shiftDay(today, -55))],
      technologies_total: 1,
      managers: [
        { id: 8802, name: "Piotr Menedżerski", position: "Kierownik zespołu Data", consultants: 2 },
      ],
      consultants: 2,
      last_seen: today,
      has_fresh_source: true,
      base: { skills: ["Azure Data Factory"], count: 9 },
    },
    {
      area: { id: 302, name: "Kredyty" },
      technologies: [
        deptTech(801, "Java 17", [1, 2, 0, 0], lastCard),
        deptTech(807, "Angular", [0, 2, 0, 0], shiftDay(today, -62)),
        deptTech(802, "Spring Boot", [1, 1, 0, 0], lastCard),
      ],
      technologies_total: 3,
      managers: [],
      consultants: 0,
      last_seen: lastCard,
      has_fresh_source: true,
      base: { skills: ["Java 17", "Angular"], count: 41 },
    },
    {
      area: { id: 301, name: "Płatności" },
      technologies: [
        deptTech(801, "Java 17", [3, 4, 3, 0], lastCard),
        deptTech(802, "Spring Boot", [3, 4, 3, 0], lastCard),
        deptTech(803, "Kafka", [3, 2, 2, 0], lastCard),
        deptTech(804, "OpenShift", [2, 0, 1, 0], lastCard),
        deptTech(806, "PostgreSQL", [2, 1, 0, 0], lastCard),
      ],
      technologies_total: 5,
      managers: [
        { id: 8803, name: "Michał Rogalski-Przykładowy", position: "Kierownik Płatności", consultants: 3 },
      ],
      consultants: 3,
      last_seen: today,
      has_fresh_source: true,
      base: { skills: ["Java 17", "Spring Boot"], count: 212 },
    },
  ];
}

/** „Luki do dopytania” — makieta 8: dział bez źródła, technologia z jednej rozmowy, „komu podlega”. */
function gaps(today: string): TechGap[] {
  return [
    { kind: "area_no_source", area: { id: 304, name: "CI/CD i chmura" }, last_seen: null },
    {
      kind: "manager_unplaced",
      contact: { id: 8803, name: "Michał Rogalski-Przykładowy" },
      position: "Kierownik Płatności",
      area: { id: 301, name: "Płatności" },
      consultants: 3,
    },
    {
      kind: "single_source",
      skill_id: 808,
      name: "Azure Data Factory",
      source: "cards",
      refs: 1,
      last_seen: shiftDay(today, -55),
      areas: ["Data"],
    },
  ];
}

/** Mapa technologii Banku Przykładowego oglądana przez Delivery Leada klienta. */
export function clientTechMap(today: string): ClientTechMap {
  const lastCard = shiftDay(today, -13);
  return {
    client_id: MAP_CLIENT.id,
    client_name: MAP_CLIENT.name,
    technologies: [
      tech(801, "Java 17", ["Płatności", "Kredyty"], [4, 6, 5, 1], lastCard, 3),
      tech(803, "Kafka", ["Płatności"], [3, 2, 2, 0], lastCard, 1),
      tech(802, "Spring Boot", ["Płatności", "Kredyty"], [4, 5, 5, 0], lastCard, 2),
      tech(804, "OpenShift", ["Płatności"], [2, 0, 1, 1], lastCard),
      tech(806, "PostgreSQL", ["Płatności"], [2, 1, 0, 0], lastCard),
      tech(807, "Angular", ["Kredyty"], [0, 2, 1, 0], shiftDay(today, -62), 1),
      tech(808, "Azure Data Factory", ["Data"], [1, 0, 0, 0], shiftDay(today, -55)),
    ],
    areas: [
      { id: 304, name: "CI/CD i chmura", cards: 0 },
      { id: 303, name: "Data", cards: 1 },
      { id: 302, name: "Kredyty", cards: 2 },
      { id: 301, name: "Płatności", cards: 4 },
    ],
    vendors: [
      { id: 61, name: "Dostawca A", cards: 3 },
      { id: 62, name: "Dostawca B", cards: 1 },
    ],
    signals: [
      {
        kind: "tech_card",
        id: 21,
        contract_id: 4501,
        on: lastCard,
        roles: ["Java", "QA"],
        source: "widzial",
        area: "Płatności",
        note: "Zespół ma się podwoić do końca roku.",
        sales_status: null,
      },
    ],
    open_jobs: [
      { id: 5201, title: "Java Developer (Płatności)", opened_on: shiftDay(today, -9) },
      { id: 5202, title: "DevOps Engineer (OpenShift)", opened_on: shiftDay(today, -21) },
      { id: 5203, title: "Angular Developer (Kredyty)", opened_on: shiftDay(today, -34) },
    ],
    open_jobs_count: 3,
    consultants_count: 6,
    cards_count: 5,
    notes: [
      {
        id: 701,
        content: "Płatności: Java 17 na OpenShift, wdrożenia raz w tygodniu.",
        created_on: shiftDay(today, -16),
      },
    ],
    notes_count: 1,
    redeploy_active: 2,
    departments: departments(today),
    gaps: gaps(today),
    default_owner: ref(HR_CAST.natalia),
    can_edit: true,
  };
}

/** Karty z importu Compassa bez kontraktu (zakładka „Technologie” banku). */
export function unlinkedCards(today: string): UnlinkedTechCards {
  const anna = {
    id: 4504,
    candidate_name: HR_CONSULTANTS.anna.name,
    start_date: shiftDay(today, -400),
    end_date: null,
    status: "active",
  };
  const annaBefore = {
    id: 4503,
    candidate_name: HR_CONSULTANTS.anna.name,
    start_date: shiftDay(today, -800),
    end_date: shiftDay(today, -401),
    status: "ended",
  };
  const michal = {
    id: 4501,
    candidate_name: HR_CONSULTANTS.michal.name,
    start_date: shiftDay(today, -44),
    end_date: null,
    status: "active",
  };
  return {
    items: [
      {
        id: 61,
        interview_on: shiftDay(today, -120),
        person_name: HR_CONSULTANTS.anna.name,
        area: "Płatności",
        author: HR_CAST.natalia.name,
        is_draft: false,
        skills: ["Java", "Kafka", "Spring Boot"],
        unrecognized_skills: ["camunda 8"],
        suggestions: [anna, annaBefore],
      },
      {
        id: 62,
        interview_on: shiftDay(today, -300),
        person_name: "Konsultant Spoza Bazy",
        area: null,
        author: HR_CAST.natalia.name,
        is_draft: false,
        skills: ["Angular"],
        unrecognized_skills: [],
        suggestions: [],
      },
    ],
    contracts: [michal, anna, annaBefore],
    can_link: true,
  };
}
