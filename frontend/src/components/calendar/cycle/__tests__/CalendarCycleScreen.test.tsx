/**
 * Ekran „Rozmowy u klienta” (0338): Tablica, panel kandydata i debrief.
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
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
import { DebriefDialog } from "@/components/calendar/cycle/DebriefDialog";

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

async function callCard() {
  const column = await screen.findByRole("listitem", { name: "Telefon po rozmowie" });
  return within(column).getByTestId("cycle-board-card");
}

describe("CalendarCycleScreen", () => {
  it("awaria listy to komunikat, nie pusta tablica", async () => {
    mocks.get.mockImplementation((url: string) =>
      url === "/api/interview-cycle"
        ? Promise.reject(Object.assign(new Error("500"), { response: { status: 500 } }))
        : Promise.resolve({ data: [] }),
    );
    renderScreen();
    expect(await screen.findByText(/Nie udało się pobrać danych/)).toBeInTheDocument();
    expect(screen.queryByText(/Żaden kandydat nie jest/)).not.toBeInTheDocument();
  });

  it("domyślnie Tablica: dwa widoki, bez Agendy", async () => {
    renderScreen();
    const views = await screen.findByRole("radiogroup", { name: "Widok" });
    expect(within(views).getAllByRole("radio").map((r) => r.textContent)).toEqual(["Tydzień", "Tablica"]);
    expect(within(views).getByRole("radio", { name: "Tablica" })).toHaveAttribute("aria-checked", "true");
    expect(await screen.findByRole("listitem", { name: "Telefon po rozmowie" })).toBeInTheDocument();
  });

  it("stary link ?view=agenda prowadzi na Tablicę", async () => {
    mocks.search = "view=agenda";
    renderScreen();
    expect(await screen.findByRole("listitem", { name: "Telefon po rozmowie" })).toBeInTheDocument();
  });

  it("telefon po rozmowie: karta odlicza, a „Zapisz debrief” wysyła jak poszło, pytania i ofertę", async () => {
    mocks.put.mockResolvedValue({
      data: { id: 1, calendar_event_id: 44, candidate_id: 11, job_id: 22, outcome: "good", candidate_comment: null, questions: ["Kafka"], offer_acceptance: "likely", acceptance_condition: null, questions_saved: 1 },
    });
    renderScreen();
    const card = await callCard();
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
    fireEvent.click(within(await callCard()).getByRole("button", { name: "Zapisz debrief" }));
    const dialog = await screen.findByRole("dialog", { name: "Debrief po rozmowie u klienta" });
    await waitFor(() => expect(within(dialog).getByLabelText("Dobrze")).not.toBeDisabled());
    fireEvent.click(within(dialog).getByLabelText("Średnio"));
    fireEvent.click(within(dialog).getByRole("button", { name: "Zapisz debrief" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(/przyjmie ofertę/);
    expect(mocks.put).not.toHaveBeenCalled();
  });

  it("klik w kandydata otwiera panel: kroki, zadanie, linki i pytania klienta", async () => {
    renderScreen();
    const card = await callCard();
    fireEvent.click(within(card).getByRole("button", { name: /Piotr Nowak — pokaż kroki/ }));
    expect(mocks.replace).toHaveBeenCalledWith("/calendar?cycle=11-22");
    const panel = await screen.findByTestId("cycle-candidate-card");
    expect(within(panel).getByRole("link", { name: /Rekrutacja/ })).toHaveAttribute("href", "/jobs/22?candidate=11");
    expect(within(panel).getByRole("link", { name: /Profil/ })).toHaveAttribute("href", "/candidates/11");
    expect(within(panel).getByText("Zadzwoń teraz")).toBeInTheDocument();
    expect(within(panel).getByRole("list", { name: "Kroki rozmowy u klienta" })).toBeInTheDocument();
    const questions = await within(panel).findByTestId("cycle-client-questions");
    await waitFor(() => expect(questions).toHaveTextContent("Transakcje w Spring"));
    expect(questions).toHaveTextContent("Pytania klienta Alior z poprzednich rozmów");
  });

  it("link z dzwonka do pary spoza „mine” przełącza HoR na cały zespół (R10-N15-4)", async () => {
    mocks.user = { id: 3, role: "head_of_recruitment", roles: ["head_of_recruitment"] };
    mocks.search = "cycle=5-9";
    renderScreen();
    await waitFor(() => expect(mocks.replace).toHaveBeenCalledWith("/calendar?cycle=5-9&scope=all"));
    expect(mocks.replace).toHaveBeenCalledTimes(1);
  });

  it("link z dzwonka do pary spoza najszerszego zakresu mówi to wprost (R10-N15-4)", async () => {
    mocks.search = "scope=jobs&cycle=5-9";
    renderScreen();
    expect(await screen.findByTestId("cycle-link-out-of-scope")).toHaveTextContent(
      /nie ma w Twoim zakresie/,
    );
    expect(mocks.replace).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Zamknij" }));
    expect(mocks.replace).toHaveBeenCalledWith("/calendar?scope=jobs");
  });

  it("para z linku jest w zakresie — bez przełączania i bez komunikatu", async () => {
    mocks.user = { id: 3, role: "head_of_recruitment", roles: ["head_of_recruitment"] };
    mocks.search = "cycle=11-22";
    renderScreen();
    expect(await screen.findByTestId("cycle-candidate-card")).toBeInTheDocument();
    expect(mocks.replace).not.toHaveBeenCalled();
    expect(screen.queryByTestId("cycle-link-out-of-scope")).not.toBeInTheDocument();
  });

  it("link z dzwonka ?cycle= otwiera panel tego kandydata", async () => {
    mocks.search = "cycle=11-22";
    renderScreen();
    const panel = await screen.findByTestId("cycle-candidate-card");
    expect(within(panel).getByText("Alior · Senior Java")).toBeInTheDocument();
  });

  it("panel nie otwiera się sam po powrocie z Tygodnia (link bez ?cycle=)", async () => {
    mocks.search = "cycle=11-22";
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
    const view = render(
      <QueryClientProvider client={client}>
        <CalendarCycleScreen />
      </QueryClientProvider>,
    );
    expect(await screen.findByTestId("cycle-candidate-card")).toBeInTheDocument();
    // „Szczegóły” → Tydzień (`?cycle=` znika z adresu), potem powrót na Tablicę.
    mocks.search = "view=week&event=44";
    view.rerender(
      <QueryClientProvider client={client}>
        <CalendarCycleScreen />
      </QueryClientProvider>,
    );
    await screen.findByTestId("week-calendar");
    mocks.search = "";
    view.rerender(
      <QueryClientProvider client={client}>
        <CalendarCycleScreen />
      </QueryClientProvider>,
    );
    await screen.findByRole("listitem", { name: "Telefon po rozmowie" });
    expect(screen.queryByTestId("cycle-candidate-card")).not.toBeInTheDocument();
  });

  it("„Szczegóły” z panelu otwierają Tydzień i zachowują wybrany zakres", async () => {
    mocks.search = "scope=jobs&cycle=11-22";
    renderScreen();
    const panel = await screen.findByTestId("cycle-candidate-card");
    fireEvent.click(within(panel).getByRole("button", { name: "Szczegóły" }));
    expect(mocks.push).toHaveBeenCalledWith("/calendar?scope=jobs&view=week&event=44");
  });

  it("bez kandydatów w cyklu jest komunikat, bez pustego panelu", async () => {
    mocks.get.mockImplementation((url: string) =>
      url === "/api/interview-cycle"
        ? Promise.resolve({ data: { ...overview(), items: [], agenda: [], todos: [] } })
        : Promise.resolve({ data: [] }),
    );
    renderScreen();
    expect(await screen.findByText(/Żaden kandydat nie jest w trakcie/)).toBeInTheDocument();
    expect(screen.queryByTestId("cycle-candidate-card")).not.toBeInTheDocument();
  });

  it("rekruter nie widzi „Terminy od klienta”, DL widzi (także w Tygodniu)", async () => {
    renderScreen();
    await callCard();
    expect(screen.queryByRole("button", { name: /Terminy od klienta/ })).not.toBeInTheDocument();

    mocks.user = { id: 8, role: "delivery_lead", roles: ["delivery_lead"] };
    renderScreen();
    expect(await screen.findByRole("button", { name: /Terminy od klienta/ })).toBeInTheDocument();
    // DL domyślnie patrzy na swoje rekrutacje.
    await waitFor(() =>
      expect(mocks.get).toHaveBeenCalledWith("/api/interview-cycle", { params: { scope: "jobs" } }),
    );
  });

  it("zakres to lista „Pokaż”, a zmiana zapisuje się w adresie", async () => {
    renderScreen();
    const select = await screen.findByRole("combobox", { name: "Zakres" });
    expect(select).toHaveValue("mine");
    fireEvent.change(select, { target: { value: "jobs" } });
    expect(mocks.replace).toHaveBeenCalledWith("/calendar?scope=jobs");
  });

  it("puste kroki są zwinięte, a przełącznik je rozwija", async () => {
    renderScreen();
    expect(await screen.findByRole("listitem", { name: "Terminy od klienta — pusto" })).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Zwiń puste kroki"));
    expect(screen.getByRole("listitem", { name: "Terminy od klienta" })).toBeInTheDocument();
  });

  it("zadanie pary (np. słaby prep) stoi na karcie", async () => {
    const data = overview();
    data.todos = [
      ...data.todos,
      { ...PAIR, kind: "prep_weak", priority: 3, due: null, event_id: 1, slot_request_id: null },
    ];
    mocks.get.mockImplementation((url: string) =>
      url === "/api/interview-cycle" ? Promise.resolve({ data }) : Promise.resolve({ data: [] }),
    );
    renderScreen();
    expect(await callCard()).toHaveTextContent("Prep słaby — popraw przed rozmową");
  });

  it("link z dzwonka (?debrief=) otwiera debrief tej rozmowy", async () => {
    mocks.search = "cycle=11-22&debrief=44";
    renderScreen();
    expect(
      await screen.findByRole("dialog", { name: "Debrief po rozmowie u klienta" }),
    ).toHaveTextContent("Piotr Nowak");
  });

  it("?event= otwiera Tydzień i nie pyta o cykl", async () => {
    mocks.search = "event=44";
    renderScreen();
    expect(await screen.findByTestId("week-calendar")).toBeInTheDocument();
    expect(mocks.get).not.toHaveBeenCalledWith("/api/interview-cycle", expect.anything());
  });

  it("debrief przed rozpoczęciem rozmowy jest w panelu nieaktywny, z godziną dostępności", async () => {
    // Rozmowa za 2 h (test na produkcji 23.09.2026: debrief dało się zapisać dzień
    // przed rozmową i oba kroki wyglądały na zrobione).
    const future = overview();
    future.items[0].steps = future.items[0].steps.map((st) =>
      st.key === "interview"
        ? { ...st, state: "scheduled", at: iso(120) }
        : st.key === "call" || st.key === "debrief"
          ? { ...st, state: "todo" }
          : st,
    );
    future.items[0].current_step = "interview";
    future.agenda = [
      { ...PAIR, kind: "interview", start: iso(120), end: iso(180), event_id: 44, slot_request_id: null, online_meeting_url: null, done: false },
      { ...PAIR, kind: "call", start: iso(180), end: iso(210), event_id: 44, slot_request_id: null, online_meeting_url: null, done: false },
    ];
    future.todos = [];
    mocks.get.mockImplementation((url: string) => {
      if (url === "/api/interview-cycle") return Promise.resolve({ data: future });
      return Promise.resolve({ data: [] });
    });
    mocks.search = "cycle=11-22";
    renderScreen();
    const panel = await screen.findByTestId("cycle-candidate-card");
    const debrief = within(panel).getByRole("button", { name: "Debrief" });
    expect(debrief).toBeDisabled();
    expect(debrief).toHaveAccessibleDescription(/^Debrief po rozmowie — dostępny od /);
    expect(within(panel).queryByRole("button", { name: "Zapisz debrief" })).not.toBeInTheDocument();
  });
});

describe("DebriefDialog (bramka na tablicy)", () => {
  function renderDialog() {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
    return render(
      <QueryClientProvider client={client}>
        <DebriefDialog open onOpenChange={() => {}} eventId={44} title="Telefon po rozmowie" />
      </QueryClientProvider>,
    );
  }

  it("rozmowa w przyszłości: okno mówi, od kiedy, i nie pozwala zapisać", async () => {
    mocks.get.mockImplementation((url: string) => {
      if (url === "/api/interview-cycle/events/44") {
        return Promise.resolve({
          data: { id: 44, candidate_id: 11, job_id: 22, start: iso(24 * 60), end: null, started: false },
        });
      }
      if (url.endsWith("/debrief")) return Promise.resolve({ data: null });
      return Promise.resolve({ data: [] });
    });
    renderDialog();
    const notice = await screen.findByTestId("debrief-not-started");
    expect(notice).toHaveTextContent("Debrief po rozmowie — dostępny od jutra");
    expect(notice).toHaveTextContent("Rozmowa u klienta jeszcze się nie odbyła");
    expect(screen.getByRole("button", { name: "Zapisz debrief" })).toBeDisabled();
    expect(mocks.put).not.toHaveBeenCalled();
  });

  it("rozmowa już trwa: zapis dostępny", async () => {
    mocks.get.mockImplementation((url: string) => {
      if (url === "/api/interview-cycle/events/44") {
        return Promise.resolve({
          data: { id: 44, candidate_id: 11, job_id: 22, start: iso(-5), end: null, started: true },
        });
      }
      if (url.endsWith("/debrief")) return Promise.resolve({ data: null });
      return Promise.resolve({ data: [] });
    });
    renderDialog();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Zapisz debrief" })).toBeEnabled(),
    );
    expect(screen.queryByTestId("debrief-not-started")).not.toBeInTheDocument();
  });
});

describe("Zapisany debrief (04.10.2026)", () => {
  function savedOverview(): CycleOverview {
    const base = overview();
    base.items[0].steps = base.items[0].steps.map((s) =>
      s.key === "call" || s.key === "debrief" ? { ...s, state: "done" } : s,
    );
    base.items[0].current_step = null;
    base.items[0].debrief = {
      id: 5,
      overall_impression: 5,
      outcome: "good",
      offer_acceptance: "likely",
      acceptance_condition: "Chce jednak 125 zł/h",
      candidate_comment: "Projekt mu się podoba",
      questions_count: 3,
      no_client_questions: false,
    };
    base.agenda = base.agenda.map((a) => (a.kind === "call" ? { ...a, done: true } : a));
    base.todos = [];
    return base;
  }

  const SAVED = {
    id: 5,
    calendar_event_id: 44,
    candidate_id: 11,
    job_id: 22,
    outcome: "good",
    candidate_comment: "Projekt mu się podoba",
    questions: ["Kafka", "Spring", "Docker"],
    offer_acceptance: "likely",
    acceptance_condition: "Chce jednak 125 zł/h",
    no_client_questions: false,
    questions_saved: 0,
  };

  it("panel kandydata pokazuje skrót z warunkiem i otwiera cały debrief", async () => {
    mocks.get.mockImplementation((url: string) => {
      if (url === "/api/interview-cycle") return Promise.resolve({ data: savedOverview() });
      if (url.endsWith("/debrief")) return Promise.resolve({ data: SAVED });
      return Promise.resolve({ data: [] });
    });
    mocks.search = "cycle=11-22";
    renderScreen();
    const panel = await screen.findByTestId("cycle-candidate-card");
    const summary = within(panel).getByTestId("debrief-summary");
    expect(summary).toHaveTextContent("dobrze · raczej przyjmie · 3 pytania klienta");
    expect(summary).toHaveTextContent("Warunek: Chce jednak 125 zł/h");
    expect(within(panel).queryByText("debrief zapisany")).not.toBeInTheDocument();

    fireEvent.click(within(panel).getByRole("button", { name: "Zobacz debrief" }));
    const dialog = await screen.findByRole("dialog", { name: "Debrief po rozmowie u klienta" });
    await waitFor(() =>
      expect(within(dialog).getByLabelText("Inne warunki")).toHaveValue("Chce jednak 125 zł/h"),
    );
    expect(within(dialog).getByLabelText("Pytanie 3")).toHaveValue("Docker");
  });

  it("rola bez zapisu widzi debrief tylko do odczytu", async () => {
    mocks.user = { id: 9, role: "user", roles: ["user"] };
    mocks.get.mockImplementation((url: string) => {
      if (url === "/api/interview-cycle") return Promise.resolve({ data: savedOverview() });
      if (url.endsWith("/debrief")) return Promise.resolve({ data: SAVED });
      return Promise.resolve({ data: [] });
    });
    mocks.search = "cycle=11-22";
    renderScreen();
    const panel = await screen.findByTestId("cycle-candidate-card");
    fireEvent.click(within(panel).getByRole("button", { name: "Zobacz debrief" }));
    const dialog = await screen.findByRole("dialog", { name: "Debrief po rozmowie u klienta" });
    await waitFor(() =>
      expect(within(dialog).getByLabelText("Warunek / zastrzeżenie")).toHaveValue("Chce jednak 125 zł/h"),
    );
    expect(within(dialog).getByLabelText("Warunek / zastrzeżenie")).toBeDisabled();
    expect(within(dialog).queryByRole("button", { name: "Zapisz debrief" })).not.toBeInTheDocument();
    // Krzyżyk okna i przycisk w stopce.
    expect(within(dialog).getAllByRole("button", { name: "Zamknij" })).toHaveLength(2);
    // Puste pole „dopisz pytanie” nie udaje czwartego pytania.
    expect(within(dialog).queryByLabelText("Pytanie 4")).not.toBeInTheDocument();
  });
});

describe("DebriefDialog — lista pytań klienta", () => {
  function renderDialog() {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
    mocks.get.mockImplementation((url: string) => {
      if (url === "/api/interview-cycle/events/44") {
        return Promise.resolve({
          data: { id: 44, candidate_id: 11, job_id: 22, start: iso(-60), end: null, started: true },
        });
      }
      if (url.endsWith("/debrief")) return Promise.resolve({ data: null });
      return Promise.resolve({ data: [] });
    });
    return render(
      <QueryClientProvider client={client}>
        <DebriefDialog open onOpenChange={() => {}} eventId={44} title="Debrief" />
      </QueryClientProvider>,
    );
  }

  it("wklejona lista trafia jako osobne pytania, bez numerów i powtórzeń", async () => {
    renderDialog();
    const first = await screen.findByLabelText("Pytanie 1");
    await waitFor(() => expect(first).not.toBeDisabled());
    fireEvent.paste(first, {
      clipboardData: { getData: () => "1. Kafka?\n2) Spring Boot\n- kafka?\n• Docker" },
    });
    expect(screen.getByLabelText("Pytanie 1")).toHaveValue("Kafka?");
    expect(screen.getByLabelText("Pytanie 2")).toHaveValue("Spring Boot");
    expect(screen.getByLabelText("Pytanie 3")).toHaveValue("Docker");
    expect(screen.getByLabelText("Pytanie 4")).toHaveValue("");
    expect(screen.getByText("3 z 30")).toBeInTheDocument();
  });

  it("„Wklej listę pytań” dokleja pytania do już wpisanych", async () => {
    renderDialog();
    const first = await screen.findByLabelText("Pytanie 1");
    await waitFor(() => expect(first).not.toBeDisabled());
    fireEvent.change(first, { target: { value: "Pierwsze" } });
    fireEvent.click(screen.getByRole("button", { name: "Wklej listę pytań" }));
    fireEvent.change(screen.getByLabelText(/Każda linia to osobne pytanie/), {
      target: { value: "Drugie\nTrzecie" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Dodaj do listy" }));
    expect(screen.getByLabelText("Pytanie 2")).toHaveValue("Drugie");
    expect(screen.getByLabelText("Pytanie 3")).toHaveValue("Trzecie");
  });
});


describe("DebriefDialog — stawka kandydata (0418)", () => {
  it("„Zmieniła się” wysyła nową stawkę razem z debriefem i mówi, kto dostanie informację", async () => {
    mocks.get.mockImplementation((url: string) => {
      if (url === "/api/interview-cycle/events/44") {
        return Promise.resolve({
          data: { id: 44, candidate_id: 11, job_id: 22, start: iso(-60), end: null, started: true },
        });
      }
      if (url === "/api/rate-changes") {
        return Promise.resolve({
          data: {
            candidate_id: 11,
            job_id: 22,
            current: { amount: "110", unit: "hourly", currency: "PLN", hourly: "110", label: "110 zł/h" },
            board_column: "client_interview",
            notifies: true,
            cv_at_client: true,
            client_rate: null,
            changes: [],
          },
        });
      }
      if (url.endsWith("/debrief")) return Promise.resolve({ data: null });
      return Promise.resolve({ data: [] });
    });
    mocks.put.mockResolvedValue({
      data: { id: 1, calendar_event_id: 44, candidate_id: 11, job_id: 22, outcome: "good", candidate_comment: null, questions: [], offer_acceptance: "likely", acceptance_condition: null, no_client_questions: true, questions_saved: 0 },
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
    render(
      <QueryClientProvider client={client}>
        <DebriefDialog open onOpenChange={() => {}} eventId={44} title="Debrief" />
      </QueryClientProvider>,
    );
    const rate = await screen.findByTestId("debrief-rate");
    expect(await within(rate).findByText("Bez zmian (110 zł/h)")).toBeInTheDocument();
    fireEvent.click(within(rate).getByLabelText("Zmieniła się"));
    fireEvent.change(screen.getByLabelText("Nowa stawka B2B netto (zł/h)"), { target: { value: "125" } });
    fireEvent.click(screen.getByLabelText("Możliwe, warto porozmawiać"));
    expect(screen.getByTestId("debrief-rate-notice")).toHaveTextContent(
      "CV jest już u klienta, więc przy wyższej stawce DL dostanie zadanie",
    );
    fireEvent.click(screen.getByLabelText("Dobrze"));
    fireEvent.click(screen.getByLabelText("Raczej tak"));
    fireEvent.click(screen.getByLabelText("Klient nie zadawał pytań"));
    fireEvent.click(screen.getByRole("button", { name: "Zapisz debrief" }));
    await waitFor(() => expect(mocks.put).toHaveBeenCalled());
    const body = mocks.put.mock.calls[0][1] as Record<string, unknown>;
    expect(body.rate_change).toEqual({ amount: "125", unit: "hourly", negotiable: "maybe", note: null });
  });
  it("ponowny zapis debriefu bez ruszania stawki jej nie wysyła (późniejsza korekta zostaje)", async () => {
    mocks.get.mockImplementation((url: string) => {
      if (url === "/api/interview-cycle/events/45") {
        return Promise.resolve({
          data: { id: 45, candidate_id: 11, job_id: 22, start: iso(-60), end: null, started: true },
        });
      }
      if (url === "/api/rate-changes") return Promise.resolve({ data: null });
      if (url.endsWith("/debrief")) {
        return Promise.resolve({
          data: {
            id: 7,
            calendar_event_id: 45,
            candidate_id: 11,
            job_id: 22,
            outcome: "good",
            candidate_comment: null,
            questions: ["Jak wdrażał CI?"],
            offer_acceptance: "likely",
            acceptance_condition: null,
            no_client_questions: false,
            current_rate_label: "120 zł/h",
            rate_change: {
              id: 3,
              status: "superseded",
              previous: "110 zł/h",
              requested: "125 zł/h",
              requested_amount: "125",
              negotiable: "maybe",
              note: null,
            },
          },
        });
      }
      return Promise.resolve({ data: [] });
    });
    mocks.put.mockResolvedValue({
      data: { id: 7, calendar_event_id: 45, candidate_id: 11, job_id: 22, outcome: "good", candidate_comment: null, questions: ["Jak wdrażał CI?"], offer_acceptance: "likely", acceptance_condition: null, no_client_questions: false, questions_saved: 0 },
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
    render(
      <QueryClientProvider client={client}>
        <DebriefDialog open onOpenChange={() => {}} eventId={45} title="Debrief" />
      </QueryClientProvider>,
    );
    await waitFor(() => expect(screen.getByLabelText("Pytanie 1")).toHaveValue("Jak wdrażał CI?"));
    fireEvent.click(screen.getByRole("button", { name: "Zapisz debrief" }));
    await waitFor(() => expect(mocks.put).toHaveBeenCalled());
    const body = mocks.put.mock.calls[0][1] as Record<string, unknown>;
    expect(body.rate_change).toBeNull();
  });
});
