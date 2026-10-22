/**
 * Dane harnessu „Opieka · Konsultanci / Rytm / Przydział” (etap 3, makiety
 * M1–M3) — wyłącznie fikcyjne. Daty od „dziś” przeglądarki (`warsawToday`).
 * Ogląda Natalia (TCM, w harnessie także head back office — może przypisać
 * wielu konsultantów naraz i ustawić próg).
 */

import type {
  CareAutoAssignment,
  AssignmentRow,
  CadenceCurrent,
  CareAssignment,
  CareConsultants,
  ClientManagerRef,
  ConsultantRow,
  ContractCadence,
  Health,
  PersonRef,
} from "@/lib/api/care";

import { HR_CAST, HR_CLIENTS, HR_CONSULTANTS, shiftDay } from "../hr-fixtures";
import { CARE_CONTRACT_ID, contractStart } from "./fixtures";

const ref = (person: { id: number; name: string }): PersonRef => ({ id: person.id, name: person.name });
const natalia = ref(HR_CAST.natalia);
const kamil = ref(HR_CAST.kamil);
const adam = ref(HR_CAST.adam);

/** Konsultanci spoza obsady „Ludzi” — tylko w tym harnessie. */
const MORE = {
  tomasz: { id: 9201, name: "Tomasz Przykładowy" },
  olga: { id: 9202, name: "Olga Wzorcowa" },
  jakub: { id: 9203, name: "Jakub Makietowy" },
  marek: { id: 9204, name: "Marek Nowoprzyjęty" },
  iga: { id: 9205, name: "Iga Próbna" },
} as const;

export const BARTOSZ_CONTRACT = 4503;

const managers: Record<string, ClientManagerRef> = {
  qa: { id: 8801, name: "Katarzyna Kierownicza", position: "QA Lead", area: { id: 311, name: "QA" } },
  data: { id: 8802, name: "Piotr Menedżerski", position: "Kierownik zespołu Data", area: { id: 303, name: "Data" } },
  pay: { id: 8803, name: "Magda Zespołowa", position: "Kierowniczka Płatności", area: { id: 301, name: "Płatności" } },
};

function program(start: string): CadenceCurrent {
  return {
    level: "biweekly",
    source: "program",
    starts_on: start,
    until_on: shiftDay(start, 89),
    returns_to: "monthly",
    reason: null,
    note: null,
    author: null,
  };
}

function monthly(): CadenceCurrent {
  return {
    level: "monthly",
    source: "default",
    starts_on: null,
    until_on: null,
    returns_to: null,
    reason: null,
    note: null,
    author: null,
  };
}

function changed(
  level: CadenceCurrent["level"],
  startsOn: string,
  reason: NonNullable<CadenceCurrent["reason"]>,
  options: { until?: string; note?: string; returnsTo?: CadenceCurrent["level"] } = {},
): CadenceCurrent {
  return {
    level,
    source: "period",
    starts_on: startsOn,
    until_on: options.until ?? null,
    returns_to: options.until ? (options.returnsTo ?? "monthly") : null,
    reason,
    note: options.note ?? null,
    author: natalia,
  };
}

interface RowInput {
  id: number;
  person: { id: number; name: string };
  client: { id: number; name: string };
  job: string;
  form: ConsultantRow["contract_type"];
  start: string;
  end?: string | null;
  owner?: PersonRef;
  manager?: ClientManagerRef | null;
  cadence: CadenceCurrent;
  next?: ConsultantRow["next_contact"];
  last?: { on: string; satisfaction?: number | null; note?: string | null } | null;
  signals?: ConsultantRow["signals"];
  suggested?: ConsultantRow["suggested_level"];
  talks: [number, number];
  health?: Health;
  redeploy?: boolean;
}

const OK: Health = { level: "ok", label: "Dobrze", reasons: [] };

function health(level: Health["level"], ...reasons: string[]): Health {
  return { level, label: level === "risk" ? "Ryzyko" : level === "watch" ? "Uwaga" : "Dobrze", reasons };
}

