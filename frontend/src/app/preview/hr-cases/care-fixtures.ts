/**
 * Karty opieki na wspólnej tablicy (`/preview/hr-cases?state=board-care|todo|
 * todo-list|panel-care`) — wyłącznie dane fikcyjne. Każdy stan z makiet K1–K3,
 * P1 i R4: rozmowa po terminie, umówiona, „nie odbiera”, opinia „czeka od”,
 * decyzja z rozmowy i z samego końca zamówienia, popyt z menedżerem i bez,
 * „Dane do uzupełnienia”, postęp tygodnia. Odpowiedź jak
 * `GET /api/care/board` i skrót Karty konsultanta (`GET /api/care/contracts/{id}/card`).
 * Terminy liczone od „dziś” przeglądarki.
 */

import type { CareContractCardSummary } from "@/lib/api/care";
import type { CareBoard, CareBoardCard } from "@/lib/api/care-board";

import { HR_CAST, HR_CLIENTS, HR_CONSULTANTS, shiftDay } from "../hr-fixtures";

const { natalia, adam } = HR_CAST;
const MANAGER = { contact_id: 5501, name: "Ewa Kierownicza" };
const TELECOM_MANAGER = { contact_id: 5503, name: "Katarzyna Kierownicza" };

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

/** Umówiona rozmowa: jutro 14:00 czasu firmy (12:00 UTC zimą — harness i tak liczy od „dziś”). */
function at(day: string, time: string): string {
  return new Date(`${day}T${time}:00`).toISOString();
}

