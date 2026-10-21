"use client";

/**
 * Harness wizualny okienka „Rozmowy” z górnego paska — publiczny, ZERO zapytań.
 *
 * Renderuje prezentacyjne części (`InterviewsTopbarButton`, `InterviewsPanel`)
 * na danych fikcyjnych przepuszczonych przez prawdziwe `buildInterviewWindow`.
 * Stany obok siebie, żeby awaria nie dała się pomylić z brakiem spraw.
 */

import {
  InterviewsPanel,
  InterviewsTopbarButton,
  type InterviewsPanelProps,
} from "@/components/v2/shell/InterviewNotificationsDropdown";
import type { NotificationResponse } from "@/lib/api";
import {
  TODO_ACTIONS,
  type AgendaEntry,
  type CycleItem,
  type CycleOverview,
  type PairInfo,
  type TodoEntry,
} from "@/lib/interview-cycle";
import { buildInterviewWindow, type InterviewWindowRow } from "@/lib/interview-window";

const NOW = new Date();
const at = (minutes: number) => new Date(NOW.getTime() + minutes * 60_000).toISOString();

function pair(id: number, name: string, client: string, title: string): PairInfo {
  return {
    candidate_id: id,
    candidate_name: name,
    candidate_email: null,
    job_id: 100 + id,
    job_title: title,
    client_id: 500 + id,
    client_name: client,
  };
}

const ANNA = pair(1, "Anna Przykładowa", "Bank Przykładowy", "Java Developer");
const BARTEK = pair(2, "Bartek Testowy", "Klient Alfa", "DevOps Engineer");
const CELINA = pair(3, "Celina Fikcyjna", "Klient Beta", "Analityk danych");
const DAWID = pair(4, "Dawid Wzorcowy", "Bank Przykładowy", "Tester automatyzujący");
const EWA = pair(5, "Ewa Bezkategorii", "Klient Alfa", "Java Developer");
const FILIP = pair(6, "Filip Zmyślony", "Klient Beta", "Scrum Master");
const LONG = pair(
  7,
  "Gabriela Wymyślona-Nieistniejąca",
  "Klient Alfa Spółka z ograniczoną odpowiedzialnością",
  "Analityk danych z bardzo długą nazwą stanowiska",
);

function agenda(p: PairInfo, kind: AgendaEntry["kind"], fields: Partial<AgendaEntry>): AgendaEntry {
  return {
    ...p,
    kind,
    start: at(0),
    end: null,
    event_id: 900 + p.candidate_id,
    slot_request_id: null,
    online_meeting_url: null,
    done: false,
    mine: true,
    ...fields,
  };
}

function todo(p: PairInfo, kind: TodoEntry["kind"], fields: Partial<TodoEntry> = {}): TodoEntry {
  return {
    ...p,
    kind,
    priority: 5,
    due: null,
    event_id: null,
    slot_request_id: null,
    mine: true,
    ...fields,
  };
}

function item(p: PairInfo, fields: Partial<CycleItem> = {}): CycleItem {
  return {
    ...p,
    steps: [],
    current_step: null,
    latest_stage: "client_interview",
    slot_request: null,
    interview_event_id: null,
    debrief: null,
    ...fields,
  };
}

function overview(fields: Partial<CycleOverview>): CycleOverview {
  return {
    generated_at: NOW.toISOString(),
    scope: "mine",
    call_window_minutes: 30,
    items: [],
    agenda: [],
    todos: [],
    truncated: false,
    ...fields,
  };
}

let nextId = 1;
function notif(
  type: string,
  p: PairInfo | null,
  minutesAgo: number,
  fields: Partial<NotificationResponse> = {},
): NotificationResponse {
  return {
    id: nextId++,
    user_id: 1,
    title: "Powiadomienie",
    message: "",
    link: p ? `/calendar?cycle=${p.candidate_id}-${p.job_id}` : "/calendar",
    notification_type: type,
    is_read: false,
    created_at: at(-minutesAgo),
    ...fields,
  };
}