function row(input: RowInput): ConsultantRow {
  const owner = input.owner ?? natalia;
  return {
    contract_id: input.id,
    candidate_id: input.person.id,
    candidate_name: input.person.name,
    client_id: input.client.id,
    client_name: input.client.name,
    job_title: input.job,
    contract_type: input.form,
    start_date: input.start,
    end_date: input.end ?? null,
    owner,
    is_mine: owner.id === natalia.id,
    manager: input.manager ?? null,
    cadence: input.cadence,
    next_contact: input.next ?? null,
    last_conversation: input.last
      ? {
          id: input.id * 10,
          occurred_on: input.last.on,
          satisfaction: input.last.satisfaction ?? null,
          note_excerpt: input.last.note ?? null,
          signals: [],
        }
      : null,
    signals: input.signals ?? [],
    suggested_level: input.suggested ?? null,
    conversations: { this_month: input.talks[0], next_month: input.talks[1] },
    can_change_cadence: owner.id === natalia.id,
    health: input.health ?? OK,
    redeploy_active: input.redeploy ?? false,
  };
}

function next(
  dueOn: string,
  today: string,
  kind: NonNullable<ConsultantRow["next_contact"]>["kind"] = "cadence",
): NonNullable<ConsultantRow["next_contact"]> {
  const overdueDays = Math.max(0, Math.round((Date.parse(today) - Date.parse(dueOn)) / 86_400_000));
  return {
    due_on: dueOn,
    label: kind === "pre_end" ? "Przed końcem zamówienia" : "Rozmowa według rytmu",
    overdue: overdueDays > 0,
    plan_item_id: 900,
    kind,
    overdue_days: overdueDays,
  };
}

