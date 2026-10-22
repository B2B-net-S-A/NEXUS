/**
 * Dane harnessu dla karty konsultanta, okna „Rozmowa” i zakładki „Klienci”
 * (przebudowa opieki 22.10.2026) — wyłącznie fikcyjne, daty od „dziś”
 * przeglądarki. Karty budujemy z wierszy „Konsultanci” (ta sama obsada,
 * zdrowie i rytm), Michał ma pełną kartę z wiedzą o projekcie i sprawami.
 */

import type {
  CardCase,
  CardPlanItem,
  CareClients,
  ClientStateView,
  ConsultantCardData,
  ConsultantRow,
  ContractTimeline,
  NextStep,
  TimelineEvent,
} from "@/lib/api/care";

import { HR_CAST, HR_CLIENTS, HR_CONSULTANTS, shiftDay } from "../hr-fixtures";
import { CARE_CLIENT, CARE_CONTRACT_ID, careTechCard, contractCare, contractStart } from "./fixtures";
import { BARTOSZ_CONTRACT, careConsultants } from "./rhythm-fixtures";

const natalia = HR_CAST.natalia;

function daysBetween(from: string, to: string): number {
  return Math.round((Date.parse(to) - Date.parse(from)) / 86_400_000);
}

function dm(iso: string): string {
  return `${iso.slice(8, 10)}.${iso.slice(5, 7)}`;
}

function planFromRow(row: ConsultantRow): CardPlanItem[] {
  const next = row.next_contact;
  if (!next) return [];
  return [
    {
      id: next.plan_item_id ?? row.contract_id * 10,
      kind: next.kind === "follow_up" ? "cadence" : next.kind,
      label: next.label,
      due_on: next.due_on,
      status: "open",
      skip_reason: null,
    },
  ];
}

function nextStepFor(row: ConsultantRow, today: string): NextStep {
  if (row.contract_id === 4504) {
    return {
      kind: "front_office",
      label: "Przekaż do front office",
      detail: "Chce zmiany projektu, zamówienie kończy się za 34 dni.",
      matches: [
        { job_id: 6201, title: "Senior Java Developer", client_name: HR_CLIENTS.telecom.name, score: 82 },
        { job_id: 6202, title: "Java Developer (płatności)", client_name: HR_CLIENTS.insurance.name, score: 74 },
      ],
    };
  }
  if (row.contract_id === BARTOSZ_CONTRACT) {
    return {
      kind: "raise_cadence",
      label: "Podnieś rytm do „co 2 tygodnie”",
      detail: "Ostatnia opinia menedżera 2,7 / 5 — rytm co miesiąc to za rzadko.",
    };
  }
  const next = row.next_contact;
  if (next?.overdue) {
    return {
      kind: "conversation",
      label: "Zaległa rozmowa",
      detail: `${next.label} · ${next.overdue_days} dni po terminie (${dm(next.due_on)}).`,
    };
  }
  if (next && daysBetween(today, next.due_on) <= 7) {
    return { kind: "conversation", label: "Rozmowa w tym tygodniu", detail: `${next.label} · ${dm(next.due_on)}.` };
  }
  return {
    kind: null,
    label: "Nic pilnego",
    detail: next ? `Najbliższa rozmowa ${dm(next.due_on)}.` : null,
  };
}

function michalCases(today: string): CardCase[] {
  return [
    {
      id: 951,
      title: "Dostęp do VPN klienta",
      area: "administration",
      area_label: "Administracja",
      status: "in_progress",
      status_label: "W toku",
      due_on: shiftDay(today, 3),
      follow_up_on: null,
      assignee_name: "Zofia Recepcyjna",
      source: "manual",
      content_hidden: false,
    },
    {
      id: 952,
      title: "Rozmowa o przedłużeniu",
      area: "negotiation",
      area_label: "Negocjacje",
      status: "waiting",
      status_label: "Czeka na kogoś",
      due_on: shiftDay(today, 14),
      follow_up_on: null,
      assignee_name: HR_CAST.kamil.name,
      source: "manual",
      content_hidden: true,
    },
    {
      id: 940,
      title: "Wejście konsultanta: Michał Konsultantowy",
      area: "onboarding",
      area_label: "Onboarding",
      status: "closed",
      status_label: "Zamknięta",
      due_on: null,
      follow_up_on: null,
      assignee_name: "Zofia Recepcyjna",
      source: "contract",
      content_hidden: false,
    },
  ];
}

