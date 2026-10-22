/**
 * Dane harnessu „Sprawy administracja@” (`/preview/hr-cases`) — wyłącznie
 * fikcyjne. Układ tablicy jak w makiecie 11: Nowa 3 (dwie z maila, jedna
 * z odejścia), W toku 2, Czeka na kogoś 1, Zrobione z licznikiem miesiąca.
 * Terminy liczymy od „dziś” przeglądarki, żeby karty nie wpadały „po terminie”.
 */

import type {
  AssigneeOption,
  CaseArea,
  CaseCard,
  CaseChecklistItem,
  CaseContractRef,
  CaseDetail,
  CaseList,
  CaseListFilters,
  CasePersonRef,
} from "@/lib/api/admin-cases";

import { HR_CAST, HR_CLIENTS, HR_CONSULTANTS, shiftDay } from "../hr-fixtures";

/** Sprawa onboardingu Anny — stan `?state=detail`. */
export const ONBOARDING_CASE_ID = 901;
/** Mail z firmy klienta bez kontraktu — stan `?state=who` („Kogo dotyczy?”). */
export const WHO_CASE_ID = 909;

const person = (p: { id: number; name: string }): CasePersonRef => ({ id: p.id, name: p.name });
const { zofia, natalia, julia, paulina, tomasz } = HR_CAST;

const PRIORITY_ORDER = { P1: 0, P2: 1, P3: 2 } as const;

/** „2026-11-02” → „2.11” (jak w treści maila). */
function dayMonth(day: string): string {
  const [, month, date] = day.split("-");
  return `${Number(date)}.${month}`;
}

function at(day: string, time = "09:00:00"): string {
  return `${day}T${time}Z`;
}

function annaContract(today: string): CaseContractRef {
  return {
    id: 4505,
    candidate_name: HR_CONSULTANTS.anna.name,
    client_name: HR_CLIENTS.insurance.name,
    start_date: shiftDay(today, 18),
    end_date: null,
    care_owner_user_id: natalia.id,
    care_owner_name: natalia.name,
    candidate_id: HR_CONSULTANTS.anna.id,
    health: { level: "ok", label: "Dobrze", reasons: ["brak rozmów — kontrakt startuje"] },
  };
}

function karolinaContract(today: string): CaseContractRef {
  return {
    id: 4502,
    candidate_name: HR_CONSULTANTS.karolina.name,
    client_name: HR_CLIENTS.telecom.name,
    start_date: shiftDay(today, -33),
    end_date: null,
    care_owner_user_id: natalia.id,
    care_owner_name: natalia.name,
    candidate_id: HR_CONSULTANTS.karolina.id,
    health: {
      level: "watch",
      label: "Uwaga",
      reasons: ["zaległa rozmowa (3 dni)", "ostatnie zadowolenie 3"],
    },
  };
}

function onboardingChecklist(): CaseChecklistItem[] {
  return [
    { text: "Wniosek o dostęp VPN u klienta", done: true },
    { text: "Badania lekarskie", done: false },
    { text: "Szkolenie BHP", done: false },
    { text: "Zestaw sprzętu — podpis protokołu w ewidencji", done: false },
  ];
}

type CardInput = Partial<CaseCard> & Pick<CaseCard, "id" | "title" | "area" | "priority" | "status">;

function card(today: string, input: CardInput): CaseCard {
  const created = input.created_at ?? at(shiftDay(today, -2));
  return {
    due_on: null,
    follow_up_on: null,
    overdue: false,
    assignee: null,
    subject_user: null,
    contract: null,
    source: "manual",
    checklist_done: 0,
    checklist_total: 0,
    updated_at: created,
    closed_at: null,
    ...input,
    created_at: created,
  };
}

