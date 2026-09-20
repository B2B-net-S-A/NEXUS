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
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  listEvents: vi.fn(),
  conflictsSummary: vi.fn(),
  getEvent: vi.fn(),
  listCandidates: vi.fn(),
  cancelEvent: vi.fn(),
  deleteEvent: vi.fn(),
  updateEvent: vi.fn(),
  createEvent: vi.fn(),
  apiGet: vi.fn(),
  toast: { showError: vi.fn(), showSuccess: vi.fn(), showToast: vi.fn(), showActionToast: vi.fn() },
  search: "",
  replace: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  default: { get: (...a: unknown[]) => mocks.apiGet(...a), post: vi.fn(), delete: vi.fn() },
  calendarApi: {
    listEvents: (...a: unknown[]) => mocks.listEvents(...a),
    conflictsSummary: (...a: unknown[]) => mocks.conflictsSummary(...a),
    getEvent: (...a: unknown[]) => mocks.getEvent(...a),
    cancelEvent: (...a: unknown[]) => mocks.cancelEvent(...a),
    deleteEvent: (...a: unknown[]) => mocks.deleteEvent(...a),
    updateEvent: (...a: unknown[]) => mocks.updateEvent(...a),
    createEvent: (...a: unknown[]) => mocks.createEvent(...a),
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

vi.mock("@/components/Toast", () => ({ useToast: () => mocks.toast }));

// Potwierdzenie „w miejscu" pomijamy: klik w przycisk od razu potwierdza.
vi.mock("@/components/ConfirmDialog", () => ({
  ConfirmButton: ({
    children,
    onConfirm,
    message,
  }: {
    children?: React.ReactNode;
    onConfirm?: () => void;
    message?: string;
  }) => (
    <button type="button" data-confirm-message={message} onClick={() => onConfirm?.()}>
      {children}
    </button>
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
  mocks.cancelEvent.mockReset();
  mocks.deleteEvent.mockReset();
  mocks.updateEvent.mockReset();
  mocks.createEvent.mockReset();
  mocks.apiGet.mockReset();
  mocks.apiGet.mockResolvedValue({ data: [] });
  Object.values(mocks.toast).forEach((fn) => fn.mockReset());
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

  it("trzecie równoległe wydarzenie trafia do chipa „+1” zamiast zwężać pasy (UAT B08)", async () => {
    mocks.listEvents.mockResolvedValue({
      data: [eventAt(1, "Spotkanie A"), eventAt(2, "Spotkanie B"), eventAt(3, "Spotkanie C")],
    });
    renderPage();

    const a = await screen.findByTestId("calendar-event-1");
    expect(a.style.width).toContain("50%");
    expect(screen.queryByTestId("calendar-event-3")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Pokaż 1 kolejne wydarzenia/ }));
    // Klik MUSI trafić w pozycję z chipa „+1", nie w listę „Nadchodzące"
    // w szynie: ta pokazuje to samo wydarzenie, dopóki jest w przyszłości,
    // więc zapytanie bez zawężenia padało zależnie od pory dnia biegu CI
    // (TZ=UTC, bieg przed 10:00 → dwa przyciski „Spotkanie C").
    const overflow = within(screen.getByTestId("calendar-overflow-popover"));
    fireEvent.click(overflow.getByRole("button", { name: /Spotkanie C/ }));
    expect(await screen.findByRole("dialog", { name: "Spotkanie C" })).toBeInTheDocument();
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

  // Retest produkcji 15.09.2026 (wydarzenie z Outlooka): opis to pełny
  // dokument HTML maila, a okno pokazywało go jako tekst ze znacznikami i CSS.
  function outlookEvent(id: number) {
    const paragraph = "<p class=\"MsoNormal\">Szczegóły projektu&nbsp;i agenda rozmowy.</p>";
    return {
      ...eventOn(id, "Rozmowa z Outlooka", "2031-03-10T09:00:00.000Z"),
      candidate_name: "Jan Przykładowy",
      teams_link: "https://teams.example.com/meet/1",
      online_meeting_url: "https://teams.example.com/meet/1",
      end_time: "2031-03-10T10:00:00.000Z",
      attendees: [
        { address: "rekruter@example.com", name: "Anna Testowa" },
        { address: "kandydat@example.com", name: null },
      ],
      description:
        "<html><head><meta http-equiv=\"Content-Type\" content=\"text/html; charset=utf-8\">" +
        "<style>P {margin-top:0;margin-bottom:0;}</style></head><body>" +
        "<div>Dzień dobry,<br>zapraszam na rozmowę.</div>" +
        paragraph.repeat(80) +
        "</body></html>",
    };
  }

  it("opis z HTML-em maila pokazuje sam tekst — bez znaczników i CSS", async () => {
    mocks.search = "event=44";
    mocks.listEvents.mockResolvedValue({ data: [] });
    mocks.getEvent.mockResolvedValue({ data: outlookEvent(44) });
    renderPage();

    const dialog = await screen.findByRole("dialog", { name: "Rozmowa z Outlooka" });
    const description = screen.getByTestId("calendar-event-description");
    expect(description).toHaveTextContent("Dzień dobry, zapraszam na rozmowę.");
    expect(description.textContent).toContain("Dzień dobry,\nzapraszam na rozmowę.");
    expect(dialog.textContent).not.toMatch(/<html|<style|<p|margin-top|Content-Type/);
    expect(description).toHaveClass("whitespace-pre-line");
    // Długi opis przewija się w oknie, zamiast ucinać przyciski akcji.
    expect(screen.getByTestId("calendar-event-detail-body")).toHaveClass("overflow-y-auto");
  });

  it("Escape zamyka okno wydarzenia z uczestnikami M365 i długim opisem — także z fokusem wewnątrz", async () => {
    mocks.search = "event=44";
    mocks.listEvents.mockResolvedValue({ data: [] });
    mocks.getEvent.mockResolvedValue({ data: outlookEvent(44) });
    renderPage();

    const dialog = await screen.findByRole("dialog", { name: "Rozmowa z Outlooka" });
    await waitFor(() => expect(dialog.contains(document.activeElement)).toBe(true));
    // Fokus na elemencie głęboko w oknie (ostatni przycisk pod długim opisem).
    const inner = screen.getAllByRole("button", { name: "Zamknij" }).at(-1)!;
    inner.focus();
    expect(inner).toHaveFocus();
    fireEvent.keyDown(inner, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(mocks.replace).toHaveBeenCalledWith("/calendar");
  });

  it("Escape na samym oknie wydarzenia z M365 też je zamyka", async () => {
    mocks.search = "event=44";
    mocks.listEvents.mockResolvedValue({ data: [] });
    mocks.getEvent.mockResolvedValue({ data: outlookEvent(44) });
    renderPage();

    const dialog = await screen.findByRole("dialog", { name: "Rozmowa z Outlooka" });
    fireEvent.keyDown(dialog, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
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


function weekEvent(overrides: Record<string, unknown> = {}) {
  const start = new Date();
  start.setHours(10, 0, 0, 0);
  const end = new Date(start);
  end.setHours(11);
  return {
    id: 1,
    title: "Rozmowa",
    description: null,
    event_type: "interview",
    status: "scheduled",
    start_time: start.toISOString(),
    end_time: end.toISOString(),
    all_day: false,
    attendees: [],
    reminder_minutes: 15,
    feedback_sources: [],
    ...overrides,
  };
}

function utcDateOfToday(): string {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}T00:00:00Z`;
}

describe("CalendarPage — wpisy całodniowe i odwołane (audyt 17.09.2026)", () => {
  it("urlop idzie do paska „cały dzień”, nie do kolumny dnia", async () => {
    mocks.listEvents.mockResolvedValue({
      data: [
        weekEvent({ id: 5, title: "Urlop", all_day: true, event_type: "meeting", start_time: utcDateOfToday(), end_time: null }),
        weekEvent({ id: 6, title: "Rozmowa A" }),
      ],
    });
    renderPage();

    const strip = await screen.findByTestId("calendar-all-day-strip");
    expect(strip).toHaveTextContent("Urlop");
    expect(screen.queryByTestId("calendar-event-5")).not.toBeInTheDocument();
    // Rozmowa nie jest zwężona przez urlop.
    expect(screen.getByTestId("calendar-event-6").style.width).toContain("100%");
  });

  it("odwołane wydarzenie nie zabiera pasa i zostaje klikalne", async () => {
    mocks.listEvents.mockResolvedValue({
      data: [
        weekEvent({ id: 7, title: "Odwołana", status: "cancelled" }),
        weekEvent({ id: 8, title: "Aktualna" }),
      ],
    });
    renderPage();

    const active = await screen.findByTestId("calendar-event-8");
    const cancelled = screen.getByTestId("calendar-event-7");
    expect(active.style.width).toContain("100%");
    expect(cancelled.style.width).toContain("100%");
    expect(cancelled).toHaveAttribute("data-cancelled", "true");
    fireEvent.click(cancelled);
    expect(await screen.findByRole("dialog", { name: "Odwołana" })).toBeInTheDocument();
  });

  it("„Najbliższe” pochodzi z osobnego zapytania o nadchodzące wydarzenia", async () => {
    const future = new Date(Date.now() + 10 * 24 * 3600 * 1000).toISOString();
    mocks.listEvents.mockImplementation((params: { upcoming?: boolean }) =>
      Promise.resolve({
        data: params?.upcoming ? [weekEvent({ id: 9, title: "Za dziesięć dni", start_time: future })] : [],
      }),
    );
    renderPage();

    expect(await screen.findByText("Za dziesięć dni")).toBeInTheDocument();
    expect(mocks.listEvents).toHaveBeenCalledWith(
      expect.objectContaining({ upcoming: true, mine_only: true }),
    );
  });
});

describe("CalendarPage — okno wydarzenia (audyt 17.09.2026)", () => {
  async function openEvent(overrides: Record<string, unknown>) {
    mocks.search = "event=50";
    mocks.listEvents.mockResolvedValue({ data: [] });
    mocks.getEvent.mockResolvedValue({ data: weekEvent({ id: 50, title: "Rozmowa X", ...overrides }) });
    renderPage();
    return screen.findByRole("dialog", { name: "Rozmowa X" });
  }

  it("pokazuje eskalację, potwierdzenie kandydata i link Teams z Outlooka", async () => {
    const dialog = await openEvent({
      candidate_id: 3,
      candidate_name: "Jan Kowalski",
      needs_attention: true,
      candidate_confirmed_at: "2031-03-09T12:00:00Z",
      candidate_confirmation_source: "phone",
      online_meeting_url: "https://teams.example.com/graph",
      teams_link: null,
    });
    expect(screen.getByTestId("calendar-event-needs-attention")).toHaveTextContent(
      "Brak feedbacku po rozmowie",
    );
    expect(dialog).toHaveTextContent(/Kandydat potwierdził .* \(telefonicznie\)/);
    expect(screen.getByRole("link", { name: "Dołącz do spotkania" })).toHaveAttribute(
      "href",
      "https://teams.example.com/graph",
    );
  });

  it("„Uzupełnij feedback” otwiera formularz feedbacku tego wydarzenia", async () => {
    await openEvent({ candidate_id: 3, candidate_name: "Jan Kowalski" });
    fireEvent.click(screen.getByRole("button", { name: "Uzupełnij feedback" }));
    expect(await screen.findByTestId("feedback-modal")).toHaveTextContent("feedback:50");
  });

  it("zapisany feedback zmienia przycisk na „Edytuj feedback”", async () => {
    await openEvent({ candidate_id: 3, feedback_sources: ["client_side"] });
    expect(screen.getByRole("button", { name: "Edytuj feedback" })).toBeInTheDocument();
  });

  it("wydarzenie z Outlooka ma „Odwołaj”, nie „Usuń”, i mówi, co stało się w Outlooku", async () => {
    await openEvent({ external_source: "microsoft365", candidate_id: 3 });
    expect(screen.queryByRole("button", { name: "Usuń" })).not.toBeInTheDocument();
    mocks.cancelEvent.mockResolvedValue({
      data: { outlook: "skipped", event: weekEvent({ id: 50, title: "Rozmowa X", status: "cancelled", external_source: "microsoft365" }) },
    });
    fireEvent.click(screen.getByRole("button", { name: "Odwołaj" }));
    await waitFor(() => expect(mocks.cancelEvent).toHaveBeenCalledWith(50));
    await waitFor(() =>
      expect(mocks.toast.showError).toHaveBeenCalledWith(expect.stringMatching(/tylko w NEXUSIE/)),
    );
  });

  it("nieudane usunięcie nie jest nieme", async () => {
    await openEvent({});
    mocks.deleteEvent.mockRejectedValue(
      Object.assign(new Error("403"), { response: { status: 403, data: { detail: "Brak uprawnień do usunięcia tego wydarzenia" } } }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Usuń" }));
    await waitFor(() =>
      expect(mocks.toast.showError).toHaveBeenCalledWith("Brak uprawnień do usunięcia tego wydarzenia"),
    );
  });

  it("usunięcie ręcznego wydarzenia z feedbackiem ostrzega o utracie feedbacku", async () => {
    await openEvent({ feedback_sources: ["candidate_side"] });
    expect(screen.getByRole("button", { name: "Usuń" }).getAttribute("data-confirm-message")).toMatch(
      /feedback z tej rozmowy zostanie usunięty/,
    );
  });

  it("edycja wysyła tylko zmienione pola", async () => {
    await openEvent({ candidate_id: null });
    mocks.updateEvent.mockResolvedValue({
      data: weekEvent({ id: 50, title: "Rozmowa X", event_type: "screening" }),
    });
    fireEvent.click(screen.getByRole("button", { name: "Edytuj" }));
    fireEvent.change(screen.getByLabelText("Typ"), { target: { value: "screening" } });
    fireEvent.click(screen.getByRole("button", { name: "Zapisz zmiany" }));
    await waitFor(() => expect(mocks.updateEvent).toHaveBeenCalledWith(50, { event_type: "screening" }));
  });

  it("wydarzenie z Outlooka edytuje tylko metadane", async () => {
    await openEvent({ external_source: "microsoft365" });
    fireEvent.click(screen.getByRole("button", { name: "Edytuj" }));
    expect(screen.getByTestId("calendar-event-edit-form")).toHaveTextContent(/pochodzi z Outlooka/);
    expect(screen.queryByLabelText("Tytuł")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Od")).not.toBeInTheDocument();
  });
});

describe("CalendarPage — nowe wydarzenie (audyt 17.09.2026)", () => {
  async function openCreate() {
    mocks.listEvents.mockResolvedValue({ data: [] });
    renderPage();
    fireEvent.click((await screen.findAllByRole("button", { name: /Nowe wydarzenie/ }))[0]);
  }

  it("koniec przed początkiem blokuje zapis z komunikatem", async () => {
    await openCreate();
    fireEvent.change(screen.getByLabelText("Tytuł *"), { target: { value: "Spotkanie" } });
    fireEvent.change(screen.getByLabelText("Od *"), { target: { value: "2031-03-10T10:00" } });
    fireEvent.change(screen.getByLabelText("Do"), { target: { value: "2031-03-10T09:00" } });
    fireEvent.click(screen.getByRole("button", { name: "Utwórz wydarzenie" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/Koniec wydarzenia musi być późniejszy/);
    expect(mocks.createEvent).not.toHaveBeenCalled();
  });

  it("uczestnicy dzieleni po spacjach i średnikach, rekrutacja kandydata wybrana sama", async () => {
    mocks.listCandidates.mockResolvedValue({
      data: { items: [{ id: 7, name: "Anna", lastname: "Testowa" }] },
    });
    mocks.apiGet.mockResolvedValue({
      data: [{ stage_id: 1, job_id: 44, job_title: "Java Dev", stage: "cv_sent", ready: true }],
    });
    mocks.createEvent.mockResolvedValue({ data: {} });
    await openCreate();
    fireEvent.change(screen.getByLabelText("Tytuł *"), { target: { value: "Rozmowa" } });
    fireEvent.change(screen.getByLabelText("Od *"), { target: { value: "2031-03-10T10:00" } });
    fireEvent.change(screen.getByLabelText(/Uczestnicy/), {
      target: { value: "a@x.pl b@x.pl;c@x.pl" },
    });
    fireEvent.click(screen.getByRole("combobox", { name: "Kandydat (opcjonalnie)" }));
    fireEvent.click(await screen.findByText("Anna Testowa"));
    await waitFor(() => expect(screen.getByLabelText("Rekrutacja")).toHaveValue("44"));
    fireEvent.click(screen.getByRole("button", { name: "Utwórz wydarzenie" }));
    await waitFor(() =>
      expect(mocks.createEvent).toHaveBeenCalledWith(
        expect.objectContaining({
          candidate_id: 7,
          job_id: 44,
          attendees: ["a@x.pl", "b@x.pl", "c@x.pl"],
        }),
      ),
    );
  });
});
