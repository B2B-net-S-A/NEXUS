/**
 * Dane harnessu `/preview/hr-onboarding` dla etapu 3 (makiety M4 i M6):
 * zakładka „Wejście” kontraktu konsultanta i ścieżki wejścia i odejścia.
 *
 * Konsultant Michał zaczyna u fikcyjnego klienta pierwszego dnia roboczego
 * przyszłego miesiąca; terminy w dniach roboczych od startu, jak liczy serwer.
 * Opiekunka — Natalia (TCM). Mail powitalny wyłączony (przełącznik
 * w ustawieniach jest domyślnie wyłączony — pierwszą wysyłkę uruchamia Artur).
 */

import type { WelcomeMailState } from "@/lib/api/client-onboarding";
import type {
  ContractEntryView,
  LifecycleTask,
  LifecycleTemplate,
  TemplateItem,
} from "@/lib/api/hr-lifecycle";

import { HR_CAST, HR_CONSULTANTS } from "../hr-fixtures";
import { addWorkDays } from "../hr-person/fixtures";
import type { OnboardingScene } from "./fixtures";

const { adam, natalia } = HR_CAST;
const { michal } = HR_CONSULTANTS;

export const ENTRY_CONTRACT_ID = 9301;
const CLIENT = "Bank Fikcyjny";

interface Spec {
  title: string;
  who: "care_owner" | "delivery_lead" | "reception" | "administration";
  offset: number;
  source: LifecycleTask["source"];
  label?: string;
  description?: string;
  key?: string;
  done?: boolean;
  file?: boolean;
  mirror?: boolean;
  category: LifecycleTask["category"];
}

const SPECS: Spec[] = [
  { title: "Prośba o konto i VPN u klienta", who: "delivery_lead", offset: -10, source: "client", label: CLIENT, category: "accounts", done: true },
  { title: "Umowa podpisana, dane do faktur", who: "administration", offset: -7, source: "form", label: "B2B", category: "documents", file: true, description: "Plik umowy w kontrakcie.", done: true },
  { title: "Przygotuj zestaw sprzętu", who: "reception", offset: -7, source: "path", key: "equipment_kit", category: "equipment", description: "Od nas: laptop 14 cali, słuchawki.", mirror: true },
  { title: "Mail powitalny do konsultanta", who: "care_owner", offset: -3, source: "path", key: "welcome_mail", category: "other", description: "Podgląd przed wysłaniem — wysyła opiekun." },
  { title: "Zaświadczenie o niekaralności", who: "care_owner", offset: -1, source: "client", label: CLIENT, category: "documents", file: true, description: "Konsultant przyśle, odhacza opiekun." },
  { title: "Dokumenty klienta: NDA", who: "care_owner", offset: 0, source: "client", label: CLIENT, category: "documents" },
  { title: "Wydanie sprzętu i protokół", who: "reception", offset: 0, source: "path", key: "equipment_issue", category: "equipment", description: "Wzór protokołu z pakietu klienta." },
  { title: "Rozmowa po pierwszym dniu", who: "care_owner", offset: 1, source: "path", category: "meeting" },
  { title: "Rozmowa po dwóch tygodniach", who: "care_owner", offset: 10, source: "path", category: "meeting", description: "Sprzęt, dostępy, zespół." },
  { title: "Pierwsza opinia menedżera u klienta", who: "delivery_lead", offset: 21, source: "path", category: "meeting" },
];

function entryTask(spec: Spec, index: number, scene: OnboardingScene): LifecycleTask {
  const person = spec.who === "care_owner" ? natalia : spec.who === "delivery_lead" ? adam : null;
  return {
    id: 9400 + index,
    title: spec.title,
    category: spec.category,
    assignee_kind: spec.who,
    assignee_user_id: person?.id ?? null,
    assignee_name: person?.name ?? null,
    due_date: addWorkDays(scene.start, spec.offset),
    status: spec.done ? "done" : "open",
    overdue: false,
    done_at: spec.done ? `${scene.today}T09:00:00Z` : null,
    done_by_name: spec.done ? natalia.name : null,
    note: null,
    description: spec.description ?? null,
    required: true,
    requires_file: Boolean(spec.file),
    key: spec.key ?? null,
    source: spec.source,
    source_label: spec.label ?? null,
    from_template: spec.source === "path" || spec.source === "form",
    mirror: spec.mirror
      ? { module: "equipment", task_id: 77, status: "open", note: "Odhacza recepcja w Sprzęcie." }
      : null,
    // Opiekunka prowadzi całe wejście; zestaw i umowę odhacza kto inny.
    can_toggle: !spec.mirror && spec.who !== "administration" && spec.who !== "reception",
  };
}

