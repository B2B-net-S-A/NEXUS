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
import { CARE_CONTRACT_ID, careTechCard, contractCare, contractStart } from "./fixtures";
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
    // Makieta P2: „Przekaż do front office — pasuje do Java Developer (Kredyty) 84 i ZAP-112 Backend 76”.
    return {
      kind: "front_office",
      label: "Przekaż do front office",
      detail: "chce zmiany projektu · kończy projekt w 60 dni",
      matches: [
        { job_id: 6201, title: "Java Developer (Kredyty)", client_name: HR_CLIENTS.telecom.name, score: 84 },
        { job_id: 6202, title: "ZAP-112 Backend", client_name: HR_CLIENTS.insurance.name, score: 76 },
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
  // Makieta S3: sprawa z maila „Czeka” z „odezwać się”, negocjacje bez treści,
  // zamknięte wejście jedną linią z checklistą.
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
      source: "mail",
      content_hidden: false,
      assignee_hidden: false,
      closed_on: null,
      checklist_done: 1,
      checklist_total: 3,
    },
    {
      id: 952,
      title: "Rozmowa o przedłużeniu",
      area: "negotiation",
      area_label: "Negocjacje",
      status: "waiting",
      status_label: "Czeka na kogoś",
      due_on: shiftDay(today, 14),
      follow_up_on: shiftDay(today, 4),
      assignee_name: natalia.name,
      source: "manual",
      content_hidden: true,
      assignee_hidden: false,
      closed_on: null,
      checklist_done: 0,
      checklist_total: 0,
    },
    {
      id: 940,
      title: "Wejście konsultanta",
      area: "onboarding",
      area_label: "Onboarding",
      status: "closed",
      status_label: "Zamknięta",
      due_on: null,
      follow_up_on: null,
      assignee_name: "Zofia Recepcyjna",
      source: "contract",
      content_hidden: false,
      assignee_hidden: false,
      closed_on: shiftDay(contractStart(today), 9),
      checklist_done: 4,
      checklist_total: 4,
    },
  ];
}

/** Makieta P2: Paweł — „co wiemy” z rozmowy 08.10, popyt i cytat w jednej linii. */
function pawelProject(today: string): ConsultantCardData["known_project"] {
  return {
    source: { on: shiftDay(today, -14), author_name: natalia.name, kind: "conversation" },
    area: { id: 301, name: "Płatności" },
    manager: { contact_id: 8803, name: "M. Rogalski-Przykładowy", position: "Kierownik Płatności" },
    team_size: "9",
    team_externals: 4,
    technologies: [
      { skill_id: 801, name: "Java 17" },
      { skill_id: 802, name: "Spring Boot" },
      { skill_id: 803, name: "Kafka" },
      { skill_id: 806, name: "OpenShift" },
    ],
    vendors: ["Dostawca A", "Dostawca B"],
    hiring: { roles: ["Java", "QA"], source: "widzial" },
    project_end_month: null,
    quote: "Do końca roku zespół ma się podwoić.",
  };
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
      satisfaction:
        michal || row.contract_id === 4504
        ? { value: 4, previous: 5 }
        : last?.satisfaction
          ? { value: last.satisfaction, previous: null }
          : null,
      manager_feedback:
        row.contract_id === BARTOSZ_CONTRACT
          ? { avg: 2.7, extension: "unsure", on: shiftDay(today, -2) }
          : michal
            ? { avg: 4.3, extension: "likely", on: shiftDay(today, -20) }
            : row.contract_id === 4504
              ? { avg: 4, extension: "yes", on: shiftDay(today, -105) }
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
        : row.contract_id === 4504
          ? pawelProject(today)
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

/** „za 2 dni”, „jutro”, „dziś”, „zaległy 3 dni” — dopisek punktu planu jak z serwera. */
function inDays(today: string, on: string): string {
  const days = daysBetween(today, on);
  if (days < 0) return `zaległy ${-days === 1 ? "1 dzień" : `${-days} dni`}`;
  if (days === 0) return "dziś";
  if (days === 1) return "jutro";
  return `za ${days} dni`;
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
  // Tytuły jak z serwera (`care/timeline.py`, makiety P2 i S3).
  const plan = (on: string, label: string) =>
    event("plan", on, `Plan: ${label.charAt(0).toLowerCase()}${label.slice(1)}`, inDays(today, on), null, today);
  const events: TimelineEvent[] = michal
    ? [
        event("recruitment", shiftDay(contractStart(today), -30), "Rekrutacja „Java Developer”", "front office · prowadzi Kamil T.", "/jobs/5101"),
        event("start", contractStart(today), "Start kontraktu", "Java Developer"),
        event("case_opened", contractStart(today), "Sprawa otwarta: Wejście konsultanta", "Zofia Recepcyjna", "/people/cases/940"),
        event("conversation", shiftDay(contractStart(today), 7), "Rozmowa · dzień 7 · 5/5", "„Onboarding u klienta, sprzęt odebrany.”"),
        event("case_closed", shiftDay(contractStart(today), 9), "Sprawa zamknięta: Wejście konsultanta 4/4", null, "/people/cases/940"),
        event(
          "conversation",
          shiftDay(contractStart(today), 14),
          "Rozmowa · telefon · 4/5",
          "„Trzy dni bez dostępu do VPN, zgłoszone do Delivery Leada.”",
        ),
        event(
          "case_opened",
          shiftDay(contractStart(today), 14),
          "Sprawa z maila: Dostęp do VPN klienta",
          "powiązana po e-mailu z kontraktu",
          "/people/cases/951",
        ),
        event("tech_card", careTechCard(today).interview_on, "Karta technologiczna", "Data · technologie: 6"),
        event("feedback", shiftDay(today, -20), "Opinia menedżera · 4,3 · przedłużenie: raczej tak", "Piotr Menedżerski"),
        event("case_opened", shiftDay(today, -6), "Sprawa otwarta: Rozmowa o przedłużeniu", natalia.name, "/people/cases/952"),
        event("order_start", contractStart(today), "Zamówienie „ZAM/2026/118”", "aktywne"),
        plan(shiftDay(contractStart(today), 56), "Rozmowa według rytmu"),
      ]
    : [
        event("start", start, "Start kontraktu", row.job_title),
        ...(row.last_conversation
          ? [
              event(
                "conversation" as const,
                row.last_conversation.occurred_on,
                [
                  "Rozmowa · telefon",
                  row.last_conversation.satisfaction ? `${row.last_conversation.satisfaction}/5` : null,
                  row.redeploy_active ? "chce zmiany projektu" : null,
                ]
                  .filter(Boolean)
                  .join(" · "),
                row.last_conversation.note_excerpt ? `„${row.last_conversation.note_excerpt}”` : null,
              ),
            ]
          : []),
        ...(row.end_date ? [event("order_end" as const, row.end_date, "Koniec zamówienia", null, null, today)] : []),
        ...(row.next_contact ? [plan(row.next_contact.due_on, row.next_contact.label)] : []),
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
              detail: "Komu podlega Piotr Menedżerski (Head of Data)?",
              contact_id: 8202,
            },
            {
              key: "category:0",
              kind: "category_stale",
              subject: "CI/CD i chmura",
              detail: "brak źródła od 18 miesięcy. Czego używają?",
            },
          ]
        : [],
  };
}