/** „Konsultanci” (M1): rytm przy każdej osobie, sygnały i rozmowy w miesiącu. */
export function careConsultants(today: string): CareConsultants {
  const karolinaStart = shiftDay(today, -33);
  const michalStart = contractStart(today);
  const items: ConsultantRow[] = [
    row({
      id: 4502,
      person: HR_CONSULTANTS.karolina,
      client: HR_CLIENTS.telecom,
      job: "Testerka automatyzująca",
      form: "b2b",
      start: karolinaStart,
      manager: managers.qa,
      cadence: program(karolinaStart),
      next: next(shiftDay(today, -5), today),
      last: { on: shiftDay(today, -19), satisfaction: 5, note: "Dobrze, chce więcej automatyzacji testów." },
      signals: [{ kind: "overdue", days: 5 }],
      talks: [2, 2],
      health: health("watch", "rozmowa zaległa od 5 dni"),
    }),
    row({
      id: 4504,
      person: HR_CONSULTANTS.pawel,
      client: HR_CLIENTS.bank,
      job: "Java Developer",
      form: "b2b",
      start: shiftDay(today, -300),
      end: shiftDay(today, 34),
      manager: managers.pay,
      cadence: changed("biweekly", shiftDay(today, -9), "wants_change", { until: shiftDay(today, 44) }),
      next: next(shiftDay(today, 5), today),
      last: { on: shiftDay(today, -9), satisfaction: 4, note: "Rozmowa o kolejnym projekcie." },
      signals: [
        { kind: "order_end", days: 34, on: shiftDay(today, 34) },
        { kind: "wants_change" },
      ],
      talks: [2, 3],
      health: health(
        "risk",
        `chce zmiany projektu (${shiftDay(today, -9).slice(8, 10)}.${shiftDay(today, -9).slice(5, 7)})`,
        "zamówienie kończy się za 34 dni",
      ),
      redeploy: true,
    }),
    row({
      id: CARE_CONTRACT_ID,
      person: HR_CONSULTANTS.michal,
      client: HR_CLIENTS.bank,
      job: "Java Developer",
      form: "b2b",
      start: michalStart,
      manager: managers.data,
      cadence: program(michalStart),
      next: next(shiftDay(michalStart, 56), today),
      last: { on: shiftDay(michalStart, 14), note: "Trzy dni bez dostępu do VPN." },
      talks: [2, 2],
    }),
    row({
      id: BARTOSZ_CONTRACT,
      person: HR_CONSULTANTS.bartosz,
      client: HR_CLIENTS.bank,
      job: "DevOps Engineer",
      form: "uzlecenie",
      start: shiftDay(today, -400),
      manager: managers.pay,
      cadence: monthly(),
      next: next(shiftDay(today, 12), today),
      last: { on: shiftDay(today, -18), satisfaction: 3, note: null },
      signals: [{ kind: "weak_feedback", average: 2.7, on: shiftDay(today, -2) }],
      suggested: "biweekly",
      talks: [1, 1],
      health: health("risk", "ostatnia opinia menedżera 2,7 / 5"),
    }),
    row({
      id: 4506,
      person: MORE.tomasz,
      client: HR_CLIENTS.bank,
      job: "Data Engineer",
      form: "uzlecenie",
      start: shiftDay(today, -1500),
      manager: managers.data,
      cadence: changed("quarterly", shiftDay(today, -60), "stable", { note: "Stabilnie, 4 lata u klienta." }),
      next: next(shiftDay(today, 30), today),
      last: { on: shiftDay(today, -60), note: null },
      talks: [0, 1],
    }),
    row({
      id: 4507,
      person: MORE.jakub,
      client: HR_CLIENTS.telecom,
      job: "Java Developer",
      form: "b2b",
      start: shiftDay(today, -1800),
      end: shiftDay(today, 75),
      cadence: changed("milestones", shiftDay(today, -100), "person_request", { note: "Prosi o rzadki kontakt." }),
      next: next(shiftDay(today, 45), today, "pre_end"),
      last: { on: shiftDay(today, -100), note: null },
      talks: [0, 0],
      health: health("watch", "brak rozmowy od 100 dni"),
    }),
    row({
      id: 4508,
      person: MORE.olga,
      client: HR_CLIENTS.bank,
      job: "DevOps",
      form: "b2b",
      start: shiftDay(today, -500),
      manager: managers.pay,
      cadence: changed("paused", shiftDay(today, -27), "long_absence", { until: shiftDay(today, 29) }),
      last: { on: shiftDay(today, -27), note: "Zgłosiła przerwę." },
      talks: [0, 0],
    }),
    row({
      id: 4505,
      person: HR_CONSULTANTS.anna,
      client: HR_CLIENTS.insurance,
      job: "Analityczka biznesowa",
      form: "b2b",
      start: shiftDay(today, 18),
      owner: kamil,
      cadence: program(shiftDay(today, 18)),
      next: next(shiftDay(today, 25), today, "day_7"),
      talks: [0, 2],
      health: health("ok", "brak rozmów — kontrakt startuje za 18 dni"),
    }),
  ];
  const monthStart = `${today.slice(0, 7)}-01`;
  return {
    today,
    months: {
      this: { from: monthStart, to: monthStart },
      next: { from: monthStart, to: monthStart },
    },
    items,
    total: items.length,
    feedback_visible: true,
  };
}

/** Okno „Rytm kontaktu” Bartosza (M2) — po słabej opinii menedżera. */
export function bartoszCadence(today: string): ContractCadence {
  const start = shiftDay(today, -400);
  return {
    contract_id: BARTOSZ_CONTRACT,
    candidate_name: HR_CONSULTANTS.bartosz.name,
    client_name: HR_CLIENTS.bank.name,
    start_date: start,
    end_date: null,
    is_live: true,
    owner: natalia,
    manager: managers.pay,
    current: monthly(),
    history: [
      { on: start, kind: "start", level: "biweekly", reason: null, note: null, until_on: null, author: null, future: false },
      {
        on: shiftDay(start, 90),
        kind: "program_end",
        level: "monthly",
        reason: null,
        note: null,
        until_on: null,
        author: null,
        future: false,
      },
    ],
    upcoming: [12, 42, 73, 103].map((days) => ({
      due_on: shiftDay(today, days),
      kind: "cadence" as const,
      label: "Rozmowa według rytmu",
    })),
    signals: [{ kind: "weak_feedback", average: 2.7, on: shiftDay(today, -2) }],
    suggested_level: "biweekly",
    preview: null,
    can_edit: true,
  };
}

