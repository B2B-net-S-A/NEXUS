/**
 * Dane harnessu „Opieka nad konsultantem” (`/preview/hr-care`) — wyłącznie
 * fikcyjne (obsada z `hr-fixtures.ts`).
 *
 * Daty liczymy od „dziś” przeglądarki (`warsawToday`, jak ekran), żeby kontrakt
 * zawsze był w 45. dniu współpracy: start = dziś − 44 (serwer liczy dzień jako
 * `(dziś − start) + 1`). Plan z rytmu (etap 3): kamień „Dzień 7” i rozmowy co
 * 2 tygodnie przez pierwsze 90 dni — dzień 28 pominięty z powodem (karta
 * technologiczna w 31. dniu), dzień 56 następny.
 */

import {
  monthEnd,
  type CareConversation,
  type CarePlanItem,
  type CareSummary,
  type ContractCare,
  type PersonRef,
  type RedeployRow,
  type SkillReviewRow,
  type TechCard,
} from "@/lib/api/care";

import { HR_CAST, HR_CLIENTS, HR_CONSULTANTS, shiftDay } from "../hr-fixtures";

export const CARE_CONTRACT_ID = 4501;
export const CARE_CLIENT = HR_CLIENTS.bank;

const ref = (person: { id: number; name: string }): PersonRef => ({ id: person.id, name: person.name });
const natalia = ref(HR_CAST.natalia);

export const CARE_OWNERS: PersonRef[] = [natalia, ref(HR_CAST.kamil), ref(HR_CAST.adam)];

export const CLIENT_AREAS = [
  { id: 301, name: "Płatności" },
  { id: 302, name: "Kredyty" },
  { id: 303, name: "Data" },
];

const at = (day: string) => `${day}T09:00:00Z`;

/** Koniec miesiąca około `days` dni od dziś (koniec projektu podaje się miesiącem). */
function monthEndAround(today: string, days: number): string {
  return monthEnd(shiftDay(today, days).slice(0, 7)) ?? shiftDay(today, days);
}

export function contractStart(today: string): string {
  return shiftDay(today, -44);
}

export function careTechCard(today: string): TechCard {
  const start = contractStart(today);
  return {
    id: 21,
    contract_id: CARE_CONTRACT_ID,
    client_id: CARE_CLIENT.id,
    interview_on: shiftDay(start, 31),
    status: "ok",
    is_draft: false,
    finalized_at: at(shiftDay(start, 31)),
    satisfaction: 4,
    area: CLIENT_AREAS[0],
    skills: [
      { id: 801, name: "Java 17" },
      { id: 802, name: "Spring Boot" },
      { id: 803, name: "Kafka" },
      { id: 804, name: "OpenShift" },
      { id: 805, name: "Oracle" },
      { id: 806, name: "PostgreSQL" },
    ],
    unrecognized_skills: [],
    vendors: [
      { id: 61, name: "Dostawca A" },
      { id: 62, name: "Dostawca B" },
    ],
    hiring: true,
    hiring_source: "widzial",
    hiring_roles: ["Java", "QA"],
    project_end_on: monthEndAround(today, 100),
    project_end_unknown: false,
    team_size: "9 osób",
    team_externals: 4,
    initiatives: [{ name: "migracja Oracle → PostgreSQL", kind: "migracja", priority: "wysoki" }],
    memorable_quote: "Do końca roku zespół ma się podwoić.",
    note: null,
    sales_status: null,
    author: natalia,
  };
}

function conversation(
  id: number,
  occurredOn: string,
  note: string,
  satisfaction: number | null,
): CareConversation {
  return {
    id,
    occurred_on: occurredOn,
    channel: "phone",
    satisfaction,
    note,
    attrition_risk: false,
    wants_change: false,
    project_end_on: null,
    client_hiring: false,
    client_hiring_note: null,
    follow_up_on: null,
    author: natalia,
  };
}

function planItem(
  id: number,
  kind: CarePlanItem["kind"],
  label: string,
  dueOn: string,
  doneOn: string | null,
  conversationId: number | null = null,
  skipReason: CarePlanItem["skip_reason"] = null,
): CarePlanItem {
  return {
    id,
    kind,
    label,
    due_on: dueOn,
    status: skipReason ? "skipped" : doneOn ? "done" : "open",
    overdue: false,
    done_conversation_id: conversationId,
    resolved_at: doneOn ? at(doneOn) : null,
    skip_reason: skipReason,
    skip_note: null,
  };
}

const RHYTHM = "Rozmowa według rytmu";

