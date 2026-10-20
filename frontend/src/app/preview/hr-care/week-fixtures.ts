/**
 * Dane harnessu „Opieka · Ten tydzień” (`/preview/hr-care?state=list`) —
 * wyłącznie fikcyjne (obsada z `hr-fixtures.ts`, makieta 7 etapu 2).
 *
 * Tydzień liczymy od „dziś” przeglądarki tak jak serwer: poniedziałek–piątek,
 * w weekend — tydzień, który się zaczyna. Konsultanci są ci sami co na liście
 * „Konsultanci” (`rhythm-fixtures.ts`): Karolina (zaległy „Dzień 30”,
 * kończy projekt), Paweł (przed końcem zamówienia, chce zmiany — do front
 * office), Michał (umówiony kontakt). Dwie prośby o opinię od menedżerów.
 */

import type {
  CareWeek,
  ClientTechMap,
  ContractTimeline,
  FrontOfficeOverview,
  PersonRef,
  TimelineEvent,
  WeekContact,
  WeekFeedback,
} from "@/lib/api/care";
import type { OrgConsultant } from "@/lib/api/client-people";

import { clientTechMap } from "../hr-client-tech/fixtures";
import { HR_CAST, HR_CLIENTS, HR_CONSULTANTS, shiftDay } from "../hr-fixtures";
import { CARE_CLIENT, CARE_CONTRACT_ID, contractStart } from "./fixtures";

const natalia: PersonRef = { id: HR_CAST.natalia.id, name: HR_CAST.natalia.name };

export const WEEK_HANDOFF_CONTRACT = 4504;
const KAROLINA_CONTRACT = 4502;

/** Poniedziałek i piątek tygodnia „Ten tydzień” (w weekend — następnego). */
export function weekBounds(today: string): { from: string; to: string } {
  const [y, m, d] = today.split("-").map(Number);
  const weekday = (new Date(Date.UTC(y, m - 1, d)).getUTCDay() + 6) % 7; // pon = 0
  const monday = weekday >= 5 ? shiftDay(today, 7 - weekday) : shiftDay(today, -weekday);
  return { from: monday, to: shiftDay(monday, 4) };
}

function consultant(
  contractId: number,
  person: { id: number; name: string },
  role: string,
  end: string | null,
): OrgConsultant {
  return {
    contract_id: contractId,
    candidate_id: person.id,
    candidate_name: person.name,
    role,
    end_date: end,
    end_source: end ? "order" : null,
    last_feedback: null,
  };
}

function contact(
  row: Partial<WeekContact> & Pick<WeekContact, "contract_id" | "reasons" | "due_on">,
): WeekContact {
  return {
    candidate_id: null,
    candidate_name: null,
    client_id: CARE_CLIENT.id,
    client_name: CARE_CLIENT.name,
    job_title: null,
    start_date: null,
    end_date: null,
    owner: natalia,
    overdue: false,
    overdue_days: 0,
    plan_item_id: null,
    manager: null,
    last_conversation: null,
    signals: [],
    front_office: { reasons: [], handed_off_on: null },
    ...row,
  };
}

const BULK_FIRST = ["Adam", "Beata", "Cezary", "Dorota", "Emil", "Fiona", "Gustaw", "Halina"];
const BULK_LAST = ["Przykładowy", "Testowa", "Makietowy", "Fikcyjna", "Wzorcowy"];
const BULK_OWNERS: PersonRef[] = [
  natalia,
  { id: 9301, name: "Opiekun Drugi" },
  { id: 9302, name: "Opiekunka Trzecia" },
];

/**
 * Jak prod 20.10.2026: setki zaległych rozmów w „Wszyscy w moim zakresie”
 * (`?state=list&big=1`). Terminy od wczoraj do ~90 dni wstecz, trzech opiekunów.
 */
