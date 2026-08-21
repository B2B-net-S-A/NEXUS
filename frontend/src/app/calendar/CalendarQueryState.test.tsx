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
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  listEvents: vi.fn(),
  conflictsSummary: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  default: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
  calendarApi: {
    listEvents: (...a: unknown[]) => mocks.listEvents(...a),
    conflictsSummary: (...a: unknown[]) => mocks.conflictsSummary(...a),
  },
  candidatesApi: { list: vi.fn() },
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
  mocks.conflictsSummary.mockResolvedValue({ data: { pairs: {} } });
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