function cardFromRow(row: ConsultantRow, today: string): ConsultantCardData {
  const last = row.last_conversation;
  const michal = row.contract_id === CARE_CONTRACT_ID;
  const care = michal ? contractCare(today) : null;
  const tech = michal ? careTechCard(today) : null;
  return {
    contract_id: row.contract_id,
    candidate_id: row.candidate_id,
    candidate_name: row.candidate_name,
    client_id: row.client_id,
    client_name: row.client_name,
    role: row.job_title,
    form: row.contract_type,
    start_on: row.start_date,
    end_on: row.end_date,
    owner: { user_id: row.owner?.id ?? null, name: row.owner?.name ?? null, source: row.owner ? "contract" : null },
    cadence: { level: row.cadence.level, label: cadenceText(row), until_on: row.cadence.until_on },
    health: row.health ?? null,
    kpis: {
      last_contact: last ? { on: last.occurred_on, days_ago: daysBetween(last.occurred_on, today) } : null,
      satisfaction: michal
        ? { value: 4, previous: 5 }
        : last?.satisfaction
          ? { value: last.satisfaction, previous: null }
          : null,
      manager_feedback:
        row.contract_id === BARTOSZ_CONTRACT
          ? { avg: 2.7, extension: "unsure", on: shiftDay(today, -2) }
          : michal
            ? { avg: 4.3, extension: "likely", on: shiftDay(today, -20) }
            : null,
      order_end: row.end_date ? { on: row.end_date, days: daysBetween(today, row.end_date) } : null,
    },
    next_step: nextStepFor(row, today),
    known_project:
      michal && tech
        ? {
            source: { on: tech.interview_on, author_name: natalia.name, kind: "tech_card" },
            area: { id: 303, name: "Data" },
            manager: { contact_id: 8202, name: "Piotr Menedżerski", position: "Head of Data" },
            team_size: "9",
            team_externals: 4,
            technologies: tech.skills.map((skill) => ({ skill_id: skill.id, name: skill.name })),
            vendors: tech.vendors.map((vendor) => vendor.name),
            hiring: { roles: tech.hiring_roles, source: tech.hiring_source },
            project_end_month: tech.project_end_on?.slice(0, 7) ?? null,
            quote: tech.memorable_quote,
          }
        : row.contract_id === 4502
          ? {
              source: { on: shiftDay(today, -19), author_name: natalia.name, kind: "conversation" },
              area: { id: 311, name: "QA" },
              manager: { contact_id: 8801, name: "Katarzyna Kierownicza", position: "QA Lead" },
              team_size: "6",
              team_externals: 2,
              technologies: [
                { skill_id: 821, name: "Playwright" },
                { skill_id: 822, name: "TypeScript" },
              ],
              vendors: [],
              hiring: null,
              project_end_month: null,
              quote: null,
            }
          : null,
    cases: michal ? michalCases(today) : [],
    plan: care
      ? care.plan.map((item) => ({
          id: item.id,
          kind: item.kind,
          label: item.label,
          due_on: item.due_on,
          status: item.status,
          skip_reason: item.skip_reason ?? null,
        }))
      : planFromRow(row),
    can_edit: row.owner?.id === natalia.id,
    can_change_owner: row.owner?.id === natalia.id,
    can_see_feedback: true,
  };
}

function cadenceText(row: ConsultantRow): string {
  const labels: Record<ConsultantRow["cadence"]["level"], string> = {
    biweekly: "co 2 tygodnie",
    monthly: "co miesiąc",
    quarterly: "co kwartał",
    milestones: "tylko kamienie",
    paused: "wstrzymany",
  };
  return labels[row.cadence.level];
}