function allCards(today: string): CaseCard[] {
  const checklist = onboardingChecklist();
  return [
    card(today, {
      id: ONBOARDING_CASE_ID,
      title: `Onboarding: ${HR_CONSULTANTS.anna.name}`,
      area: "onboarding",
      priority: "P1",
      status: "new",
      due_on: shiftDay(today, 2),
      assignee: person(zofia),
      contract: annaContract(today),
      source: "mail",
      checklist_done: checklist.filter((item) => item.done).length,
      checklist_total: checklist.length,
      created_at: at(shiftDay(today, -1), "08:15:00"),
    }),
    card(today, {
      id: 902,
      title: "Faktura za szkolenie BHP",
      area: "administration",
      priority: "P3",
      status: "new",
      due_on: shiftDay(today, 10),
      source: "mail",
    }),
    card(today, {
      id: 903,
      title: `Offboarding: ${tomasz.name}`,
      area: "offboarding",
      priority: "P2",
      status: "new",
      due_on: shiftDay(today, 46),
      subject_user: person(tomasz),
      source: "lifecycle",
      checklist_total: 2,
    }),
    card(today, {
      id: 904,
      title: `Negocjacje stawki: ${HR_CONSULTANTS.karolina.name}`,
      area: "negotiation",
      priority: "P2",
      status: "in_progress",
      due_on: shiftDay(today, 5),
      assignee: person(natalia),
      contract: karolinaContract(today),
    }),
    card(today, {
      id: 905,
      title: "Post na LinkedIn: kariera",
      area: "marketing",
      priority: "P3",
      status: "in_progress",
      assignee: person(julia),
    }),
    card(today, {
      id: 906,
      title: "Ubezpieczenie OC konsultanta",
      area: "administration",
      priority: "P2",
      status: "waiting",
      due_on: shiftDay(today, 12),
      follow_up_on: shiftDay(today, 4),
      assignee: person(zofia),
    }),
    card(today, {
      id: 907,
      title: `Onboarding: ${HR_CONSULTANTS.karolina.name}`,
      area: "onboarding",
      priority: "P2",
      status: "done",
      assignee: person(paulina),
      contract: karolinaContract(today),
      source: "contract",
      checklist_done: 4,
      checklist_total: 4,
      closed_at: at(shiftDay(today, -29)),
    }),
    card(today, {
      id: WHO_CASE_ID,
      title: "Pytanie o fakturę od działu zakupów",
      area: "administration",
      priority: "P2",
      status: "new",
      due_on: shiftDay(today, 3),
      source: "mail",
      created_at: at(today, "07:05:00"),
    }),
    card(today, {
      id: 908,
      title: "Faktura za szkolenie z Excela",
      area: "administration",
      priority: "P3",
      status: "closed",
      assignee: person(zofia),
      source: "mail",
      closed_at: at(shiftDay(today, -20)),
    }),
  ];
}

const OPEN = new Set(["new", "in_progress", "waiting"]);

/** Piątek tygodnia `today` (jak serwer: w weekend — piątek, który minął). */
export function weekEnd(today: string): string {
  const [y, m, d] = today.split("-").map(Number);
  const weekday = (new Date(Date.UTC(y, m - 1, d)).getUTCDay() + 6) % 7; // pon = 0
  return shiftDay(today, 4 - weekday);
}

/** Odpowiedź `GET /api/cases` dla filtrów tablicy (kolejność serwera: priorytet, termin). */
export function caseList(
  today: string,
  filters: CaseListFilters,
  viewerId: number = zofia.id,
): CaseList {
  const friday = weekEnd(today);
  // Zdrowie relacji widzi tylko krąg D11 (opiekunka) — recepcja dostaje `null`.
  const scoped = allCards(today)
    .map((item) =>
      item.contract && viewerId !== natalia.id
        ? { ...item, contract: { ...item.contract, health: null } }
        : item,
    )
    .filter((item) => !filters.mine || item.assignee?.id === viewerId)
    .filter((item) => !filters.mine_care || item.contract?.care_owner_user_id === viewerId);
  const open = scoped.filter((item) => OPEN.has(item.status));
  const areas: CaseList["counts"] = {
    areas: {},
    week: 0,
    unassigned: 0,
    mine_care: allCards(today).filter(
      (item) => OPEN.has(item.status) && item.contract?.care_owner_user_id === viewerId,
    ).length,
  };
  for (const item of open) {
    areas.areas[item.area] = (areas.areas[item.area] ?? 0) + 1;
    if (item.due_on && item.due_on <= friday) areas.week += 1;
    if (!item.assignee) areas.unassigned += 1;
  }
  const items = scoped
    .filter((item) => !filters.area || item.area === filters.area)
    .filter((item) => filters.include_closed || item.status !== "closed")
    .filter(
      (item) => !filters.week || (OPEN.has(item.status) && !!item.due_on && item.due_on <= friday),
    )
    .filter((item) => !filters.unassigned || (OPEN.has(item.status) && !item.assignee))
    .sort(
      (a, b) =>
        PRIORITY_ORDER[a.priority] - PRIORITY_ORDER[b.priority] ||
        (a.due_on ?? "9999").localeCompare(b.due_on ?? "9999"),
    );
  return {
    items,
    total: items.length,
    truncated: false,
    done_this_month: 41,
    counts: areas,
    today,
    week_end: friday,
    can_manage: true,
  };
}

/** Obszary filtra tablicy (`null` = wszystkie). */
export const BOARD_AREAS: (CaseArea | null)[] = [
  null,
  "onboarding",
  "offboarding",
  "negotiation",
  "administration",
  "marketing",
  "other",
];

