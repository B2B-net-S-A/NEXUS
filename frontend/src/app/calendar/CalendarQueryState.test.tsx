/**
 * Kalendarz tygodniowy: awaria NIE może wyglądać jak wolny tydzień.
 *
 * `const { data: events = [], isLoading }` to komponentowa wersja „złap błąd
 * API i ustaw stan na pusty". Jedyną bramką konsumenta był `isLoading`, więc
 * przy 403/500 siatka malowała się w całości — poprawnie zadatowana i zupełnie
 * pusta. Rekruter skanujący poniedziałek rano widzi zero rozmów i odchodzi;
 * przegapiona rozmowa pali jednocześnie kandydata, hiring managera i klienta.
 *
 * Test pilnuje też dwóch mniejszych, cichych połówek tej samej usterki:
 * panelu „Najbliższe", który przy awarii po prostu znikał, oraz mapy kolizji,
 * której brak oznaczeń jest nieodróżnialny od tygodnia bez podwójnych rezerwacji.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  listEvents: vi.fn(),
  conflictsSummary: vi.fn(),
  getEvent: vi.fn(),
  listCandidates: vi.fn(),
  search: "",
  replace: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  default: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
  calendarApi: {
    listEvents: (...a: unknown[]) => mocks.listEvents(...a),
    conflictsSummary: (...a: unknown[]) => mocks.conflictsSummary(...a),
    getEvent: (...a: unknown[]) => mocks.getEvent(...a),
  },
  candidatesApi: { list: (...a: unknown[]) => mocks.listCandidates(...a) },
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(mocks.search),
  useRouter: () => ({ replace: mocks.replace, push: vi.fn() }),
}));

vi.mock("@/lib/use-debounced-value", () => ({
  useDebouncedValue: (value: unknown) => value,
}));

vi.mock("@/components/feedback/InterviewFeedbackModal", () => ({
  InterviewFeedbackModal: ({ calendarEventId }: { calendarEventId: number }) => (
    <div data-testid="feedback-modal">feedback:{calendarEventId}</div>
  ),
}));

vi.mock("@/lib/celebrate", () => ({ celebrate: vi.fn() }));

vi.mock("@/components/ConfirmDialog", () => ({
  ConfirmButton: ({ children }: { children?: React.ReactNode }) => (
    <button type="button">{children}</button>
  ),
}));

import CalendarPage from "@/app/calendar/page";

const LOADING = /Ładowanie kalendarza/;

function httpError(status: number) {
  return Object.assign(new Error(`HTTP ${status}`), { response: { status } });
}

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(
    <QueryClientProvider client={client}>
      <CalendarPage />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mocks.listEvents.mockReset();
  mocks.conflictsSummary.mockReset();
  mocks.getEvent.mockReset();
  mocks.listCandidates.mockReset();
  mocks.replace.mockReset();
  mocks.search = "";
  mocks.conflictsSummary.mockResolvedValue({ data: { pairs: {} } });
  mocks.listCandidates.mockResolvedValue({ data: { items: [] } });
});

describe("CalendarPage — awaria pobrania wydarzeń", () => {
  it("500 renderuje jawną awarię zamiast pustego tygodnia", async () => {
    mocks.listEvents.mockRejectedValue(httpError(500));

    renderPage();

    expect(
      await screen.findByText("Nie udało się pobrać danych"),
    ).toBeInTheDocument();
    expect(screen.queryByText(LOADING)).not.toBeInTheDocument();
  });

  it("403 renderuje brak uprawnień i ostrzega w panelu „Najbliższe”", async () => {
    mocks.listEvents.mockRejectedValue(httpError(403));

    renderPage();

    expect(await screen.findByText("Brak uprawnień")).toBeInTheDocument();
    // Panel „Najbliższe" przy awarii znikał bez śladu — pusta szyna czytała się
    // jako „nie masz nic zaplanowanego".
    expect(
      screen.getByText(/ta lista jest niekompletna, nie pusta/),
    ).toBeInTheDocument();
  });

  it("sukces z zerem wydarzeń renderuje siatkę bez komunikatu o awarii", async () => {
    mocks.listEvents.mockResolvedValue({ data: [] });

    renderPage();

    expect(await screen.findByText("Dzisiaj")).toBeInTheDocument();
    expect(screen.queryByText("Nie udało się pobrać danych")).not.toBeInTheDocument();
    expect(screen.queryByText("Brak uprawnień")).not.toBeInTheDocument();
  });
});

describe("CalendarPage — mapa kolizji", () => {
  it("padnięta mapa kolizji ostrzega, że brak oznaczeń nie znaczy braku kolizji", async () => {
    mocks.listEvents.mockResolvedValue({ data: [] });
    mocks.conflictsSummary.mockRejectedValue(httpError(500));

    renderPage();

    expect(
      await screen.findByText(/Nie udało się sprawdzić kolizji terminów/),
    ).toBeInTheDocument();
  });

  it("działająca mapa kolizji nie pokazuje ostrzeżenia", async () => {
    mocks.listEvents.mockResolvedValue({ data: [] });

    renderPage();

    expect(await screen.findByText("Dzisiaj")).toBeInTheDocument();
    expect(
      screen.queryByText(/Nie udało się sprawdzić kolizji terminów/),
    ).not.toBeInTheDocument();
  });
});

describe("CalendarPage — nachodzące wydarzenia i okno podglądu (UAT M03-B11)", () => {
  function eventAt(id: number, title: string) {
    const start = new Date();
    start.setHours(10, 0, 0, 0);
    const end = new Date(start);
    end.setHours(11);
    return {
      id,
      title,
      description: null,
      event_type: "meeting",
      status: "scheduled",
      start_time: start.toISOString(),
      end_time: end.toISOString(),
      all_day: false,
      attendees: [],
    };
  }

  it("dwa wydarzenia o tej samej godzinie stoją obok siebie, nie na sobie", async () => {
    mocks.listEvents.mockResolvedValue({
      data: [eventAt(1, "Spotkanie A"), eventAt(2, "Spotkanie B")],
    });
    renderPage();

    const a = await screen.findByTestId("calendar-event-1");
    const b = screen.getByTestId("calendar-event-2");
    expect(a.style.left).not.toBe(b.style.left);
    expect(a.style.width).toContain("50%");
  });

  it("Escape zamyka okno podglądu wydarzenia", async () => {
    mocks.listEvents.mockResolvedValue({ data: [eventAt(1, "Spotkanie A")] });
    renderPage();

    fireEvent.click(await screen.findByTestId("calendar-event-1"));
    const dialog = screen.getByRole("dialog", { name: "Spotkanie A" });
    expect(dialog).toBeInTheDocument();
    // Radix nasłuchuje Escape na `document` — zdarzenie z okna nie schodzi
    // do dokumentu, więc odpalamy je na samym oknie dialogowym.
    fireEvent.keyDown(dialog, { key: "Escape" });
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
  });

  // Audyt B34: własny `div` miał role/aria, ale nie zatrzymywał fokusu —
  // Tab z „Zamknij" szedł do linku „Przejdź do treści" pod oknem.
  it("okno podglądu jest modalne i przejmuje fokus po otwarciu", async () => {
    mocks.listEvents.mockResolvedValue({ data: [eventAt(1, "Spotkanie A")] });
    renderPage();

    fireEvent.click(await screen.findByTestId("calendar-event-1"));
    const dialog = screen.getByRole("dialog", { name: "Spotkanie A" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    await waitFor(() => expect(dialog.contains(document.activeElement)).toBe(true));
    // Strona pod oknem jest dla technologii asystujących ukryta.
    const grid = screen.getByTestId("calendar-event-1");
    expect(grid.closest("[aria-hidden='true']")).not.toBeNull();
  });
});

describe("CalendarPage — link ?event=<id> (audyt B39)", () => {
  function eventOn(id: number, title: string, isoStart: string) {
    return {
      id,
      title,
      description: null,
      event_type: "interview",
      status: "scheduled",
      start_time: isoStart,
      end_time: null,
      all_day: false,
      attendees: [],
    };
  }

  it("otwiera szczegóły wskazanego wydarzenia i przewija tydzień na jego datę", async () => {
    mocks.search = "event=42";
    mocks.listEvents.mockResolvedValue({ data: [] });
    // Poniedziałek daleko poza bieżącym tygodniem — miesiąc w nagłówku musi się zmienić.
    mocks.getEvent.mockResolvedValue({
      data: eventOn(42, "Rozmowa z linku", "2031-03-10T09:00:00.000Z"),
    });
    renderPage();

    expect(
      await screen.findByRole("dialog", { name: "Rozmowa z linku" }),
    ).toBeInTheDocument();
    expect(mocks.getEvent).toHaveBeenCalledWith(42);
    // Strona pod otwartym oknem jest `aria-hidden` — nagłówek trzeba szukać jawnie.
    expect(screen.getByRole("heading", { level: 1, hidden: true })).toHaveTextContent(/marzec 2031/);
  });

  it("wydarzenie z uczestnikami z M365 ({address, name}) otwiera się zamiast wywracać kalendarz", async () => {
    // Retest produkcji 15.09.2026: obiekt uczestnika renderowany wprost dawał
    // React #31 i „Coś poszło nie tak” dla każdego wydarzenia z Outlooka.
    mocks.search = "event=43";
    mocks.listEvents.mockResolvedValue({ data: [] });
    mocks.getEvent.mockResolvedValue({
      data: {
        ...eventOn(43, "Rozmowa z Outlooka", "2031-03-10T09:00:00.000Z"),
        attendees: [
          { address: "rekruter@example.com", name: "Anna Testowa" },
          { address: "kandydat@example.com", name: null },
          "reczny@example.com",
        ],
      },
    });
    renderPage();

    const dialog = await screen.findByRole("dialog", { name: "Rozmowa z Outlooka" });
    expect(dialog).toHaveTextContent("Anna Testowa");
    expect(dialog).toHaveTextContent("kandydat@example.com");
    expect(dialog).toHaveTextContent("reczny@example.com");
    expect(screen.getByText("Anna Testowa")).toHaveAttribute("title", "rekruter@example.com");
  });

  it("zamknięcie okna z linku zdejmuje parametr z adresu", async () => {
    mocks.search = "event=42";
    mocks.listEvents.mockResolvedValue({ data: [] });
    mocks.getEvent.mockResolvedValue({
      data: eventOn(42, "Rozmowa z linku", "2031-03-10T09:00:00.000Z"),
    });
    renderPage();

    await screen.findByRole("dialog", { name: "Rozmowa z linku" });
    fireEvent.click(screen.getAllByRole("button", { name: "Zamknij" })[0]);
    await waitFor(() => expect(mocks.replace).toHaveBeenCalledWith("/calendar"));
  });

  it("&action=feedback otwiera od razu formularz feedbacku zamiast szczegółów", async () => {
    mocks.search = "event=42&action=feedback";
    mocks.listEvents.mockResolvedValue({ data: [] });
    mocks.getEvent.mockResolvedValue({
      data: eventOn(42, "Rozmowa z linku", "2031-03-10T09:00:00.000Z"),
    });
    renderPage();

    expect(await screen.findByTestId("feedback-modal")).toHaveTextContent("feedback:42");
    expect(screen.queryByRole("dialog", { name: "Rozmowa z linku" })).not.toBeInTheDocument();
  });

  it("nieudane pobranie wydarzenia z linku jest jawną awarią, nie cichą siatką", async () => {
    mocks.search = "event=42";
    mocks.listEvents.mockResolvedValue({ data: [] });
    mocks.getEvent.mockRejectedValue(httpError(404));
    renderPage();

    expect(
      await screen.findByText(/Nie udało się otworzyć wydarzenia #42/),
    ).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("śmieci w parametrze nie odpalają zapytania", async () => {
    mocks.search = "event=abc";
    mocks.listEvents.mockResolvedValue({ data: [] });
    renderPage();

    expect(await screen.findByText("Dzisiaj")).toBeInTheDocument();
    expect(mocks.getEvent).not.toHaveBeenCalled();
  });
});

describe("CalendarPage — kandydat w nowym wydarzeniu (audyt B07)", () => {
  it("szuka kandydata po stronie serwera frazą, nie listą 100 ostatnich", async () => {
    mocks.listEvents.mockResolvedValue({ data: [] });
    mocks.listCandidates.mockResolvedValue({
      data: {
        items: [
          { id: 196867, name: "Anna", lastname: "Testowa", email: "anna@example.com" },
        ],
      },
    });
    renderPage();

    // Dwa przyciski „Nowe wydarzenie" (nagłówek + szyna boczna) — bierzemy pierwszy.
    fireEvent.click((await screen.findAllByRole("button", { name: /Nowe wydarzenie/ }))[0]);
    // Lista nie jest pobierana „na zapas" przy otwarciu formularza.
    expect(mocks.listCandidates).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("combobox", { name: "Kandydat (opcjonalnie)" }));
    const input = await screen.findByPlaceholderText("Szukaj kandydata…");
    fireEvent.change(input, { target: { value: "testowa" } });

    await waitFor(() =>
      expect(mocks.listCandidates).toHaveBeenCalledWith(
        expect.objectContaining({ q: "testowa", page_size: 20 }),
      ),
    );
    fireEvent.click(await screen.findByText("Anna Testowa"));
    expect(
      screen.getByRole("combobox", { name: "Kandydat (opcjonalnie)" }),
    ).toHaveTextContent("Anna Testowa");
  });
});

