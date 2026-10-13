import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { NotificationResponse } from "@/lib/api";
import type { AgendaEntry, CycleOverview, PairInfo, TodoEntry } from "@/lib/interview-cycle";
import {
  INTERVIEW_NOTIFY_EVENT,
  OPEN_INTERVIEWS_WINDOW_EVENT,
  resetCallToastsForTests,
} from "@/lib/interview-notifications";

const push = vi.hoisted(() => vi.fn());
const showActionToast = vi.hoisted(() => vi.fn());
const apiMock = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn() }));
const session = vi.hoisted(() => ({
  roles: ["recruiter"] as string[],
  seesCalendar: true,
  pipelineWrite: true,
}));

vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
// Okna akcji ładują się leniwie — w teście wystarczy wiedzieć, które otwarto.
vi.mock("next/dynamic", () => ({
  default: () =>
    function ActionDialogStub({ action }: { action: { type: string } }) {
      return <div data-testid="action-dialog">{action.type}</div>;
    },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showActionToast }),
}));
vi.mock("@/lib/api", () => ({ api: apiMock }));
vi.mock("@/store/auth", () => ({
  useAuthStore: (selector: (state: unknown) => unknown) =>
    selector({ user: { id: 5, authorization_version: 1, roles: session.roles } }),
  hasRole: (user: { roles?: string[] } | null, ...roles: string[]) =>
    roles.some((role) => user?.roles?.includes(role)),
}));
vi.mock("@/lib/nav-registry", () => ({
  visibleNavEntries: () => (session.seesCalendar ? [{ id: "calendar" }] : []),
}));
vi.mock("@/lib/section-access", () => ({
  hasSectionAccess: () => session.pipelineWrite,
}));

import { InterviewNotificationsDropdown } from "../InterviewNotificationsDropdown";

const at = (minutes: number) => new Date(Date.now() + minutes * 60_000).toISOString();

function pair(id: number, name: string): PairInfo {
  return {
    candidate_id: id,
    candidate_name: name,
    candidate_email: null,
    job_id: 100 + id,
    job_title: "Analityk danych",
    client_id: 5,
    client_name: "Klient Alfa",
  };
}

const ANNA = pair(1, "Anna Przykładowa");
const BARTEK = pair(2, "Bartek Testowy");
const CELINA = pair(3, "Celina Fikcyjna");

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

function todo(p: PairInfo, kind: TodoEntry["kind"]): TodoEntry {
  return { ...p, kind, priority: 5, due: null, event_id: null, slot_request_id: 7, mine: true };
}

const SLOT_REQUEST = {
  id: 7,
  status: "awaiting_recruiter" as const,
  slots: [{ start: at(60 * 24), end: null }],
  chosen_index: null,
  respond_by: null,
  recruiter_id: 5,
  created_by: 6,
  duration_minutes: 60,
  note: null,
  event_id: null,
};

function overview(fields: Partial<CycleOverview> = {}): CycleOverview {
  return {
    generated_at: new Date().toISOString(),
    scope: "mine",
    call_window_minutes: 30,
    items: [],
    agenda: [],
    todos: [],
    truncated: false,
    ...fields,
  };
}

function notif(id: number, type: string, link: string, fields: Partial<NotificationResponse> = {}) {
  return {
    id,
    user_id: 5,
    title: `Tytuł ${type}`,
    message: `Treść ${type}`,
    link,
    notification_type: type,
    is_read: false,
    created_at: at(-10),
    ...fields,
  } satisfies NotificationResponse;
}

const PICK_OVERVIEW = overview({
  items: [
    {
      ...CELINA,
      steps: [],
      current_step: "choice",
      latest_stage: "client_interview",
      slot_request: SLOT_REQUEST,
      interview_event_id: null,
      debrief: null,
    },
  ],
  todos: [todo(CELINA, "slots_pick")],
});
const PICK_SIGNAL = notif(41, "interview_slots_requested", "/calendar?cycle=3-103");

function serve(data: { cycle?: CycleOverview | Error; news?: NotificationResponse[] | Error }) {
  apiMock.get.mockImplementation((url: string) => {
    const body = url === "/api/interview-cycle" ? (data.cycle ?? overview()) : (data.news ?? []);
    if (body instanceof Error) return Promise.reject(body);
    return Promise.resolve({ data: url === "/api/interview-cycle" ? body : { items: body } });
  });
}

function renderDropdown() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <InterviewNotificationsDropdown />
    </QueryClientProvider>,
  );
}

// Pierwszy render (Radix, dwa zapytania) bywa wolniejszy niż domyślna sekunda
// `findBy*` na obciążonym runnerze — stąd własny budżet oczekiwania.
function findTrigger(name: string | RegExp = /^Rozmowy u klienta/) {
  return screen.findByRole("button", { name }, { timeout: 5_000 });
}