/** Podgląd „co 2 tygodnie” bez daty końca (po kliknięciu poziomu w oknie). */
export function bartoszCadencePreview(today: string): ContractCadence {
  return {
    ...bartoszCadence(today),
    preview: {
      level: "biweekly",
      until_on: null,
      returns_to: null,
      upcoming: [14, 28, 42, 56, 70].map((days) => ({
        due_on: shiftDay(today, days),
        kind: "cadence" as const,
        label: "Rozmowa według rytmu",
      })),
      owner_month: { owner: natalia, month: `${shiftDay(today, 31).slice(0, 7)}-01`, before: 9, after: 11 },
    },
  };
}

/** Rytm w zakładce „Opieka” Michała (program pierwszych 90 dni). */
export function michalCadence(today: string): ContractCadence {
  const start = contractStart(today);
  return {
    ...bartoszCadence(today),
    contract_id: CARE_CONTRACT_ID,
    candidate_name: HR_CONSULTANTS.michal.name,
    start_date: start,
    manager: managers.data,
    current: program(start),
    history: [
      { on: start, kind: "start", level: "biweekly", reason: null, note: null, until_on: null, author: null, future: false },
      {
        on: shiftDay(start, 90),
        kind: "program_end",
        level: "monthly",
        reason: null,
        note: null,
        until_on: null,
        author: null,
        future: true,
      },
    ],
    upcoming: [56, 70, 84].map((days) => ({
      due_on: shiftDay(start, days),
      kind: "cadence" as const,
      label: "Rozmowa według rytmu",
    })),
    signals: [],
    suggested_level: null,
  };
}

function assignmentRow(
  id: number,
  person: { id: number; name: string },
  client: { id: number; name: string },
  job: string,
  start: string,
  owner: PersonRef | null,
  hint: AssignmentRow["hint"],
  extra: Partial<AssignmentRow> = {},
): AssignmentRow {
  return {
    contract_id: id,
    candidate_id: person.id,
    candidate_name: person.name,
    job_title: job,
    contract_type: "b2b",
    client_id: client.id,
    client_name: client.name,
    start_date: start,
    end_date: null,
    owner,
    owner_source: owner ? (hint === "client" ? "client" : hint === "delivery_lead" ? "delivery_lead" : "contract") : null,
    explicit_owner_id: hint === "contract" ? (owner?.id ?? null) : null,
    client_default_owner: hint === "client" ? owner : null,
    hint,
    ending_soon: false,
    cadence_level: "biweekly",
    conversations_next_month: 2,
    ...extra,
  };
}

