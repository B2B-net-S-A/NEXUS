/**
 * Karty opieki na wspólnej tablicy (`/preview/hr-cases?state=board-care|todo|
 * todo-list|panel-care`) — wyłącznie dane fikcyjne. Odpowiedź jak
 * `GET /api/care/board` i skrót Karty konsultanta (`GET /api/care/contracts/{id}/card`).
 * Terminy liczone od „dziś” przeglądarki.
 */

import type { CareContractCardSummary } from "@/lib/api/care";
import type { CareBoard, CareBoardCard } from "@/lib/api/care-board";

import { HR_CAST, HR_CLIENTS, HR_CONSULTANTS, shiftDay } from "../hr-fixtures";

const { natalia, adam } = HR_CAST;
const MANAGER = { contact_id: 5501, name: "Ewa Kierownicza" };

/** Karta otwarta w stanie `panel-care`. */
export const PANEL_CARE_KEY = "contact:plan:7101";

function base(today: string, input: Partial<CareBoardCard> & Pick<CareBoardCard, "key" | "kind" | "title">): CareBoardCard {
  return {
    column: "new",
    subtitle: null,
    reason_label: null,
    due_on: today,
    overdue_days: 0,
    scheduled_at: null,
    retry_on: null,
    note_excerpt: null,
    contract_id: null,
    candidate_id: null,
    client_id: null,
    client_name: null,
    manager: null,
    owner_user_id: natalia.id,
    owner_name: natalia.name,
    health: null,
    ...input,
  };
}

function mineCards(today: string): CareBoardCard[] {
  return [
    base(today, {
      key: PANEL_CARE_KEY,
      kind: "contact",
      title: `Rozmowa: ${HR_CONSULTANTS.michal.name}`,
      subtitle: `${HR_CLIENTS.bank.name} · menedżer: ${MANAGER.name}`,
      reason_label: "rozmowa z rytmu",
      due_on: shiftDay(today, -3),
      overdue_days: 3,
      note_excerpt: "Projekt kończy się w grudniu, pyta o kolejny.",
      contract_id: 4501,
      candidate_id: HR_CONSULTANTS.michal.id,
      client_id: HR_CLIENTS.bank.id,
      client_name: HR_CLIENTS.bank.name,
      manager: MANAGER,
      last_satisfaction: 3,
      health: {
        level: "risk",
        label: "Ryzyko",
        reasons: ["chce zmiany projektu (01.10)", "zamówienie kończy się za 32 dni"],
      },
    }),
    base(today, {
      key: "contact:followup:8801",
      kind: "contact",
      column: "in_progress",
      title: `Rozmowa: ${HR_CONSULTANTS.karolina.name}`,
      subtitle: `${HR_CLIENTS.telecom.name} · Analityczka danych`,
      reason_label: "umówiony kontakt",
      due_on: shiftDay(today, 1),
      scheduled_at: `${shiftDay(today, 1)}T09:30:00Z`,
      contract_id: 4502,
      candidate_id: HR_CONSULTANTS.karolina.id,
      client_id: HR_CLIENTS.telecom.id,
      client_name: HR_CLIENTS.telecom.name,
      health: { level: "watch", label: "Uwaga", reasons: ["ostatnie zadowolenie 3"] },
    }),
    base(today, {
      key: "contact:plan:7102",
      kind: "contact",
      column: "waiting",
      title: `Rozmowa: ${HR_CONSULTANTS.bartosz.name}`,
      subtitle: `${HR_CLIENTS.bank.name} · menedżer: ${MANAGER.name}`,
      reason_label: "dzień 7",
      due_on: shiftDay(today, -1),
      overdue_days: 1,
      retry_on: shiftDay(today, 2),
      note_excerpt: "Nie odbiera — oddzwoni po spotkaniu zespołu.",
      contract_id: 4503,
      candidate_id: HR_CONSULTANTS.bartosz.id,
      client_id: HR_CLIENTS.bank.id,
      client_name: HR_CLIENTS.bank.name,
      health: { level: "ok", label: "Dobrze", reasons: [] },
    }),
    base(today, {
      key: "feedback:5501",
      kind: "feedback",
      title: `Opinia: ${MANAGER.name}`,
      subtitle: `${HR_CLIENTS.bank.name} · 2 konsultantów`,
      reason_label: "przed końcem zamówienia",
      due_on: shiftDay(today, 2),
      client_id: HR_CLIENTS.bank.id,
      client_name: HR_CLIENTS.bank.name,
      manager: MANAGER,
      consultants: [
        { contract_id: 4501, name: HR_CONSULTANTS.michal.name },
        { contract_id: 4503, name: HR_CONSULTANTS.bartosz.name },
      ],
    }),
    base(today, {
      key: "decision:301",
      kind: "decision",
      title: `Decyzja: ${HR_CONSULTANTS.pawel.name}`,
      subtitle: `${HR_CLIENTS.clinic.name} · koniec projektu za 41 dni`,
      reason_label: "koniec projektu",
      due_on: null,
      contract_id: 4504,
      candidate_id: HR_CONSULTANTS.pawel.id,
      client_id: HR_CLIENTS.clinic.id,
      client_name: HR_CLIENTS.clinic.name,
      health: { level: "watch", label: "Uwaga", reasons: ["koniec bez decyzji za 41 dni"] },
    }),
    base(today, {
      key: "demand:7003:9901",
      kind: "demand",
      title: `Popyt: ${HR_CLIENTS.clinic.name}`,
      subtitle: "dział Platformy · 2 role",
      reason_label: "z rozmowy opiekuna",
      due_on: null,
      client_id: HR_CLIENTS.clinic.id,
      client_name: HR_CLIENTS.clinic.name,
      owner_user_id: adam.id,
      owner_name: adam.name,
      demand: {
        roles: ["Java Developer", "Tester automatyzujący"],
        source: "konsultant widział ogłoszenie",
        area: { id: 12, name: "Platformy" },
        conversation_id: 9901,
      },
    }),
  ];
}

