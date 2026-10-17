/**
 * Dane harnessu „Technologie klienta” (`/preview/hr-client-tech`) — wyłącznie
 * fikcyjne. Liczby źródeł T/R/K/N i obszary jak w makiecie 10; daty „ostatnio”
 * liczymy od „dziś” przeglądarki, żeby mapa nie starzała się z kalendarzem.
 */

import type { ClientTechMap, MapTechnology, PersonRef, TechSource } from "@/lib/api/care";

import { HR_CAST, HR_CLIENTS, shiftDay } from "../hr-fixtures";

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
      { id: 301, name: "Płatności", cards: 4 },
      { id: 302, name: "Kredyty", cards: 2 },
      { id: 303, name: "Data", cards: 1 },
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
    default_owner: ref(HR_CAST.natalia),
    can_edit: true,
  };
}