function mineCards(today: string): CareBoardCard[] {
  return [
    // K1/K2: rozmowa dzień 30 po terminie — panel `panel-care`.
    base(today, {
      key: PANEL_CARE_KEY,
      kind: "contact",
      title: HR_CONSULTANTS.karolina.name,
      subtitle: `${HR_CLIENTS.telecom.name} · QA`,
      role_label: "QA",
      reason_kind: "day_30",
      reason_label: "Dzień 30",
      due_on: shiftDay(today, -3),
      overdue_days: 3,
      note_excerpt: "Dobrze, chce więcej pracy z automatyzacją.",
      note_on: shiftDay(today, -26),
      contract_id: 4502,
      candidate_id: HR_CONSULTANTS.karolina.id,
      client_id: HR_CLIENTS.telecom.id,
      client_name: HR_CLIENTS.telecom.name,
      end_on: shiftDay(today, 24),
      manager: { ...TELECOM_MANAGER, feedback_due_on: shiftDay(today, -6) },
      last_satisfaction: 5,
      health: {
        level: "watch",
        label: "Uwaga",
        reasons: ["rozmowa „dzień 30” 3 dni po terminie", "trwa negocjacja warunków"],
      },
    }),
    // Umówiona: plakietka „jutro · 14:00”, bez osobnej ramki.
    base(today, {
      key: "contact:followup:8801",
      kind: "contact",
      column: "in_progress",
      title: HR_CONSULTANTS.michal.name,
      subtitle: `${HR_CLIENTS.bank.name} · Data`,
      role_label: "Data",
      reason_kind: "follow_up",
      reason_label: "Umówiony kontakt",
      due_on: shiftDay(today, 1),
      scheduled_at: at(shiftDay(today, 1), "14:00"),
      note_excerpt: "Zapytać o certyfikat Azure.",
      note_on: shiftDay(today, -31),
      contract_id: 4501,
      candidate_id: HR_CONSULTANTS.michal.id,
      client_id: HR_CLIENTS.bank.id,
      client_name: HR_CLIENTS.bank.name,
      manager: { ...MANAGER, feedback_due_on: shiftDay(today, -3) },
      health: { level: "ok", label: "Dobrze", reasons: [] },
    }),
    // Czeka: „nie odbiera — spróbować …”.
    base(today, {
      key: "contact:plan:7102",
      kind: "contact",
      column: "waiting",
      title: HR_CONSULTANTS.bartosz.name,
      subtitle: `${HR_CLIENTS.telecom.name} · Java`,
      role_label: "Java",
      reason_kind: "pre_end",
      reason_label: "Przed końcem zamówienia",
      due_on: shiftDay(today, -1),
      overdue_days: 1,
      retry_on: shiftDay(today, 3),
      note_excerpt: "Prosi o rzadki kontakt.",
      note_on: shiftDay(today, -100),
      contract_id: 4503,
      candidate_id: HR_CONSULTANTS.bartosz.id,
      client_id: HR_CLIENTS.telecom.id,
      client_name: HR_CLIENTS.telecom.name,
      health: { level: "ok", label: "Dobrze", reasons: [] },
    }),
    // Opinia menedżera: „czeka od …”, „o: Michał K., Bartosz T.”.
    base(today, {
      key: "feedback:5501",
      kind: "feedback",
      title: MANAGER.name,
      subtitle: `${HR_CLIENTS.bank.name} · Kierowniczka zespołu płatności`,
      role_label: "Kierowniczka zespołu płatności",
      reason_label: "Kwartał bez opinii",
      due_on: shiftDay(today, -3),
      overdue_days: 3,
      client_id: HR_CLIENTS.bank.id,
      client_name: HR_CLIENTS.bank.name,
      manager: MANAGER,
      last_feedback: { held_on: shiftDay(today, -93), average: 4 },
      consultants: [
        { contract_id: 4501, name: HR_CONSULTANTS.michal.name },
        { contract_id: 4503, name: HR_CONSULTANTS.bartosz.name },
      ],
    }),
    // Decyzja z rozmowy („chce zmiany”).
    base(today, {
      key: "decision:301",
      kind: "decision",
      title: HR_CONSULTANTS.pawel.name,
      subtitle: `${HR_CLIENTS.bank.name} · Java`,
      role_label: "Java",
      reason_kind: "wants_change",
      reason_label: "Decyzja: chce zmiany projektu",
      due_on: null,
      note_excerpt: "Chciałby projekt z większym zespołem.",
      note_on: shiftDay(today, -21),
      contract_id: 4504,
      candidate_id: HR_CONSULTANTS.pawel.id,
      client_id: HR_CLIENTS.bank.id,
      client_name: HR_CLIENTS.bank.name,
      end_on: shiftDay(today, 31),
      health: { level: "risk", label: "Ryzyko", reasons: ["chce zmiany projektu", "zamówienie kończy się za 31 dni"] },
    }),
    // Popyt u DL: menedżer znany i otwarta rekrutacja.
    base(today, {
      key: "demand:7001:9901",
      kind: "demand",
      title: "Popyt do sprawdzenia: Java, QA",
      subtitle: `${HR_CLIENTS.bank.name} · Płatności`,
      reason_label: "Klient zatrudnia",
      due_on: null,
      note_excerpt: "Klient zatrudnia: Java, QA.",
      note_on: shiftDay(today, -14),
      client_id: HR_CLIENTS.bank.id,
      client_name: HR_CLIENTS.bank.name,
      owner_user_id: adam.id,
      owner_name: adam.name,
      manager: MANAGER,
      consultants: [{ contract_id: 4501, name: HR_CONSULTANTS.michal.name }],
      demand: {
        roles: ["Java", "QA"],
        source: "widział",
        area: { id: 12, name: "Płatności" },
        conversation_id: 9901,
        manager: MANAGER,
        open_job: { id: 8801, title: "Java Developer" },
      },
    }),
    // Popyt bez menedżera: „Uzupełnij menedżera” → drzewo osób klienta.
    base(today, {
      key: "demand:7004:9902",
      kind: "demand",
      title: "Popyt do sprawdzenia: .NET",
      subtitle: HR_CLIENTS.insurance.name,
      reason_label: "Klient zatrudnia",
      due_on: null,
      note_excerpt: ".NET",
      note_on: shiftDay(today, -22),
      client_id: HR_CLIENTS.insurance.id,
      client_name: HR_CLIENTS.insurance.name,
      owner_user_id: adam.id,
      owner_name: adam.name,
      demand: {
        roles: [".NET"],
        source: null,
        area: null,
        conversation_id: 9902,
        manager: null,
        open_job: null,
      },
    }),
    // Dane do uzupełnienia u klienta (P1).
    base(today, {
      key: `data:${HR_CLIENTS.telecom.id}`,
      kind: "data",
      title: HR_CLIENTS.telecom.name,
      subtitle: "klient · 6 konsultantów",
      reason_label: "Dane do uzupełnienia",
      due_on: null,
      client_id: HR_CLIENTS.telecom.id,
      client_name: HR_CLIENTS.telecom.name,
      owner_user_id: null,
      owner_name: null,
      data: { certain: 2, uncertain: 1, gaps: 3, consultants: 6 },
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
        title: HR_CONSULTANTS.anna.name,
        subtitle: `${HR_CLIENTS.insurance.name} · start za 18 dni`,
        reason_kind: "day_7",
        reason_label: "Dzień 7",
        due_on: weekEnd,
        contract_id: 4505,
        candidate_id: HR_CONSULTANTS.anna.id,
        client_id: HR_CLIENTS.insurance.id,
        client_name: HR_CLIENTS.insurance.name,
        owner_user_id: adam.id,
        owner_name: adam.name,
        health: { level: "ok", label: "Dobrze", reasons: ["brak rozmów — kontrakt startuje"] },
      }),
      // Koniec zamówienia ≤ 60 dni bez wpisu „Do przepięcia” — pierwszy ruch go zakłada.
      base(today, {
        key: "decision:end:4506",
        kind: "decision",
        title: "Tomasz Podglądowy",
        subtitle: `${HR_CLIENTS.clinic.name} · Analityk`,
        role_label: "Analityk",
        reason_kind: "project_end",
        reason_label: "Decyzja: koniec projektu",
        due_on: shiftDay(today, 41),
        contract_id: 4506,
        client_id: HR_CLIENTS.clinic.id,
        client_name: HR_CLIENTS.clinic.name,
        end_on: shiftDay(today, 41),
        owner_user_id: adam.id,
        owner_name: adam.name,
        health: { level: "watch", label: "Uwaga", reasons: ["koniec bez decyzji za 41 dni"] },
      }),
    );
  }
  return {
    today,
    week_end: weekEnd,
    cards,
    week_progress: { done: 2, total: 6 },
    done: {
      this_week: 5,
      recent: [
        { key: "contact:plan:7090", kind: "contact", title: `Rozmowa: ${HR_CONSULTANTS.bartosz.name}`, done_on: shiftDay(today, -1) },
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
    card(4502, HR_CONSULTANTS.karolina, HR_CLIENTS.telecom, {
      role: "QA",
      cadence: { level: "biweekly", label: "co 2 tygodnie", until_on: shiftDay(today, 60) },
      kpis: {
        last_contact: { on: shiftDay(today, -26), days_ago: 26 },
        satisfaction: { value: 5, previous: 4 },
        order_end: { on: shiftDay(today, 24), days: 24 },
      },
      known_project: {
        manager: { contact_id: TELECOM_MANAGER.contact_id, name: TELECOM_MANAGER.name, position: "Kierowniczka QA" },
      },
      cases: [
        {
          id: 904,
          title: "Negocjacje stawki",
          area: "negotiation",
          area_label: "Negocjacje",
          status: "in_progress",
          status_label: "W toku",
          due_on: shiftDay(today, 5),
          follow_up_on: null,
          assignee_name: natalia.name,
          source: "manual",
          content_hidden: true,
        },
        {
          id: 906,
          title: "Ubezpieczenie OC konsultanta",
          area: "administration",
          area_label: "Administracja",
          status: "waiting",
          status_label: "Czeka na kogoś",
          due_on: shiftDay(today, 12),
          follow_up_on: shiftDay(today, 4),
          assignee_name: "Zofia Recepcyjna",
          source: "mail",
          content_hidden: false,
        },
      ],
    }),
    card(4503, HR_CONSULTANTS.bartosz, HR_CLIENTS.bank, {}),
    card(4504, HR_CONSULTANTS.pawel, HR_CLIENTS.clinic, {}),
  ];
}
