/**
 * Ekran „Rozmowy u klienta” (0338): agenda, tablica i debrief.
 *
 * Pilnuje trzech rzeczy, które łatwo zepsuć:
 * - awaria listy NIE wygląda jak „nic nie czeka” (pustka czyta się jak wolny dzień),
 * - „Zadzwoń teraz” prowadzi do debriefu, a debrief wysyła trzy pola z ticketu,
 * - akcje DL (terminy, potwierdzenie) nie pokazują się rekruterowi.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

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
          { key: "choice", label: "", state: "done", at: null, event_id: null, meta: null },
          { key: "prep", label: "", state: "done", at: iso(-600), event_id: 1, meta: null },
          { key: "prep2", label: "", state: "skipped", at: null, event_id: null, meta: null },
          { key: "interview", label: "", state: "done", at: iso(-72), event_id: 44, meta: null },
          { key: "call", label: "", state: "current", at: iso(18), event_id: 44, meta: "teraz" },
          { key: "debrief", label: "", state: "todo", at: null, event_id: 44, meta: null },
        ],
        current_step: "call",
        latest_stage: "client_interview",
        slot_request: null,
        interview_event_id: 44,
        debrief: null,
      },
    ],
    agenda: [
      { ...PAIR, kind: "interview", start: iso(-72), end: iso(-12), event_id: 44, slot_request_id: null, online_meeting_url: null, done: false },
      { ...PAIR, kind: "call", start: iso(-12), end: iso(18), event_id: 44, slot_request_id: null, online_meeting_url: null, done: false },
    ],
    todos: [
      { ...PAIR, kind: "call_now", priority: 0, due: iso(18), event_id: 44, slot_request_id: null },
    ],
    truncated: false,
  };
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
  mocks.put.mockReset();
  mocks.replace.mockReset();
  mocks.push.mockReset();
  mocks.search = "";
  mocks.user = { id: 7, role: "recruiter", roles: ["recruiter"] };
  Object.values(mocks.toast).forEach((fn) => fn.mockReset());
  mocks.get.mockImplementation((url: string) => {
    if (url === "/api/interview-cycle") return Promise.resolve({ data: overview() });
    if (url === "/api/interview-cycle/client-questions") {
      return Promise.resolve({ data: [{ id: 1, text: "Transakcje w Spring", created_at: null }] });
    }
    if (url.endsWith("/debrief")) return Promise.resolve({ data: null });
    return Promise.resolve({ data: [] });
  });
});

describe("CalendarCycleScreen", () => {
  it("awaria listy to komunikat, nie pusta agenda", async () => {
    mocks.get.mockImplementation((url: string) =>
      url === "/api/interview-cycle"
        ? Promise.reject(Object.assign(new Error("500"), { response: { status: 500 } }))
        : Promise.resolve({ data: [] }),
    );
    renderScreen();
    expect(await screen.findByText(/Nie udało się pobrać danych/)).toBeInTheDocument();
    expect(screen.queryByText(/Nic nie czeka/)).not.toBeInTheDocument();
  });

  it("„Zadzwoń teraz” → debrief wysyła jak poszło, pytania i ofertę", async () => {
    mocks.put.mockResolvedValue({
      data: { id: 1, calendar_event_id: 44, candidate_id: 11, job_id: 22, outcome: "good", candidate_comment: null, questions: ["Kafka"], offer_acceptance: "likely", acceptance_condition: null, questions_saved: 1 },
    });
    renderScreen();
    const card = await screen.findByTestId("cycle-call-now");
    expect(card).toHaveTextContent("Piotr Nowak");
    expect(card).toHaveTextContent(/zostało \d+ min/);
    fireEvent.click(within(card).getByRole("button", { name: "Zapisz debrief" }));

    const dialog = await screen.findByRole("dialog", { name: "Debrief po rozmowie u klienta" });
    // Formularz jest zablokowany, dopóki nie wróci zapisany debrief (poprawka).
    await waitFor(() => expect(within(dialog).getByLabelText("Dobrze")).not.toBeDisabled());
    fireEvent.click(within(dialog).getByLabelText("Dobrze"));
    fireEvent.change(within(dialog).getByLabelText("Pytanie 1"), { target: { value: "Kafka" } });
    fireEvent.click(within(dialog).getByLabelText("Raczej tak"));
    fireEvent.click(within(dialog).getByRole("button", { name: "Zapisz debrief" }));

    await waitFor(() =>
      expect(mocks.put).toHaveBeenCalledWith(
        "/api/interview-cycle/events/44/debrief",
        expect.objectContaining({
          outcome: "good",
          questions: ["Kafka"],
          offer_acceptance: "likely",
          notify_dl: true,
        }),
      ),
    );
    expect(mocks.toast.showSuccess).toHaveBeenCalledWith(expect.stringMatching(/Nowe pytania klienta: 1/));
  });

  it("debrief bez odpowiedzi o ofercie się nie wysyła", async () => {
    renderScreen();
    fireEvent.click(within(await screen.findByTestId("cycle-call-now")).getByRole("button", { name: "Zapisz debrief" }));
    const dialog = await screen.findByRole("dialog", { name: "Debrief po rozmowie u klienta" });
    // Formularz jest zablokowany, dopóki nie wróci zapisany debrief (poprawka).
    await waitFor(() => expect(within(dialog).getByLabelText("Dobrze")).not.toBeDisabled());
    fireEvent.click(within(dialog).getByLabelText("Średnio"));
    fireEvent.click(within(dialog).getByRole("button", { name: "Zapisz debrief" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(/przyjmie ofertę/);
    expect(mocks.put).not.toHaveBeenCalled();
  });

  it("karta kandydata pokazuje pytania klienta z poprzednich debriefów", async () => {
    renderScreen();
    const questions = await screen.findByTestId("cycle-client-questions");
    await waitFor(() => expect(questions).toHaveTextContent("Transakcje w Spring"));
    // Nazwa klienta nie ma rodzaju — bez „Alior pytał”.
    expect(questions).toHaveTextContent("Pytania klienta Alior z poprzednich rozmów");
  });

  it("bez kandydatów w cyklu nie ma pustej karty kandydata", async () => {
    mocks.get.mockImplementation((url: string) =>
      url === "/api/interview-cycle"
        ? Promise.resolve({ data: { ...overview(), items: [], agenda: [], todos: [] } })
        : Promise.resolve({ data: [] }),
    );
    renderScreen();
    expect(await screen.findByText(/Nic nie czeka/)).toBeInTheDocument();
    expect(screen.queryByRole("complementary", { name: "Wybrany kandydat" })).not.toBeInTheDocument();
  });

  it("rekruter nie widzi „Terminy od klienta”, DL widzi", async () => {
    renderScreen();
    await screen.findByTestId("cycle-call-now");
    expect(screen.queryByRole("button", { name: /Terminy od klienta/ })).not.toBeInTheDocument();

    mocks.user = { id: 8, role: "delivery_lead", roles: ["delivery_lead"] };
    renderScreen();
    expect(await screen.findByRole("button", { name: /Terminy od klienta/ })).toBeInTheDocument();
    // DL domyślnie patrzy na swoje rekrutacje.
    await waitFor(() =>
      expect(mocks.get).toHaveBeenCalledWith("/api/interview-cycle", { params: { scope: "jobs" } }),
    );
  });

  it("bez wyboru z linku karta pokazuje PIERWSZĄ osobę z „Do zrobienia” i lista ją zaznacza", async () => {
    // Kolejność `items` (serwer) różni się od kolejności zadań — na prodzie
    // karta pokazywała czwartą osobę z listy, a lista nie mówiła, kto wybrany.
    const base = overview().items[0];
    const slotsItem = (id: number, name: string) => ({
      ...base,
      candidate_id: id,
      candidate_name: name,
      current_step: "slots" as const,
      steps: base.steps.map((st) => ({ ...st, state: st.key === "slots" ? ("current" as const) : ("todo" as const) })),
    });
    const later = slotsItem(91, "Zofia Późniejsza");
    const first = slotsItem(92, "Adam Pierwszy");
    const todo = (p: { candidate_id: number; candidate_name: string }) => ({
      ...PAIR,
      candidate_id: p.candidate_id,
      candidate_name: p.candidate_name,
      kind: "slots_missing" as const,
      priority: 5,
      due: null,
      event_id: null,
      slot_request_id: null,
    });
    mocks.get.mockImplementation((url: string) => {
      if (url === "/api/interview-cycle") {
        return Promise.resolve({
          data: { ...overview(), items: [later, first], agenda: [], todos: [todo(first), todo(later)] },
        });
      }
      return Promise.resolve({ data: [] });
    });
    renderScreen();
    const card = await screen.findByRole("complementary", { name: "Wybrany kandydat" });
    expect(within(card).getByText("Adam Pierwszy")).toBeInTheDocument();
    const current = document.querySelectorAll('[aria-current="true"]');
    expect(current).toHaveLength(1);
    expect(current[0]).toHaveTextContent("Adam Pierwszy");
  });

  it("tablica stawia kandydata w kolumnie bieżącego kroku", async () => {
    mocks.search = "view=board";
    renderScreen();
    const column = await screen.findByRole("listitem", { name: "Telefon ≤ 30 min" });
    expect(within(column).getByText("Piotr Nowak")).toBeInTheDocument();
  });

  it("link z dzwonka (?debrief=) otwiera debrief tej rozmowy", async () => {
    mocks.search = "cycle=11-22&debrief=44";
    renderScreen();
    expect(
      await screen.findByRole("dialog", { name: "Debrief po rozmowie u klienta" }),
    ).toHaveTextContent("Piotr Nowak");
  });

  it("?event= otwiera Tydzień i nie pyta o agendę", async () => {
    mocks.search = "event=44";
    renderScreen();
    expect(await screen.findByTestId("week-calendar")).toBeInTheDocument();
    expect(mocks.get).not.toHaveBeenCalledWith("/api/interview-cycle", expect.anything());
  });
});
