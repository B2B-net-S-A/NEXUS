/**
 * Dane harnessu „Struktura u klienta” (`/preview/hr-client-people`) — wyłącznie
 * fikcyjne. Układ jak w makiecie 6 etapu 2: dział Data z dyrektorem i Head of
 * Data (menedżer trzech konsultantów, prośba o opinię przed końcem zamówień),
 * Płatności z jedną menedżerką bez opinii, osoba bez działu z podpowiedzią
 * działu z tekstu i konsultant bez wskazanego menedżera z podpowiedzią z pola
 * „Line Manager”. Daty liczymy od „dziś” przeglądarki.
 */

import type {
  ClientOrg,
  FeedbackRequest,
  OrgConsultant,
  OrgPerson,
} from "@/lib/api/client-people";

import type { ClientTechMap } from "@/lib/api/care";

import { HR_CLIENTS, HR_CONSULTANTS, shiftDay } from "../hr-fixtures";
import { clientTechMap } from "../hr-client-tech/fixtures";

export const ORG_CLIENT = HR_CLIENTS.bank;

// Te same działy co na mapie technologii banku (`hr-client-tech/fixtures.ts`) —
// zakładka „Ludzie i technologie” składa karty działów z obu odpowiedzi.
const AREA_DATA = { id: 303, name: "Data" };
const AREA_PAYMENTS = { id: 301, name: "Płatności" };
const AREA_LOANS = { id: 302, name: "Kredyty" };
const AREA_CLOUD = { id: 304, name: "CI/CD i chmura" };

function consultant(
  contractId: number,
  person: { id: number; name: string },
  role: string,
  endDate: string | null,
  lastFeedback: OrgConsultant["last_feedback"] = null,
): OrgConsultant {
  return {
    contract_id: contractId,
    candidate_id: person.id,
    candidate_name: person.name,
    role,
    end_date: endDate,
    end_source: endDate ? "order" : null,
    last_feedback: lastFeedback,
  };
}

function person(overrides: Partial<OrgPerson> & Pick<OrgPerson, "id" | "name">): OrgPerson {
  return {
    position: null,
    department_text: null,
    area_id: null,
    depth: 0,
    is_decision_maker: false,
    is_hiring_manager: false,
    is_manager: false,
    reports_to: null,
    subordinates: [],
    email: null,
    phone: null,
    hiring_manager_jobs: [],
    hiring_manager_jobs_total: 0,
    consultants: [],
    last_feedback: null,
    feedback_request: null,
    department_hint: null,
    ...overrides,
  };
}