/** „Opieka · Klienci”: portfel z wiedzą, zdrowiem, popytem i kończącymi. */
export function careClients(today: string, scope: "mine" | "all"): CareClients {
  // Stany z makiety P4: drzewo pełne, pewne propozycje, bez propozycji
  // automatu; mapa świeża / stara / bez źródeł; prośba czeka od…
  const rows: CareClients["rows"] = [
    {
      client_id: HR_CLIENTS.bank.id,
      name: HR_CLIENTS.bank.name,
      delivery_leads: [HR_CAST.kamil.name],
      default_owner_name: natalia.name,
      consultants: 6,
      health: { ok: 4, watch: 1, risk: 1 },
      managers_known: 3,
      structure_open: 0,
      proposals_certain: 0,
      tree_complete: true,
      last_feedback_on: shiftDay(today, -93),
      feedback_pending: 1,
      feedback_pending_since: shiftDay(today, -3),
      map: { last_source_on: careTechCard(today).interview_on, gaps: 2 },
      demand: { skills: ["Java", "QA"], open_jobs: 3, hiring_signal: false },
      ending_60: [
        { contract_id: 4504, name: HR_CONSULTANTS.pawel.name, end_on: shiftDay(today, 31) },
        { contract_id: 4503, name: HR_CONSULTANTS.bartosz.name, end_on: shiftDay(today, 50) },
      ],
    },
    {
      client_id: HR_CLIENTS.telecom.id,
      name: HR_CLIENTS.telecom.name,
      delivery_leads: [HR_CAST.kamil.name],
      default_owner_name: natalia.name,
      consultants: 9,
      health: { ok: 7, watch: 2, risk: 0 },
      managers_known: 1,
      structure_open: 6,
      proposals_certain: 2,
      tree_complete: false,
      last_feedback_on: null,
      feedback_pending: 1,
      feedback_pending_since: shiftDay(today, -6),
      map: { last_source_on: shiftDay(today, -430), gaps: 3 },
      demand: { skills: [], open_jobs: 1, hiring_signal: false },
      ending_60: [{ contract_id: 4502, name: HR_CONSULTANTS.karolina.name, end_on: shiftDay(today, 24) }],
    },
  ];
  if (scope === "all") {
    rows.push(
      {
        client_id: HR_CLIENTS.clinic.id,
        name: HR_CLIENTS.clinic.name,
        delivery_leads: [],
        default_owner_name: null,
        consultants: 2,
        health: { ok: 2, watch: 0, risk: 0 },
        managers_known: 0,
        structure_open: 2,
        proposals_certain: 0,
        tree_complete: false,
        last_feedback_on: null,
        feedback_pending: 0,
        feedback_pending_since: null,
        map: { last_source_on: null, gaps: 4 },
        demand: { skills: ["Python"], open_jobs: 1, hiring_signal: false },
        ending_60: [],
      },
      {
        client_id: HR_CLIENTS.insurance.id,
        name: HR_CLIENTS.insurance.name,
        delivery_leads: [HR_CAST.kamil.name],
        default_owner_name: null,
        consultants: 1,
        health: { ok: 1, watch: 0, risk: 0 },
        managers_known: 1,
        structure_open: 0,
        proposals_certain: 0,
        tree_complete: true,
        last_feedback_on: shiftDay(today, -50),
        feedback_pending: 0,
        feedback_pending_since: null,
        map: { last_source_on: shiftDay(today, -22), gaps: 0 },
        demand: { skills: [".NET"], open_jobs: 0, hiring_signal: true },
        ending_60: [],
      },
    );
  }
  return { rows, today };
}