function bulkOverdue(today: string, count: number): WeekContact[] {
  return Array.from({ length: count }, (_, i) => {
    const days = 1 + ((i * 37) % 90);
    const dueOn = shiftDay(today, -days);
    return contact({
      contract_id: 20_000 + i,
      candidate_id: 30_000 + i,
      candidate_name: `${BULK_FIRST[i % BULK_FIRST.length]} ${BULK_LAST[i % BULK_LAST.length]} ${i + 1}`,
      job_title: "Developer",
      owner: BULK_OWNERS[i % BULK_OWNERS.length],
      reasons: [
        {
          kind: "cadence",
          label: "Rozmowa według rytmu",
          due_on: dueOn,
          overdue: true,
          plan_item_id: null,
          from_conversation_on: null,
        },
      ],
      due_on: dueOn,
      overdue: true,
      overdue_days: days,
    });
  });
}

export function careWeek(today: string, scope: "mine" | "all", bulk = 0): CareWeek {
  const { from, to } = weekBounds(today);
  const karolinaStart = shiftDay(today, -33);
  const karolinaEnd = shiftDay(today, 25);
  const pawelEnd = shiftDay(to, 30);
  const michalStart = contractStart(today);

  const feedback: WeekFeedback[] = [
    {
      contact_id: 8801,
      contact_name: "Katarzyna Kierownicza",
      position: "QA Lead",
      client_id: HR_CLIENTS.telecom.id,
      client_name: HR_CLIENTS.telecom.name,
      area: { id: 311, name: "QA" },
      reasons: ["pre_end"],
      due_on: shiftDay(karolinaEnd, -30),
      overdue: true,
      last_feedback: null,
      consultants: [
        consultant(KAROLINA_CONTRACT, HR_CONSULTANTS.karolina, "Testerka automatyzująca", karolinaEnd),
      ],
    },
    {
      contact_id: 8802,
      contact_name: "Piotr Menedżerski",
      position: "Kierownik zespołu Data",
      client_id: CARE_CLIENT.id,
      client_name: CARE_CLIENT.name,
      area: { id: 303, name: "Data" },
      reasons: ["quarterly"],
      due_on: shiftDay(today, -2),
      overdue: true,
      last_feedback: { session_id: 71, held_on: shiftDay(today, -92), average: 4 },
      consultants: [
        consultant(CARE_CONTRACT_ID, HR_CONSULTANTS.michal, "Java Developer", null),
        consultant(4503, HR_CONSULTANTS.bartosz, "DevOps Engineer", null),
      ],
    },
  ];

  const contacts: WeekContact[] = [
    contact({
      contract_id: KAROLINA_CONTRACT,
      candidate_id: HR_CONSULTANTS.karolina.id,
      candidate_name: HR_CONSULTANTS.karolina.name,
      client_id: HR_CLIENTS.telecom.id,
      client_name: HR_CLIENTS.telecom.name,
      job_title: "Testerka automatyzująca",
      start_date: karolinaStart,
      end_date: karolinaEnd,
      reasons: [
        {
          kind: "day_30",
          label: "Dzień 30",
          due_on: shiftDay(karolinaStart, 30),
          overdue: true,
          plan_item_id: 902,
          from_conversation_on: null,
        },
      ],
      due_on: shiftDay(karolinaStart, 30),
      overdue: true,
      overdue_days: 3,
      plan_item_id: 902,
      manager: {
        id: 8801,
        name: "Katarzyna Kierownicza",
        position: "QA Lead",
        area: { id: 311, name: "QA" },
      },
      last_conversation: {
        id: 31,
        occurred_on: shiftDay(karolinaStart, 8),
        satisfaction: 5,
        note_excerpt: "Dzień 7: dobrze, chce więcej pracy z automatyzacją testów.",
        signals: [],
      },
      front_office: { reasons: ["project_end"], handed_off_on: null },
    }),
    contact({
      contract_id: WEEK_HANDOFF_CONTRACT,
      candidate_id: HR_CONSULTANTS.pawel.id,
      candidate_name: HR_CONSULTANTS.pawel.name,
      job_title: "Java Developer",
      start_date: shiftDay(today, -300),
      end_date: pawelEnd,
      reasons: [
        {
          kind: "pre_end",
          label: "Przed końcem zamówienia",
          due_on: to,
          overdue: false,
          plan_item_id: 903,
          from_conversation_on: null,
        },
      ],
      due_on: to,
      plan_item_id: 903,
      last_conversation: {
        id: 32,
        occurred_on: shiftDay(today, -20),
        satisfaction: 4,
        note_excerpt: "Rozmowa kwartalna — chciałby projekt z większym zespołem.",
        signals: ["wants_change"],
      },
      signals: ["project_end", "wants_change"],
      front_office: { reasons: ["project_end", "wants_change"], handed_off_on: null },
    }),
    contact({
      contract_id: CARE_CONTRACT_ID,
      candidate_id: HR_CONSULTANTS.michal.id,
      candidate_name: HR_CONSULTANTS.michal.name,
      job_title: "Java Developer",
      start_date: michalStart,
      reasons: [
        {
          kind: "follow_up",
          label: "Umówiony kontakt",
          due_on: today < from ? from : today,
          overdue: false,
          plan_item_id: null,
          from_conversation_on: shiftDay(michalStart, 14),
        },
      ],
      due_on: today < from ? from : today,
      manager: {
        id: 8802,
        name: "Piotr Menedżerski",
        position: "Kierownik zespołu Data",
        area: { id: 303, name: "Data" },
      },
      last_conversation: {
        id: 12,
        occurred_on: shiftDay(michalStart, 14),
        satisfaction: null,
        note_excerpt: "Zapytać o certyfikat Azure.",
        signals: [],
      },
    }),
  ];
  const all =
    scope === "mine"
      ? contacts
      : [
          ...contacts,
          contact({
            contract_id: 4505,
            candidate_id: HR_CONSULTANTS.anna.id,
            candidate_name: HR_CONSULTANTS.anna.name,
            client_id: HR_CLIENTS.insurance.id,
            client_name: HR_CLIENTS.insurance.name,
            job_title: "Analityczka biznesowa",
            owner: { id: HR_CAST.kamil.id, name: HR_CAST.kamil.name },
            reasons: [
              {
                kind: "day_7",
                label: "Dzień 7",
                due_on: to,
                overdue: false,
                plan_item_id: 904,
                from_conversation_on: null,
              },
            ],
            due_on: to,
            plan_item_id: 904,
          }),
        ];
  const bulkRows = scope === "all" ? bulkOverdue(today, bulk) : [];
  return {
    week: { from, to, today, is_current: true },
    scope,
    contacts: [...all, ...bulkRows],
    feedback,
    feedback_visible: true,
    counts: {
      contacts: all.length + bulkRows.length,
      // Rozmowy zapisane od poniedziałku (pasek tygodnia).
      done: scope === "mine" ? 2 : 4,
      overdue: 1 + bulkRows.length + feedback.filter((item) => item.overdue).length,
      feedback: feedback.length,
      front_office: 2,
    },
    can_edit: true,
    can_write_feedback: true,
  };
}