export function careBoard(today: string, weekEnd: string, scope: "mine" | "all"): CareBoard {
  const cards = mineCards(today);
  if (scope === "all") {
    cards.push(
      base(today, {
        key: "contact:plan:7104",
        kind: "contact",
        title: `Rozmowa: ${HR_CONSULTANTS.anna.name}`,
        subtitle: `${HR_CLIENTS.insurance.name} · start za 18 dni`,
        reason_label: "przed startem",
        due_on: weekEnd,
        contract_id: 4505,
        candidate_id: HR_CONSULTANTS.anna.id,
        client_id: HR_CLIENTS.insurance.id,
        client_name: HR_CLIENTS.insurance.name,
        owner_user_id: adam.id,
        owner_name: adam.name,
        health: { level: "ok", label: "Dobrze", reasons: ["brak rozmów — kontrakt startuje"] },
      }),
    );
  }
  return {
    today,
    week_end: weekEnd,
    cards,
    done: {
      this_week: 3,
      recent: [
        { key: "contact:plan:7090", kind: "contact", title: `Rozmowa: ${HR_CONSULTANTS.pawel.name}`, done_on: shiftDay(today, -1) },
        { key: "feedback:5502", kind: "feedback", title: "Opinia: Robert Działowy", done_on: shiftDay(today, -2) },
      ],
    },
  };
}

/** Skrót Karty konsultanta dla kart z kontraktem. */
export function contractCards(today: string): CareContractCardSummary[] {
  const card = (
    contractId: number,
    person: { id: number; name: string },
    client: { id: number; name: string },
    extra: Partial<CareContractCardSummary>,
  ): CareContractCardSummary => ({
    contract_id: contractId,
    candidate_id: person.id,
    candidate_name: person.name,
    client_id: client.id,
    client_name: client.name,
    role: "Programista Java",
    form: "B2B",
    start_on: shiftDay(today, -400),
    end_on: null,
    owner: { user_id: natalia.id, name: natalia.name, source: "contract" },
    cadence: { level: "monthly", label: "co miesiąc", until_on: null },
    health: null,
    kpis: { last_contact: null, satisfaction: null, order_end: null },
    known_project: null,
    cases: [],
    ...extra,
  });
  return [
    card(4501, HR_CONSULTANTS.michal, HR_CLIENTS.bank, {
      kpis: {
        last_contact: { on: shiftDay(today, -34), days_ago: 34 },
        satisfaction: { value: 3, previous: 4 },
        order_end: { on: shiftDay(today, 32), days: 32 },
      },
      known_project: {
        manager: { contact_id: MANAGER.contact_id, name: MANAGER.name, position: "Kierowniczka zespołu płatności" },
      },
      cases: [
        {
          id: 931,
          title: "Negocjacje: przedłużenie zamówienia",
          area: "negotiation",
          area_label: "Negocjacje",
          status: "in_progress",
          status_label: "W toku",
          due_on: shiftDay(today, 6),
          follow_up_on: null,
          assignee_name: natalia.name,
          source: "manual",
          content_hidden: true,
        },
      ],
    }),
    card(4502, HR_CONSULTANTS.karolina, HR_CLIENTS.telecom, {}),
    card(4503, HR_CONSULTANTS.bartosz, HR_CLIENTS.bank, {}),
    card(4504, HR_CONSULTANTS.pawel, HR_CLIENTS.clinic, {}),
  ];
}