/** Karty wszystkich osób z „Konsultantów” (klucz zapytania = id kontraktu). */
export function consultantCards(today: string): ConsultantCardData[] {
  return careConsultants(today).items.map((row) => cardFromRow(row, today));
}

function event(
  kind: TimelineEvent["kind"],
  on: string,
  title: string,
  detail: string | null = null,
  link: string | null = null,
  today = "",
): TimelineEvent {
  return { kind, on, title, detail, link, future: today !== "" && on > today };
}

/** Historia karty: start, rozmowy, sprawy, opinie, zamówienia, plan. */
export function cardTimeline(today: string, row: ConsultantRow): ContractTimeline {
  const start = row.start_date ?? shiftDay(today, -200);
  const michal = row.contract_id === CARE_CONTRACT_ID;
  const events: TimelineEvent[] = michal
    ? [
        event("recruitment", shiftDay(contractStart(today), -30), "Rekrutacja „Java Developer”", null, "/jobs/5101"),
        event("start", contractStart(today), "Start u klienta", CARE_CLIENT.name),
        event("case_opened", contractStart(today), "Sprawa: Wejście konsultanta", "Onboarding"),
        event("conversation", shiftDay(contractStart(today), 7), "Rozmowa · Telefon", "Onboarding u klienta, sprzęt odebrany."),
        event("case_closed", shiftDay(contractStart(today), 9), "Sprawa zamknięta: Wejście konsultanta", "Onboarding"),
        event(
          "conversation",
          shiftDay(contractStart(today), 14),
          "Rozmowa · Telefon",
          "Trzy dni bez dostępu do VPN, zgłoszone do Delivery Leada.",
        ),
        event("case_opened", shiftDay(contractStart(today), 14), "Sprawa: Dostęp do VPN klienta", "Administracja"),
        event("tech_card", careTechCard(today).interview_on, "Karta technologiczna · zadowolenie 4/5", "Java 17, Spring Boot, Kafka…"),
        event("feedback", shiftDay(today, -20), "Opinia: Piotr Menedżerski", "średnio 4,3 / 5 · przedłużenie: raczej tak"),
        event("case_opened", shiftDay(today, -6), "Sprawa: Rozmowa o przedłużeniu", "Negocjacje"),
        event("order_start", contractStart(today), "Zamówienie ZAM/2026/118", "do końca kwartału"),
        event("plan", shiftDay(contractStart(today), 56), "Rozmowa według rytmu", null, null, today),
      ]
    : [
        event("start", start, "Start u klienta", row.client_name),
        ...(row.last_conversation
          ? [
              event(
                "conversation" as const,
                row.last_conversation.occurred_on,
                "Rozmowa · Telefon",
                row.last_conversation.note_excerpt,
              ),
            ]
          : []),
        ...(row.end_date ? [event("order_end" as const, row.end_date, "Koniec zamówienia", null, null, today)] : []),
        ...(row.next_contact
          ? [event("plan" as const, row.next_contact.due_on, row.next_contact.label, null, null, today)]
          : []),
      ];
  return {
    contract: {
      id: row.contract_id,
      candidate_id: row.candidate_id,
      candidate_name: row.candidate_name,
      client_id: row.client_id,
      client_name: row.client_name,
      job_id: michal ? 5101 : null,
      job_title: row.job_title,
      status: "active",
      is_live: true,
      start_date: row.start_date,
      end_date: row.end_date,
    },
    owner: row.owner,
    manager: row.manager,
    signals: row.redeploy_active ? ["wants_change"] : [],
    front_office_reasons: row.contract_id === 4504 ? ["project_end", "wants_change"] : [],
    events,
    feedback_visible: true,
    can_edit: row.owner?.id === natalia.id,
  };
}