/** Zakładka „Opieka” kontraktu Michała w Banku Przykładowym (makieta 9). */
export function contractCare(today: string): ContractCare {
  const start = contractStart(today);
  const card = careTechCard(today);
  return {
    contract: {
      id: CARE_CONTRACT_ID,
      label: `${HR_CONSULTANTS.michal.name} · ${CARE_CLIENT.name}`,
      candidate_id: HR_CONSULTANTS.michal.id,
      candidate_name: HR_CONSULTANTS.michal.name,
      client_id: CARE_CLIENT.id,
      client_name: CARE_CLIENT.name,
      job_id: 5101,
      job_title: "Java Developer",
      status: "active",
      is_live: true,
      start_date: start,
      end_date: null,
      day_of_cooperation: 45,
    },
    owner: { user: natalia, source: "contract", explicit: true },
    client_default_owner: natalia,
    cadence: {
      level: "biweekly",
      source: "program",
      starts_on: start,
      until_on: shiftDay(start, 89),
      returns_to: "monthly",
      reason: null,
      note: null,
      author: null,
      can_edit: true,
    },
    plan: [
      planItem(1, "day_7", "Dzień 7", shiftDay(start, 7), shiftDay(start, 7), 11),
      planItem(2, "cadence", RHYTHM, shiftDay(start, 14), shiftDay(start, 14), 12),
      planItem(3, "cadence", RHYTHM, shiftDay(start, 28), card.interview_on, null, "recent_contact"),
      planItem(4, "cadence", RHYTHM, shiftDay(start, 42), card.interview_on),
      planItem(5, "cadence", RHYTHM, shiftDay(start, 56), null),
      planItem(6, "cadence", RHYTHM, shiftDay(start, 70), null),
    ],
    next_contact: { due_on: shiftDay(start, 56), label: RHYTHM, overdue: false, plan_item_id: 5 },
    last_satisfaction: { value: 4, on: card.interview_on },
    conversations: [
      conversation(
        12,
        shiftDay(start, 14),
        "Trzy dni bez dostępu do VPN, zgłoszone do Delivery Leada. Poza tym w porządku.",
        null,
      ),
      conversation(11, shiftDay(start, 7), "Onboarding u klienta, sprzęt odebrany.", null),
    ],
    tech_cards: [card],
    redeploy: [],
    project_end: { end_on: card.project_end_on, source: "tech_card", known_on: card.interview_on },
    can_edit: true,
  };
}

// ── `/care` (stan `list`) ───────────────────────────────────────────────────

function redeploy(
  id: number,
  contractId: number,
  consultant: { id: number; name: string },
  jobTitle: string,
  status: RedeployRow["status"],
  dueOn: string,
  createdOn: string,
  note: string | null,
): RedeployRow {
  return {
    id,
    contract_id: contractId,
    reason: "project_end",
    status,
    due_on: dueOn,
    source: "tech_card",
    note,
    created_at: at(createdOn),
    resolved_at: null,
    candidate_id: consultant.id,
    candidate_name: consultant.name,
    client_id: CARE_CLIENT.id,
    client_name: CARE_CLIENT.name,
    job_title: jobTitle,
    end_date: null,
    owner: natalia,
  };
}

export function redeployQueue(today: string, state: "active" | "closed") {
  const items =
    state === "active"
      ? [
          redeploy(42, 4504, HR_CONSULTANTS.pawel, "Java Developer", "in_progress", shiftDay(today, 46), shiftDay(today, -14), "pasuje do 1 rekrutacji"),
          redeploy(41, 4503, HR_CONSULTANTS.bartosz, "DevOps Engineer", "open", monthEndAround(today, 60), shiftDay(today, -3), "pasuje do 2 otwartych rekrutacji"),
        ]
      : [];
  return { items, total: items.length, can_edit: true };
}

export function skillReview(today: string, state: "open" | "closed") {
  const item = (
    id: number,
    name: string,
    status: SkillReviewRow["status"],
    occurrences: number,
    skill: SkillReviewRow["skill"],
    daysAgo: number,
  ): SkillReviewRow => ({
    id,
    name,
    status,
    occurrences,
    skill,
    reported_by: natalia,
    created_at: at(shiftDay(today, -daysAgo)),
    resolved_at: status === "open" ? null : at(shiftDay(today, -daysAgo + 2)),
  });
  const items =
    state === "open"
      ? [
          { ...item(51, "Camunda 8", "open", 2, null, 6), suggestions: [{ id: 811, name: "Camunda" }] },
          item(52, "Oracle GoldenGate", "open", 1, null, 13),
        ]
      : [item(53, "Springboot", "mapped", 3, { id: 802, name: "Spring Boot" }, 20)];
  return { items, can_curate: true };
}

export const CARE_SUMMARY: CareSummary = {
  redeploy_active: 2,
  skill_review_open: 2,
  can_edit: true,
  can_curate: true,
};