/** „Przydział” (M3): trzech opiekunów, dwie osoby bez opiekuna, próg 20 rozmów. */
export function careAssignment(today: string): CareAssignment {
  const consultants = careConsultants(today).items;
  const items: AssignmentRow[] = [
    assignmentRow(4601, MORE.marek, HR_CLIENTS.clinic, "Python Developer", shiftDay(today, 17), null, "no_default"),
    assignmentRow(4602, MORE.iga, HR_CLIENTS.clinic, "Testerka", shiftDay(today, 17), null, "no_default", {
      contract_type: "uzlecenie",
    }),
    ...consultants.map((item) =>
      assignmentRow(
        item.contract_id,
        { id: item.candidate_id ?? 0, name: item.candidate_name ?? "" },
        { id: item.client_id, name: item.client_name },
        item.job_title ?? "",
        item.start_date ?? today,
        item.owner,
        item.owner?.id === kamil.id ? "client" : "contract",
        {
          contract_type: item.contract_type,
          cadence_level: item.cadence.level,
          conversations_next_month: item.conversations.next_month,
          end_date: item.end_date,
          ending_soon: item.signals.some((signal) => signal.kind === "order_end"),
        },
      ),
    ),
  ];
  return {
    today,
    month: { from: `${shiftDay(today, 31).slice(0, 7)}-01`, to: `${shiftDay(today, 31).slice(0, 7)}-28` },
    this_month: { from: `${today.slice(0, 7)}-01`, to: `${today.slice(0, 7)}-28` },
    counts: { active: items.length, without_owner: 2, owners: 2, conversations: 21, ending: 1 },
    threshold: { monthly_conversations: 20 },
    owners: [
      {
        id: natalia.id,
        name: natalia.name,
        is_delivery_lead: false,
        consultants: 7,
        conversations: 21,
        by_level: { biweekly: 3, monthly: 1, quarterly: 1, milestones: 1, paused: 1 },
        clients: [HR_CLIENTS.bank.name, HR_CLIENTS.telecom.name],
        over_threshold: true,
        is_tcm: true,
        in_pool: true,
        planned_this_month: 11,
        done_this_month: 9,
      },
      {
        id: kamil.id,
        name: kamil.name,
        is_delivery_lead: true,
        consultants: 1,
        conversations: 2,
        by_level: { biweekly: 1 },
        clients: [HR_CLIENTS.insurance.name],
        over_threshold: false,
        is_tcm: false,
        in_pool: false,
        planned_this_month: 1,
        done_this_month: 1,
      },
      // Pula bez podopiecznych (makieta P6: „w puli · bez podopiecznych”).
      {
        id: 204,
        name: "Igor Testowy",
        is_delivery_lead: false,
        consultants: 0,
        conversations: 0,
        by_level: {},
        clients: [],
        over_threshold: false,
        is_tcm: false,
        in_pool: true,
        planned_this_month: 0,
        done_this_month: 0,
      },
    ],
    items,
    clients: [
      { id: HR_CLIENTS.bank.id, name: HR_CLIENTS.bank.name, default_owner: natalia, default_owner_active: true, consultants: 5 },
      { id: HR_CLIENTS.clinic.id, name: HR_CLIENTS.clinic.name, default_owner: null, default_owner_active: false, consultants: 2 },
      { id: HR_CLIENTS.insurance.id, name: HR_CLIENTS.insurance.name, default_owner: kamil, default_owner_active: true, consultants: 1 },
      { id: HR_CLIENTS.telecom.id, name: HR_CLIENTS.telecom.name, default_owner: null, default_owner_active: false, consultants: 2 },
    ],
    owner_choices: [natalia, kamil, adam],
    can_assign: true,
    can_edit_threshold: true,
    can_edit_defaults: true,
  };
}

/** Pula opiekunów (podwładni head back office) i podgląd „Przypisz wg obłożenia”. */
export function careAutoAssignment(today: string): CareAutoAssignment {
  const people = [
    { id: 201, name: "Beata Księgowa" },
    { id: 202, name: "Daria Przykładowa" },
    { id: 203, name: "Hanna Finansowa" },
    { id: 204, name: "Igor Testowy" },
  ];
  const [beata, daria, hanna, igor] = people;
  return {
    pool: [
      { ...beata, excluded: true, sees_care: true, eligible: false, note: null, consultants_now: null, consultants_after: null },
      { ...daria, excluded: false, sees_care: false, eligible: false, note: "nie widzi Opieki (brak sekcji albo podglądu Delivery)", consultants_now: null, consultants_after: null },
      { ...hanna, excluded: false, sees_care: true, eligible: true, note: null, consultants_now: 0, consultants_after: 1 },
      { id: natalia.id, name: natalia.name, excluded: false, sees_care: true, eligible: true, note: null, consultants_now: 7, consultants_after: 7 },
      { ...igor, excluded: false, sees_care: true, eligible: true, note: null, consultants_now: 0, consultants_after: 1 },
    ],
    config: {
      manager: { id: kamil.id, name: kamil.name },
      manager_from_division: false,
      excluded_user_ids: [beata.id],
      auto_new_contracts: true,
      saved: true,
    },
    manager_choices: [kamil, adam],
    items: [
      { contract_id: 4601, candidate_name: MORE.marek.name, client_name: HR_CLIENTS.clinic.name, start_date: shiftDay(today, 17), owner: hanna },
      { contract_id: 4602, candidate_name: MORE.iga.name, client_name: HR_CLIENTS.clinic.name, start_date: shiftDay(today, 17), owner: igor },
    ],
    unassigned: [],
    counts: { targets: 2, assigned: 2, unassigned: 0, eligible: 3 },
  };
}