beforeEach(() => {
  push.mockReset();
  showActionToast.mockReset();
  apiMock.get.mockReset();
  apiMock.put.mockReset();
  apiMock.put.mockResolvedValue({ data: { success: true, updated: 1 } });
  session.roles = ["recruiter"];
  session.seesCalendar = true;
  session.pipelineWrite = true;
  window.localStorage.clear();
  resetCallToastsForTests();
  serve({});
});

describe("InterviewNotificationsDropdown", () => {
  it("bez pozycji „Kalendarz” w menu nie ma ikony ani zapytań", () => {
    session.seesCalendar = false;
    renderDropdown();

    expect(screen.queryByRole("button", { name: /Rozmowy u klienta/ })).toBeNull();
    expect(apiMock.get).not.toHaveBeenCalled();
  });

  it("rekruter pyta o swoje pary, Delivery Lead o swoje rekrutacje", async () => {
    const { unmount } = renderDropdown();
    await findTrigger();
    expect(apiMock.get).toHaveBeenCalledWith("/api/interview-cycle", { params: { scope: "mine" } });
    expect(apiMock.get).toHaveBeenCalledWith("/api/notifications/interviews");
    unmount();

    apiMock.get.mockClear();
    session.roles = ["delivery_lead"];
    renderDropdown();
    await findTrigger();
    expect(apiMock.get).toHaveBeenCalledWith("/api/interview-cycle", { params: { scope: "jobs" } });
  });

  it("licznik liczy wiersze, a sygnał zadania daje kropkę zamiast drugiego wiersza", async () => {
    serve({ cycle: PICK_OVERVIEW, news: [PICK_SIGNAL] });
    renderDropdown();

    const button = await findTrigger("Rozmowy u klienta — sprawy do załatwienia: 1");
    fireEvent.click(button);

    expect(await screen.findByRole("heading", { name: "Czeka na Ciebie" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Celina Fikcyjna" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "nowe" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Nowe" })).toBeNull();
  });

  it("akcja wiersza otwiera okno w miejscu i gasi zwinięte powiadomienia", async () => {
    serve({ cycle: PICK_OVERVIEW, news: [PICK_SIGNAL] });
    renderDropdown();
    fireEvent.click(await findTrigger("Rozmowy u klienta — sprawy do załatwienia: 1"));

    fireEvent.click(await screen.findByRole("button", { name: "Wybierz termin" }));

    expect(await screen.findByTestId("action-dialog")).toHaveTextContent("pick");
    expect(apiMock.put).toHaveBeenCalledWith("/api/notifications/interviews/read", { ids: [41] });
    expect(push).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.queryByRole("heading", { name: "Czeka na Ciebie" })).toBeNull());
  });

  it("klik w nazwisko prowadzi do pary w kalendarzu", async () => {
    serve({ cycle: PICK_OVERVIEW });
    renderDropdown();
    fireEvent.click(await findTrigger("Rozmowy u klienta — sprawy do załatwienia: 1"));

    fireEvent.click(await screen.findByRole("button", { name: "Celina Fikcyjna" }));

    expect(push).toHaveBeenCalledWith("/calendar?cycle=3-103");
    expect(apiMock.put).not.toHaveBeenCalled();
  });

  it("potwierdzenie terminu ma przycisk tylko z prawem do terminów od klienta", async () => {
    const confirm = overview({
      items: [
        {
          ...PICK_OVERVIEW.items[0],
          slot_request: { ...SLOT_REQUEST, status: "awaiting_dl", chosen_index: 0 },
        },
      ],
      todos: [todo(CELINA, "slots_confirm")],
    });
    serve({ cycle: confirm });
    session.pipelineWrite = false;
    renderDropdown();
    fireEvent.click(await findTrigger("Rozmowy u klienta — sprawy do załatwienia: 1"));

    expect(await screen.findByRole("button", { name: "Celina Fikcyjna" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Potwierdź" })).toBeNull();
  });

  it("„Oznacz nowe” gasi wszystkie własne powiadomienia kategorii", async () => {
    serve({ news: [notif(51, "interview_slot_confirmed", "/calendar?cycle=2-102")] });
    renderDropdown();
    fireEvent.click(await findTrigger("Rozmowy u klienta — sprawy do załatwienia: 1"));

    fireEvent.click(
      await screen.findByRole("button", { name: "Oznacz nowe powiadomienia jako przeczytane" }),
    );

    await waitFor(() =>
      expect(apiMock.put).toHaveBeenCalledWith("/api/notifications/interviews/read", undefined),
    );
  });

  it("awaria zadań nie wygląda jak brak spraw", async () => {
    serve({
      cycle: new Error("500"),
      news: [notif(52, "interview_slot_chosen", "/calendar?cycle=3-103")],
    });
    renderDropdown();
    fireEvent.click(await findTrigger("Rozmowy u klienta — sprawy do załatwienia: 1"));

    expect(await screen.findByRole("alert")).toHaveTextContent("Nie udało się wczytać zadań");
    expect(screen.getByRole("button", { name: "Tytuł interview_slot_chosen" })).toBeInTheDocument();
    expect(screen.queryByText(/Nic nie czeka/)).toBeNull();
  });

  it("awaria obu źródeł mówi o błędzie i pozwala ponowić", async () => {
    serve({ cycle: new Error("500"), news: new Error("500") });
    renderDropdown();
    fireEvent.click(await findTrigger());

    expect(await screen.findByRole("alert")).toHaveTextContent("Nie udało się wczytać rozmów");
    apiMock.get.mockClear();
    fireEvent.click(screen.getByRole("button", { name: "Ponów" }));
    await waitFor(() => expect(apiMock.get).toHaveBeenCalledTimes(2));
  });

  it("telefon po rozmowie: pigułka z odliczaniem i jeden dymek z „Zapisz debrief”", async () => {
    serve({ cycle: overview({ agenda: [agenda(ANNA, "call", { start: at(-12), end: at(18) })] }) });
    const { unmount } = renderDropdown();

    await findTrigger("Rozmowy u klienta — zadzwoń: A. Przykładowa, zostało 18 min");
    await waitFor(() => expect(showActionToast).toHaveBeenCalledTimes(1));
    const [message, options] = showActionToast.mock.calls[0];
    expect(message).toBe(
      "Anna Przykładowa (Klient Alfa): rozmowa u klienta skończyła się. Na telefon zostało 18 min.",
    );
    expect(options.actionLabel).toBe("Zapisz debrief");

    act(() => options.onAction());
    expect(await screen.findByTestId("action-dialog")).toHaveTextContent("debrief");

    // Druga karta albo odświeżenie strony nie powtarza dymka.
    unmount();
    resetCallToastsForTests();
    showActionToast.mockReset();
    renderDropdown();
    await findTrigger("Rozmowy u klienta — zadzwoń: A. Przykładowa, zostało 18 min");
    expect(showActionToast).not.toHaveBeenCalled();
  });

  it("powiadomienie z gniazda daje dymek, a „Pokaż” otwiera okienko", async () => {
    renderDropdown();
    await findTrigger();

    act(() => {
      window.dispatchEvent(
        new CustomEvent(INTERVIEW_NOTIFY_EVENT, {
          detail: {
            id: 61,
            title: "Terminy rozmowy od klienta",
            message: "3 terminy rozmowy u klienta do ustalenia z kandydatem (Analityk danych).",
            link: "/calendar?cycle=3-103",
            notification_type: "interview_slots_requested",
            created_at: at(0),
          },
        }),
      );
    });

    expect(showActionToast).toHaveBeenCalledTimes(1);
    const [message, options] = showActionToast.mock.calls[0];
    expect(message).toBe("3 terminy rozmowy u klienta do ustalenia z kandydatem (Analityk danych).");
    expect(options.actionLabel).toBe("Pokaż");
    act(() => options.onAction());
    expect(await screen.findByRole("heading", { name: "Rozmowy u klienta" })).toBeInTheDocument();
  });

  it("przypomnienie przed prepem z linkiem Teams prowadzi prosto do spotkania", async () => {
    const prep = agenda(BARTEK, "prep2", {
      start: at(40),
      end: at(70),
      event_id: 77,
      online_meeting_url: "https://teams.example.invalid/prep",
    });
    serve({ cycle: overview({ agenda: [prep] }) });
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    renderDropdown();
    await findTrigger();
    await waitFor(() => expect(apiMock.get).toHaveBeenCalledTimes(2));
    await act(async () => {
      await Promise.resolve();
    });

    act(() => {
      window.dispatchEvent(
        new CustomEvent(INTERVIEW_NOTIFY_EVENT, {
          detail: {
            id: 62,
            title: "Przypomnienie o wydarzeniu",
            message: "Za 15 minut: Prep 2",
            link: "/calendar?event=77",
            notification_type: "interview_scheduled",
            created_at: at(0),
          },
        }),
      );
    });

    const [message, options] = showActionToast.mock.calls[0];
    expect(message).toBe("Za 15 minut: Prep 2");
    expect(options.actionLabel).toBe("Dołącz");
    options.onAction();
    expect(open).toHaveBeenCalledWith(
      "https://teams.example.invalid/prep",
      "_blank",
      "noopener,noreferrer",
    );
    open.mockRestore();
  });

  it("podpowiedź z dzwonka otwiera okienko zdarzeniem okna", async () => {
    renderDropdown();
    await findTrigger();

    act(() => {
      window.dispatchEvent(new CustomEvent(OPEN_INTERVIEWS_WINDOW_EVENT));
    });

    expect(await screen.findByText(/Nic nie czeka w sprawie rozmów u klienta/)).toBeInTheDocument();
  });
});