const SLOTS = {
  id: 7,
  status: "awaiting_recruiter" as const,
  slots: [1, 2, 3].map((d) => ({ start: at(60 * 24 * d), end: null })),
  chosen_index: null,
  respond_by: at(60 * 21),
  recruiter_id: 1,
  created_by: 2,
  duration_minutes: 60,
  note: null,
  event_id: null,
};

const RECRUITER = buildInterviewWindow({
  now: NOW,
  overview: overview({
    items: [
      item(CELINA, { slot_request: SLOTS }),
      item(EWA, {
        steps: [
          { key: "interview", label: "Rozmowa", state: "scheduled", at: at(60 * 44), event_id: 5, meta: null },
        ],
      }),
    ],
    agenda: [
      agenda(ANNA, "call", { start: at(-12), end: at(18) }),
      agenda(BARTEK, "prep2", {
        start: at(12),
        end: at(42),
        online_meeting_url: "https://teams.example.invalid/prep",
      }),
      agenda(FILIP, "interview", { start: at(100), end: at(160) }),
    ],
    todos: [
      todo(CELINA, "slots_pick", { due: at(60 * 21) }),
      todo(DAWID, "prep2_missing", { due: at(60 * 19), urgent: true }),
      todo(DAWID, "prep_weak"),
    ],
  }),
  notifications: [
    notif("interview_slots_requested", CELINA, 35),
    notif("interview_slot_confirmed", EWA, 60),
  ],
});

const DELIVERY_LEAD = buildInterviewWindow({
  now: NOW,
  overview: overview({
    scope: "jobs",
    items: [
      item(CELINA, { slot_request: { ...SLOTS, status: "awaiting_dl", chosen_index: 0 } }),
      item(ANNA, {
        interview_event_id: 901,
        debrief: {
          id: 1,
          overall_impression: 5,
          outcome: "good",
          offer_acceptance: "likely",
          acceptance_condition: "start od grudnia",
          questions_count: 4,
        },
      }),
    ],
    agenda: [
      agenda(LONG, "prep", {
        start: at(8),
        end: at(38),
        online_meeting_url: "https://teams.example.invalid/prep",
      }),
    ],
    todos: [
      todo(CELINA, "slots_confirm", { due: at(60 * 44) }),
      todo(DAWID, "prep_weak", { due: at(60 * 19), urgent: true }),
      // Zadania rekruterów z „Moich rekrutacji” — serwer oznacza je jako nie moje.
      todo(BARTEK, "slots_pick", { mine: false }),
    ],
  }),
  notifications: [
    notif("interview_slot_chosen", CELINA, 20),
    notif("interview_debrief_saved", ANNA, 5),
    // 0453: odpowiedź kandydata na prep i prep założony w kalendarzu DL-a.
    notif("prep_candidate_declined", BARTEK, 3, {
      title: "Prep 2: kandydat proponuje 20.10, 16:00",
      message: "Bartek Testowy — DevOps Engineer: zamiast 20.10.2026, godz. 13:00.",
    }),
    notif("prep_changed_yours", DAWID, 40, {
      title: "Nowy Prep 1 w Twoim kalendarzu · 21.10, 10:00",
      message: "Dawid Wzorcowy — Tester automatyzujący: prep zaplanowany przez: Ola Rekruter.",
    }),
    // 0498: rozmowa u klienta przełożona przez kogoś z pary.
    notif("interview_changed", CELINA, 2, {
      title: "Rozmowa u klienta przełożona na 24.10, 14:00",
      message: "Celina Fikcyjna — Analityk danych: zmiana od: Ola Rekruter, było pt 24.10.2026, godz. 11:00.",
    }),
    notif("prep_candidate_response", ANNA, 70, {
      title: "Prep 1 przyjęty · 19.10, 09:00",
      message: "Anna Przykładowa — odpowiedź na zaproszenie z Outlooka.",
    }),
    notif("prep_attention", null, 90, {
      title: "Prep 2 bez nagrania",
      message: "Filip Zmyślony — Scrum Master: z prepu nie ma transkryptu, więc nie da się go ocenić.",
      link: "/calendar?cycle=60-61",
    }),
    notif("post_interview_t15", null, 15, {
      title: "Zadzwoń i zbierz feedback",
      message: "15 min temu skończyła się rozmowa. Zadzwoń i zbierz feedback.",
      link: "/calendar?event=77&action=feedback",
      on_behalf_of_name: "Anna Przykładowa",
    }),
  ],
});