/** Struktura Banku Przykładowego oglądana przez Delivery Leada klienta. */
export function clientOrg(today: string): ClientOrg {
  const ordersEnd = shiftDay(today, 20);
  const lastTalk = {
    session_id: 9301,
    held_on: shiftDay(today, -66),
    average: 4,
  };
  const dataTeam = [
    consultant(9401, HR_CONSULTANTS.michal, "Data Engineer", ordersEnd, {
      ...lastTalk,
      average: 4.3,
    }),
    consultant(9402, HR_CONSULTANTS.karolina, "Analityczka danych", ordersEnd, lastTalk),
    consultant(9403, HR_CONSULTANTS.bartosz, "Data Engineer", shiftDay(today, 160)),
  ];
  const payments = [
    consultant(9404, HR_CONSULTANTS.anna, "Tester automatyzujący", shiftDay(today, 25)),
  ];
  const director = person({
    id: 8201,
    name: "Zenon Dyrektorski",
    position: "CTO",
    area_id: AREA_DATA.id,
    is_decision_maker: true,
    is_hiring_manager: true,
    subordinates: [{ id: 8202, name: "Piotr Menedżerski" }],
    email: "zenon.dyrektorski@example.com",
    hiring_manager_jobs: [
      { id: 6101, title: "Data Engineer (Data)", status: "published" },
      { id: 6102, title: "Architekt danych", status: "closed" },
    ],
    hiring_manager_jobs_total: 2,
  });
  const headOfData = person({
    id: 8202,
    name: "Piotr Menedżerski",
    position: "Head of Data",
    area_id: AREA_DATA.id,
    depth: 1,
    is_manager: true,
    reports_to: { id: director.id, name: director.name },
    email: "piotr.menedzerski@example.com",
    phone: "+48 600 000 001",
    consultants: dataTeam,
    last_feedback: lastTalk,
    feedback_request: {
      reasons: ["pre_end"],
      due_on: shiftDay(ordersEnd, -30),
      overdue: true,
    },
  });
  const paymentsLead = person({
    id: 8203,
    name: "Katarzyna Płatnicza",
    position: "Kierowniczka zespołu płatności",
    area_id: AREA_PAYMENTS.id,
    is_manager: true,
    consultants: payments,
    feedback_request: {
      reasons: ["pre_end"],
      due_on: shiftDay(today, -5),
      overdue: true,
    },
  });
  const lineManager = person({
    id: 8204,
    name: "Michał Liniowy",
    position: "Line Manager",
    department_text: "Data",
    department_hint: { area_id: AREA_DATA.id, name: AREA_DATA.name },
  });
  const requests: FeedbackRequest[] = [headOfData, paymentsLead].map((manager) => ({
    contact_id: manager.id,
    contact_name: manager.name,
    position: manager.position,
    client_id: ORG_CLIENT.id,
    client_name: ORG_CLIENT.name,
    reasons: manager.feedback_request?.reasons ?? [],
    due_on: manager.feedback_request?.due_on ?? today,
    overdue: true,
    last_feedback: manager.last_feedback,
    consultants: manager.consultants,
    owner_ids: [102],
  }));
  return {
    client_id: ORG_CLIENT.id,
    client_name: ORG_CLIENT.name,
    areas: [AREA_CLOUD, AREA_DATA, AREA_LOANS, AREA_PAYMENTS],
    departments: [
      { area: AREA_DATA, people: [director, headOfData] },
      { area: AREA_PAYMENTS, people: [paymentsLead] },
      { area: null, people: [lineManager] },
    ],
    without_manager: [
      {
        ...consultant(9405, HR_CONSULTANTS.pawel, "QA", null),
        line_manager: "Michał Liniowy",
        client_pm_name: null,
        manager_outside_client: false,
        hint: {
          contact_id: lineManager.id,
          name: lineManager.name,
          position: lineManager.position,
          source: "line_manager",
          text: "Michał Liniowy",
        },
      },
    ],
    requests,
    people_count: 4,
    consultants_count: 5,
    can_edit_org: true,
    can_write_feedback: true,
  };
}

/** Zdrowie relacji przy konsultantach w drzewie (krąg D11) — fikcja do kropek. */
const HEALTH: Record<number, { level: "ok" | "watch" | "risk"; label: string; reasons: string[] }> = {
  9401: { level: "ok", label: "Dobrze", reasons: [] },
  9402: { level: "watch", label: "Uwaga", reasons: ["zamówienie kończy się za 20 dni bez decyzji"] },
  9403: { level: "ok", label: "Dobrze", reasons: [] },
  9404: { level: "risk", label: "Ryzyko", reasons: ["chce zmiany projektu"] },
};

/** Drzewo z polem `health` przy konsultancie (serwer od 22.10.2026, krąg D11). */
export function clientOrgWithHealth(today: string): ClientOrg {
  const org = clientOrg(today);
  const withHealth = (c: OrgConsultant): OrgConsultant =>
    ({ ...c, health: HEALTH[c.contract_id] ?? null }) as OrgConsultant;
  return {
    ...org,
    departments: org.departments.map((department) => ({
      ...department,
      people: department.people.map((person) => ({
        ...person,
        consultants: person.consultants.map(withHealth),
      })),
    })),
  };
}

/**
 * Mapa banku zgodna z drzewem (zakładka „Ludzie i technologie”): menedżerowie
 * działów i liczby naszych z `clientOrg`, luka „komu podlega” przy
 * kierowniczce płatności bez przełożonego.
 */
export function peopleTechMap(today: string): ClientTechMap {
  const map = clientTechMap(today);
  const managers: Record<number, ClientTechMap["departments"][number]["managers"]> = {
    303: [{ id: 8202, name: "Piotr Menedżerski", position: "Head of Data", consultants: 3 }],
    301: [
      { id: 8203, name: "Katarzyna Płatnicza", position: "Kierowniczka zespołu płatności", consultants: 1 },
    ],
  };
  return {
    ...map,
    consultants_count: 5,
    departments: map.departments.map((department) => ({
      ...department,
      managers: managers[department.area.id] ?? [],
      consultants: managers[department.area.id]?.[0]?.consultants ?? 0,
    })),
    gaps: map.gaps.map((gap) =>
      gap.kind === "manager_unplaced"
        ? {
            ...gap,
            contact: { id: 8203, name: "Katarzyna Płatnicza" },
            position: "Kierowniczka zespołu płatności",
            consultants: 1,
          }
        : gap,
    ),
  };
}