function event(
  kind: TimelineEvent["kind"],
  on: string,
  title: string,
  today: string,
  detail: string | null = null,
  link: string | null = null,
): TimelineEvent {
  return { kind, on, title, detail, link, future: on > today };
}

/** Oś Pawła — od rekrutacji po koniec zamówienia (makieta 7, panel boczny). */
export function pawelTimeline(today: string): ContractTimeline {
  const start = shiftDay(today, -300);
  const { to } = weekBounds(today);
  const end = shiftDay(to, 30);
  return {
    contract: {
      id: WEEK_HANDOFF_CONTRACT,
      candidate_id: HR_CONSULTANTS.pawel.id,
      candidate_name: HR_CONSULTANTS.pawel.name,
      client_id: CARE_CLIENT.id,
      client_name: CARE_CLIENT.name,
      job_id: 5101,
      job_title: "Java Developer",
      status: "ending",
      is_live: true,
      start_date: start,
      end_date: end,
    },
    owner: natalia,
    manager: {
      id: 8803,
      name: "Michał Rogalski-Przykładowy",
      position: "Kierownik Płatności",
      area: { id: 301, name: "Płatności" },
    },
    signals: ["project_end", "wants_change"],
    front_office_reasons: ["project_end", "wants_change"],
    events: [
      event("recruitment", shiftDay(start, -40), "Rekrutacja „Java Developer”", today, "front office · prowadzi Kamil Testowy", "/jobs/5101"),
      event("start", start, "Start kontraktu", today, "Java Developer"),
      event("order_start", start, "Zamówienie „ZAM/2026/014”", today, "aktywne"),
      event("feedback", shiftDay(today, -105), "Opinia: Michał Rogalski-Przykładowy", today, "4,0/5 · przedłużenie: tak"),
      event(
        "conversation",
        shiftDay(today, -20),
        "Rozmowa · kontakt kwartalny",
        today,
        "chce zmiany projektu · zadowolenie 4/5 · „Rozmowa kwartalna — chciałby projekt z większym zespołem.”",
      ),
      event("redeploy", shiftDay(today, -20), "Do przepięcia: chce zmiany projektu", today, "nowe"),
      { ...event("plan", to, "Kontakt: przed końcem zamówienia", today), future: true },
      event("order_end", end, "Koniec zamówienia „ZAM/2026/014”", today),
    ],
    feedback_visible: true,
    can_edit: true,
  };
}