/** `d11` — oglądający z kręgu D11 widzi zdrowie relacji, reszta dostaje `null`. */
export function onboardingCase(today: string, d11 = false): CaseDetail {
  const card = allCards(today).find((item) => item.id === ONBOARDING_CASE_ID) as CaseCard;
  const start = dayMonth(shiftDay(today, 18));
  const contract = { ...annaContract(today), ...(d11 ? {} : { health: null }) };
  const base = { ...card, contract };
  const received = shiftDay(today, -1);
  return {
    ...base,
    description:
      `Start ${start} u klienta ${HR_CLIENTS.insurance.name}. Przed pierwszym dniem: dostęp VPN, ` +
      "badania i szkolenie BHP. Zestaw sprzętu czeka na podpis protokołu w ewidencji sprzętu.",
    checklist: onboardingChecklist(),
    lifecycle_case_id: null,
    created_by: null,
    messages: [
      {
        id: 1,
        sender_email: "kadry.ubezpieczenia@example.com",
        sender_name: `Kadry — ${HR_CLIENTS.insurance.name}`,
        subject: `Nowa osoba w projekcie od ${start}`,
        received_at: at(received, "08:12:00"),
        body_text:
          `Dzień dobry,\nod ${start} do zespołu dołącza ${HR_CONSULTANTS.anna.name}. ` +
          "Prosimy o potwierdzenie badań i szkolenia BHP oraz dane do wniosku o dostęp VPN.\n" +
          "Pozdrawiamy",
        attachments: [
          { name: "wniosek-vpn.docx", content_type: null, size: 48_000, inline: false },
          { name: "logo.png", content_type: "image/png", size: 4_000, inline: true },
        ],
      },
    ],
    comments: [
      {
        id: 1,
        author: person(zofia),
        body: "Wniosek VPN wysłany. Badania do umówienia, czekam na termin szkolenia BHP.",
        created_at: at(today, "07:40:00"),
      },
    ],
    can_manage: true,
    can_comment: true,
    consultant: {
      contract_id: contract.id,
      candidate_name: contract.candidate_name,
      client_name: contract.client_name,
      role: "Analityczka biznesowa",
      form: "B2B",
      order_end_on: shiftDay(today, 200),
      // S4: szkic kolejnego zamówienia — „przedłużenie w toku” przy końcu zamówienia.
      order_extension_pending: true,
      owner_user_id: natalia.id,
      owner_name: natalia.name,
      cadence_label: "co 2 tygodnie (pierwsze 90 dni)",
      last_conversation: { on: shiftDay(today, -9), excerpt: "Prosi o rzadki kontakt." },
      other_open_cases: 0,
      health: contract.health ?? null,
    },
  };
}

/**
 * Ta sama sprawa onboardingu oglądana przez osobę przypisaną BEZ uprawnienia
 * „Sprawy” (S4): serwer nie wysyła karty konsultanta (`consultant: null`),
 * a bez `can_manage` nie ma akcji ani „Weź”.
 */
export function onboardingCaseForAssignee(today: string, viewer: CasePersonRef): CaseDetail {
  return {
    ...onboardingCase(today),
    assignee: viewer,
    can_manage: false,
    consultant: null,
  };
}

/**
 * Sprawa z maila z firmy klienta bez kontraktu — „Kogo dotyczy?” (S4): nadawca
 * to kontakt klienta, w treści nazwisko jedynej naszej konsultantki o tym
 * nazwisku u tego klienta. Bez osoby — w „Szczegółach” stoi „Weź”.
 */
export function whoCase(today: string): CaseDetail {
  const base = allCards(today).find((item) => item.id === WHO_CASE_ID) as CaseCard;
  return {
    ...base,
    description: null,
    checklist: [],
    lifecycle_case_id: null,
    created_by: null,
    messages: [
      {
        id: 2,
        sender_email: "zakupy@ubezpieczenia-fikcyjne.example.com",
        sender_name: "Katarzyna Zakupowa",
        subject: `Faktura za październik — ${HR_CONSULTANTS.anna.name}`,
        received_at: at(today, "07:02:00"),
        body_text:
          `Dzień dobry,\nna fakturze za październik dla ${HR_CONSULTANTS.anna.name} brakuje numeru zamówienia. ` +
          "Prosimy o korektę.\nPozdrawiamy",
        attachments: [],
      },
    ],
    comments: [],
    can_manage: true,
    can_comment: true,
    link_suggestions: [
      {
        contract_id: 4505,
        candidate_name: HR_CONSULTANTS.anna.name,
        client_name: HR_CLIENTS.insurance.name,
        reason: `Mail z firmy klienta, w treści: ${HR_CONSULTANTS.anna.name}`,
        sender_kind: "client_contact",
        sender_contact_name: "Katarzyna Zakupowa",
        only_match: true,
      },
    ],
  };
}

/** Obsługa skrzynki (6 osób) i osoby spoza niej. */
export const CASE_ASSIGNEES: AssigneeOption[] = [
  { id: zofia.id, name: zofia.name, handler: true },
  { id: paulina.id, name: paulina.name, handler: true },
  { id: julia.id, name: julia.name, handler: true },
  { id: HR_CAST.marta.id, name: HR_CAST.marta.name, handler: true },
  { id: HR_CAST.piotr.id, name: HR_CAST.piotr.name, handler: true },
  { id: HR_CAST.admin.id, name: HR_CAST.admin.name, handler: true },
  { id: natalia.id, name: natalia.name, handler: false },
];