/** `GET /api/hr/lifecycle/contracts/{id}/entry` — opiekunka Natalia. */
export function consultantEntry(scene: OnboardingScene): ContractEntryView {
  const tasks = SPECS.map((spec, index) => entryTask(spec, index, scene));
  const done = tasks.filter((task) => task.status !== "open").length;
  return {
    contract_id: ENTRY_CONTRACT_ID,
    module_on: true,
    start_date: scene.start,
    case: {
      id: 9300,
      kind: "onboarding",
      status: "active",
      user_id: null,
      person_name: michal.name,
      pending_email: null,
      template_id: 52,
      template_name: "Konsultant u klienta",
      audience: "consultant",
      contract_id: ENTRY_CONTRACT_ID,
      template_version: 4,
      template_current_version: 4,
      start_date: scene.start,
      last_working_day: null,
      deactivate_on: null,
      handover_at: null,
      manager_user_id: null,
      manager_name: null,
      owner_name: natalia.name,
      started_at: `${scene.today}T08:00:00Z`,
      handover_executed_at: null,
      account_closed_at: null,
      account_close_result: null,
      completed_at: null,
      cancelled_at: null,
      scope: "manager",
      can_manage: false,
      can_cancel: false,
      can_add_task: true,
      tasks,
      progress: { done, total: tasks.length, overdue: 0 },
    },
    composition: {
      client_id: 8801,
      client_name: CLIENT,
      employment_type: "b2b",
      employment_label: "B2B",
      equipment: "ours",
      care_owner: { id: natalia.id, name: natalia.name, source: "contract" },
      delivery_lead: { id: adam.id, name: adam.name },
      client_manager: "Piotr Klientowy",
    },
    missing_reason: null,
    can_create: false,
    can_add_task: true,
    legacy_items: 0,
  };
}

/** Karta maila powitalnego (G2) — przełącznik wyłączony, bez wysyłki. */
export function welcomeMailOff(scene: OnboardingScene): WelcomeMailState {
  return {
    contract_id: ENTRY_CONTRACT_ID,
    enabled: false,
    mailbox_ready: true,
    transport_ready: true,
    can_toggle: false,
    is_sender: true,
    can_send: false,
    sent: null,
    draft: {
      recipient_email: michal.email,
      recipient_name: michal.name,
      subject: `Start w ${CLIENT} ${scene.start}`,
      body: `Cześć Michał, zaczynasz w ${CLIENT} ${scene.start}. Jestem Twoją opiekunką. Natalia`,
    },
    issues: [],
  };
}

function pathItem(item: TemplateItem, id: number): TemplateItem {
  return {
    description: null,
    required: true,
    requires_file: false,
    conditions: {},
    key: null,
    added_in_version: 1,
    ...item,
    id,
  };
}

/** Ścieżki (M4) oczami head back office: konsultanta zmienia, zespołu nie. */
export const PATH_TEMPLATES: LifecycleTemplate[] = [
  {
    id: 51,
    kind: "onboarding",
    audience: "team",
    version: 3,
    name: "Zespół wewnętrzny",
    is_active: true,
    employment_type: null,
    department: null,
    can_edit: false,
    live_cases_behind: 0,
    items: [
      pathItem({ title: "Konto Microsoft 365", category: "accounts", assignee_kind: "it", due_offset_days: -2 }, 511),
      pathItem({ title: "Wydanie zestawu biurowego", category: "equipment", assignee_kind: "reception", due_offset_days: -2 }, 512),
      pathItem({ title: "Rozmowa w pierwszym dniu", category: "meeting", assignee_kind: "manager", due_offset_days: 0 }, 513),
    ],
  },
  {
    id: 52,
    kind: "onboarding",
    audience: "consultant",
    version: 4,
    name: "Konsultant u klienta",
    is_active: true,
    employment_type: null,
    department: null,
    can_edit: true,
    live_cases_behind: 3,
    items: SPECS.filter((spec) => spec.source !== "client").map((spec, index) =>
      pathItem(
        {
          title: spec.title,
          category: spec.category,
          assignee_kind: spec.who,
          due_offset_days: spec.offset,
          description: spec.description ?? null,
          requires_file: Boolean(spec.file),
          key: spec.key ?? null,
          conditions:
            spec.source === "form"
              ? { employment_types: ["b2b"] }
              : spec.who === "reception"
                ? { equipment: "ours" }
                : {},
        },
        520 + index,
      ),
    ),
  },
  {
    id: 53,
    kind: "offboarding",
    audience: "consultant",
    version: 1,
    name: "Koniec projektu konsultanta",
    is_active: true,
    employment_type: null,
    department: null,
    can_edit: true,
    live_cases_behind: 0,
    items: [
      pathItem({ title: "Rozmowa przed końcem projektu", category: "meeting", assignee_kind: "care_owner", due_offset_days: -10 }, 531),
      pathItem({ title: "Zwrot sprzętu według pakietu klienta", category: "equipment", assignee_kind: "reception", due_offset_days: 0, conditions: { equipment: "ours" } }, 532),
    ],
  },
];