/** Krótka oś pozostałych osób z listy (start i ostatnia rozmowa). */
export function shortTimeline(today: string, row: WeekContact): ContractTimeline {
  return {
    contract: {
      id: row.contract_id,
      candidate_id: row.candidate_id,
      candidate_name: row.candidate_name,
      client_id: row.client_id,
      client_name: row.client_name,
      job_id: null,
      job_title: row.job_title,
      status: "active",
      is_live: true,
      start_date: row.start_date,
      end_date: row.end_date,
    },
    owner: natalia,
    manager: row.manager,
    signals: row.signals,
    front_office_reasons: row.front_office.reasons,
    events: [
      ...(row.start_date ? [event("start", row.start_date, "Start kontraktu", today, row.job_title)] : []),
      ...(row.last_conversation
        ? [
            event(
              "conversation",
              row.last_conversation.occurred_on,
              "Rozmowa",
              today,
              row.last_conversation.note_excerpt,
            ),
          ]
        : []),
      ...(row.end_date ? [event("order_end", row.end_date, "Koniec zamówienia", today)] : []),
    ],
    feedback_visible: true,
    can_edit: true,
  };
}

/** „Przekaż do front office” dla Pawła — dwie pasujące rekrutacje z silnika „Pasuje też do”. */
export function pawelFrontOffice(today: string): FrontOfficeOverview {
  const { to } = weekBounds(today);
  return {
    contract_id: WEEK_HANDOFF_CONTRACT,
    eligible: true,
    reasons: ["project_end", "wants_change"],
    end_date: shiftDay(to, 30),
    status: "ok",
    jobs: [
      {
        job_id: 5301,
        title: "Java Developer (Kredyty)",
        client_name: HR_CLIENTS.bank.name,
        client_reference: null,
        score: 84,
        matching_must: ["Java 17", "Spring Boot"],
        gap_must: [],
      },
      {
        job_id: 5302,
        title: "Backend Developer",
        client_name: HR_CLIENTS.clinic.name,
        client_reference: "ZAP-112",
        score: 76,
        matching_must: ["Java 17"],
        gap_must: ["Kotlin"],
      },
    ],
    handoffs: [],
    can_edit: true,
  };
}

/** Karolina kończy projekt, nic teraz nie pasuje. */
export function karolinaFrontOffice(today: string): FrontOfficeOverview {
  return {
    contract_id: KAROLINA_CONTRACT,
    eligible: true,
    reasons: ["project_end"],
    end_date: shiftDay(today, 25),
    status: "ok",
    jobs: [],
    handoffs: [],
    can_edit: true,
  };
}

/** Mapa Telekomu Wzorcowego dla pytań w oknie rozmowy z Karoliną (dział QA). */
export function telecomTechMap(today: string): ClientTechMap {
  const base = clientTechMap(today);
  return {
    ...base,
    client_id: HR_CLIENTS.telecom.id,
    client_name: HR_CLIENTS.telecom.name,
    departments: [],
    gaps: [
      {
        kind: "manager_unplaced",
        contact: { id: 8801, name: "Katarzyna Kierownicza" },
        position: "QA Lead",
        area: { id: 311, name: "QA" },
        consultants: 1,
      },
      {
        kind: "single_source",
        skill_id: 809,
        name: "Playwright",
        source: "jobs",
        refs: 1,
        last_seen: shiftDay(today, -40),
        areas: ["QA"],
      },
    ],
  };
}