const EMPTY = buildInterviewWindow({ now: NOW, overview: overview({}), notifications: [] });

const ONLY_NEWS = buildInterviewWindow({
  now: NOW,
  overview: null,
  notifications: [notif("interview_slot_chosen", CELINA, 20, { title: "Kandydat wybrał termin", message: "Rekruter ustalił termin z kandydatem — potwierdź go u klienta." })],
});

const noop = () => undefined;

const actionLabel = (row: InterviewWindowRow) =>
  row.todo ? TODO_ACTIONS[row.todo.kind] : null;

const BASE: InterviewsPanelProps = {
  state: "ready",
  view: RECRUITER,
  canMarkNews: true,
  actionLabel,
  onOpenRow: noop,
  onAction: noop,
  onMarkNewsRead: noop,
  onRetry: noop,
  onOpenSettings: noop,
  onOpenCalendar: noop,
};

function Frame({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="w-full max-w-[420px] shrink-0">
      <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </h2>
      <div className="overflow-hidden rounded-lg border border-border bg-card shadow-md">
        {children}
      </div>
    </section>
  );
}

export default function InterviewNotificationsPreviewPage() {
  return (
    <main className="min-h-dvh bg-muted/30 p-4 sm:p-6">
      <h1 className="mb-1 text-lg font-semibold text-foreground">
        Okienko „Rozmowy” — harness
      </h1>
      <p className="mb-4 max-w-3xl text-sm text-muted-foreground">
        Rozmowy u klienta i prepy: co dzieje się teraz, co czeka na osobę i co
        nowego przyszło. Dane fikcyjne, bez zapytań do serwera.
      </p>

      <div className="mb-6 flex flex-wrap items-center gap-6 rounded-lg border border-border bg-background px-4 py-2">
        <span className="text-xs text-muted-foreground">Ikona w pasku:</span>
        <InterviewsTopbarButton count={0} urgent={false} open={false} pill={null} />
        <InterviewsTopbarButton count={3} urgent={false} open={false} pill={null} />
        <InterviewsTopbarButton count={4} urgent open={false} pill={null} />
        <InterviewsTopbarButton count={120} urgent open pill={null} />
        <InterviewsTopbarButton
          count={4}
          urgent
          open={false}
          pill={{ name: "A. Przykładowa", minutesLeft: 18 }}
        />
      </div>

      <div className="flex flex-wrap items-start gap-6">
        <Frame title="Rekruter">
          <InterviewsPanel {...BASE} />
        </Frame>
        <Frame title="Delivery Lead">
          <InterviewsPanel {...BASE} view={DELIVERY_LEAD} />
        </Frame>
        <Frame title="Nic nie czeka">
          <InterviewsPanel {...BASE} view={EMPTY} canMarkNews={false} />
        </Frame>
        <Frame title="Zadania nie wczytane">
          <InterviewsPanel {...BASE} view={ONLY_NEWS} failed="tasks" />
        </Frame>
        <Frame title="Ładowanie">
          <InterviewsPanel {...BASE} state="loading" view={EMPTY} canMarkNews={false} />
        </Frame>
        <Frame title="Błąd">
          <InterviewsPanel {...BASE} state="error" view={EMPTY} canMarkNews={false} />
        </Frame>
      </div>
    </main>
  );
}
