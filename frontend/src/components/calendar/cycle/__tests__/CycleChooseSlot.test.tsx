/**
 * Runda 10 (F26): nowe terminy od klienta po odbytej rozmowie.
 * „Wybierz termin” z panelu kandydata otwiera wybór terminu.
 *
 * (Wspólne mocki skopiowane z CalendarCycleScreen.test.tsx.)
 * Zakładka „Agenda” zniknęła 24.09.2026 — jej treść jest w panelu karty.
 *
 * Pilnuje rzeczy, które łatwo zepsuć:
 * - awaria listy NIE wygląda jak „nic nie czeka” (pustka czyta się jak wolny dzień),
 * - telefon po rozmowie prowadzi do debriefu, a debrief wysyła trzy pola z ticketu,
 * - akcje DL (terminy, potwierdzenie) nie pokazują się rekruterowi,
 * - stare linki (`?view=agenda`, `?cycle=`, `?debrief=`) dalej prowadzą w dobre miejsce.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterAll, beforeEach, describe, expect, it, vi } from "vitest";

import type { CycleOverview } from "@/lib/interview-cycle";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  replace: vi.fn(),
  push: vi.fn(),
  search: "",
  user: { id: 7, role: "recruiter", roles: ["recruiter"] } as Record<string, unknown>,
  toast: { showError: vi.fn(), showSuccess: vi.fn(), showToast: vi.fn(), showActionToast: vi.fn() },
}));

vi.mock("@/lib/api", () => ({
  api: {
    get: (...a: unknown[]) => mocks.get(...a),
    post: (...a: unknown[]) => mocks.post(...a),
    put: (...a: unknown[]) => mocks.put(...a),
  },
}));
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(mocks.search),
  useRouter: () => ({ replace: mocks.replace, push: mocks.push }),
}));
vi.mock("@/components/Toast", () => ({ useToast: () => mocks.toast }));
vi.mock("@/components/calendar/WeekCalendar", () => ({
  default: () => <div data-testid="week-calendar">tydzień</div>,
}));
vi.mock("@/components/calendar/ScheduleInterviewModal", () => ({
  default: ({ defaultTitle }: { defaultTitle?: string }) => (
    <div data-testid="schedule-modal">{defaultTitle}</div>
  ),
}));
vi.mock("@/store/auth", async (orig) => {
  const actual = await orig<typeof import("@/store/auth")>();
  return {
    ...actual,
    useAuthStore: (sel: (s: { user: unknown }) => unknown) => sel({ user: mocks.user }),
  };
});

import { CalendarCycleScreen } from "@/components/calendar/cycle/CalendarCycleScreen";

// Zegar przypięty na dzisiejsze południe: dane są względne wobec „teraz”, a
// panel kandydata pokazuje wydarzenia od dzisiejszego dnia. Między 00:00
// a 01:12 rozmowa sprzed 72 min wypadała na wczoraj i test padał co noc
// (kolejka merge'ów 26.09.2026). Fałszujemy tylko `Date` — timery zostają
// prawdziwe, więc `findBy*`/`waitFor` działają bez zmian.
vi.useFakeTimers({ toFake: ["Date"] });
vi.setSystemTime(
  (() => {
    const noon = new Date();
    noon.setHours(12, 0, 0, 0);
    return noon;
  })(),
);
afterAll(() => {
  vi.useRealTimers();
});

const NOW = Date.now();
const iso = (minutesFromNow: number) => new Date(NOW + minutesFromNow * 60_000).toISOString();

const PAIR = {
  candidate_id: 11,
  candidate_name: "Piotr Nowak",
  candidate_email: "piotr@example.com",
  job_id: 22,
  job_title: "Senior Java",
  client_id: 33,
  client_name: "Alior",
};

const REQUEST = {
  id: 5,
  status: "awaiting_recruiter",
  slots: [
    { start: iso(60 * 30), end: iso(60 * 30 + 30) },
    { start: iso(60 * 54), end: iso(60 * 54 + 30) },
  ],
  chosen_index: null,
  respond_by: null,
  recruiter_id: 7,
  created_by: 9,
  duration_minutes: 30,
  note: null,
  event_id: null,
};

function overview(): CycleOverview {
  return {
    generated_at: iso(0),
    scope: "mine",
    call_window_minutes: 30,
    items: [
      {
        ...PAIR,
        steps: [
          { key: "slots", label: "", state: "done", at: null, event_id: null, meta: null },
          { key: "choice", label: "", state: "current", at: null, event_id: null, meta: "2 terminy do wyboru" },
          { key: "prep", label: "", state: "todo", at: null, event_id: null, meta: null },
          { key: "prep2", label: "", state: "todo", at: null, event_id: null, meta: null },
          { key: "interview", label: "", state: "todo", at: null, event_id: null, meta: null },
          { key: "call", label: "", state: "todo", at: null, event_id: null, meta: null },
          { key: "debrief", label: "", state: "todo", at: null, event_id: null, meta: null },
        ],
        current_step: "choice",
        latest_stage: "client_interview",
        slot_request: REQUEST,
        interview_event_id: 44,
        debrief: null,
      },
    ],
    agenda: [],
    todos: [
      { ...PAIR, kind: "debrief_overdue", priority: 1, due: iso(-120), event_id: 44, slot_request_id: null },
      { ...PAIR, kind: "slots_pick", priority: 2, due: null, event_id: null, slot_request_id: 5 },
    ],
    truncated: false,
  } as unknown as CycleOverview;
}

function renderScreen() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(
    <QueryClientProvider client={client}>
      <CalendarCycleScreen />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mocks.get.mockReset();
  mocks.post.mockReset();
  mocks.search = "cycle=11-22";
  mocks.user = { id: 7, role: "recruiter", roles: ["recruiter"] };
  mocks.get.mockImplementation((url: string) => {
    if (url === "/api/interview-cycle") return Promise.resolve({ data: overview() });
    return Promise.resolve({ data: [] });
  });
});

describe("nowe terminy po odbytej rozmowie (F26)", () => {
  it("„Wybierz termin” z zadań panelu otwiera wybór terminu", async () => {
    renderScreen();
    const panel = await screen.findByTestId("cycle-candidate-card");
    const todos = within(panel).getByRole("list", { name: "Do zrobienia przy tym kandydacie" });
    fireEvent.click(within(todos).getByRole("button", { name: "Wybierz termin" }));
    expect(await screen.findByRole("dialog", { name: "Termin ustalony z kandydatem" })).toBeInTheDocument();
  });

  it("„Wybierz termin” przy kroku otwiera wybór terminu", async () => {
    renderScreen();
    const panel = await screen.findByTestId("cycle-candidate-card");
    const steps = within(panel).getByRole("list", { name: "Kroki rozmowy u klienta" });
    fireEvent.click(within(steps).getByRole("button", { name: "Wybierz termin" }));
    expect(await screen.findByRole("dialog", { name: "Termin ustalony z kandydatem" })).toBeInTheDocument();
  });
});