/** Prawa kolumna okna „Rozmowa”: ostatni stan i pytania z mapy klienta. */
export function clientStateFor(today: string, contractId: number): ClientStateView {
  const card = consultantCards(today).find((item) => item.contract_id === contractId);
  const known = card?.known_project ?? null;
  const state: ClientStateView["state"] = known
    ? {
        area: known.area,
        manager: known.manager,
        team_size: known.team_size,
        team_externals: known.team_externals,
        technologies: known.technologies,
        vendors: known.vendors,
        hiring: known.hiring,
        project_end_month: known.project_end_month,
        quote: known.quote,
      }
    : null;
  return {
    state,
    source: known?.source ?? null,
    questions:
      contractId === CARE_CONTRACT_ID
        ? [
            {
              key: "reports_to:8202",
              kind: "reports_to",
              subject: "Piotr Menedżerski",
              detail: "Head of Data · menedżer Michała",
              contact_id: 8202,
            },
            {
              key: "area:303",
              kind: "area_without_source",
              subject: "Data",
              detail: "ostatnie źródło sprzed 18 miesięcy",
              area_id: 303,
            },
            {
              key: "single:803",
              kind: "single_source",
              subject: "Kafka",
              detail: "tylko z jednej karty technologicznej",
            },
          ]
        : [],
  };
}

/** „Opieka · Klienci”: portfel z wiedzą, zdrowiem, popytem i kończącymi. */
export function careClients(today: string, scope: "mine" | "all"): CareClients {
  const rows: CareClients["rows"] = [
    {
      client_id: HR_CLIENTS.bank.id,
      name: HR_CLIENTS.bank.name,
      delivery_leads: [HR_CAST.kamil.name],
      default_owner_name: natalia.name,
      consultants: 5,
      health: { ok: 3, watch: 0, risk: 2 },
      managers_known: 3,
      structure_open: 1,
      last_feedback_on: shiftDay(today, -2),
      feedback_pending: 1,
      map: { last_source_on: careTechCard(today).interview_on, gaps: 3 },
      demand: { skills: ["Java", "Kafka", "QA"], open_jobs: 2, hiring_signal: true },
      ending_60: [{ contract_id: 4504, name: HR_CONSULTANTS.pawel.name, end_on: shiftDay(today, 34) }],
    },
    {
      client_id: HR_CLIENTS.telecom.id,
      name: HR_CLIENTS.telecom.name,
      delivery_leads: [HR_CAST.adam.name],
      default_owner_name: null,
      consultants: 2,
      health: { ok: 0, watch: 2, risk: 0 },
      managers_known: 1,
      structure_open: 1,
      last_feedback_on: null,
      feedback_pending: 1,
      map: { last_source_on: shiftDay(today, -19), gaps: null },
      demand: { skills: [], open_jobs: 1, hiring_signal: false },
      ending_60: [],
    },
  ];
  if (scope === "all") {
    rows.push(
      {
        client_id: HR_CLIENTS.insurance.id,
        name: HR_CLIENTS.insurance.name,
        delivery_leads: [HR_CAST.kamil.name],
        default_owner_name: HR_CAST.kamil.name,
        consultants: 1,
        health: { ok: 1, watch: 0, risk: 0 },
        managers_known: 0,
        structure_open: 0,
        last_feedback_on: null,
        feedback_pending: 0,
        map: null,
        demand: { skills: [], open_jobs: 0, hiring_signal: false },
        ending_60: [],
      },
      {
        client_id: HR_CLIENTS.clinic.id,
        name: HR_CLIENTS.clinic.name,
        delivery_leads: [HR_CAST.adam.name],
        default_owner_name: null,
        consultants: 3,
        health: { ok: 3, watch: 0, risk: 0 },
        managers_known: 2,
        structure_open: 0,
        last_feedback_on: shiftDay(today, -40),
        feedback_pending: 0,
        map: { last_source_on: shiftDay(today, -90), gaps: 0 },
        demand: { skills: ["Python"], open_jobs: 0, hiring_signal: false },
        ending_60: [],
      },
    );
  }
  return { rows };
}
