import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  apiGet: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: (...args: unknown[]) => mocks.apiGet(...args) },
}));

import { ProjectsTab } from "@/app/clients/[id]/ProjectsTab";

interface FakeJob {
  id: number;
  title: string;
  location: string | null;
  status: string;
}

// draft + published → "aktywne"; closed → "zamknięte".
const ACTIVE_JOBS: FakeJob[] = [
  { id: 1, title: "Senior Python Developer", location: "Warszawa", status: "published" },
  { id: 2, title: "React Engineer szkic", location: null, status: "draft" },
];
const CLOSED_JOBS: FakeJob[] = [
  { id: 3, title: "DevOps Engineer", location: "Kraków", status: "closed" },
];

// Emuluje /api/jobs: rozdziela po statusie (open_only vs status=closed) i
// wyszukuje po tytule (q → ilike), tak jak robi to serwer.
function fakeServer(_url: string, config?: { params?: Record<string, unknown> }) {
  const params = config?.params ?? {};
  const isClosed = params.status === "closed";
  let pool = isClosed ? CLOSED_JOBS : ACTIVE_JOBS;
  const q = typeof params.q === "string" ? params.q.toLowerCase() : "";
  if (q) pool = pool.filter((j) => j.title.toLowerCase().includes(q));
  return Promise.resolve({ data: { items: pool, total: pool.length } });
}

function renderTab() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ProjectsTab clientId={42} />
    </QueryClientProvider>,
  );
}

/**
 * Kubełki są teraz przełącznikiem, nie akordeonem, więc nie ma już `<details>`
 * do inspekcji. Asercje idą po roli `tab`/`aria-selected` (Radix) oraz po
 * OBECNOŚCI wierszy w DOM.
 *
 * Świadomie `not.toBeInTheDocument()`, nie `not.toBeVisible()`: jsdom nie liczy
 * widoczności, więc `toBeVisible` przepuściłby implementację, która tylko
 * ukrywa niewybraną listę CSS-em — a ticket wymaga, żeby aktywne ZNIKAŁY.
 */
function tab(name: RegExp | string): HTMLElement {
  return screen.getByRole("tab", { name });
}

/**
 * Radix `TabsTrigger` przełącza się na pointer events, których `fireEvent.click`
 * nie emituje — dlatego kliknięcia w kubełki idą przez `userEvent`.
 * `delay: null` zdejmuje sztuczną pauzę między zdarzeniami.
 */
const setupUser = () => userEvent.setup({ delay: null });

beforeEach(() => {
  mocks.apiGet.mockReset();
  mocks.apiGet.mockImplementation(fakeServer);
});

describe("ProjectsTab — podział aktywne/zamknięte + wyszukiwarka", () => {
  it("segreguje projekty po statusie — widoczny tylko wybrany kubełek", async () => {
    const user = setupUser();
    renderTab();

    // Aktywne (published + draft) widoczne, zamknięte NIEOBECNE w DOM.
    expect(
      await screen.findByText("Senior Python Developer"),
    ).toBeInTheDocument();
    expect(screen.getByText("React Engineer szkic")).toBeInTheDocument();
    expect(screen.queryByText("DevOps Engineer")).not.toBeInTheDocument();

    await user.click(tab(/Zamknięte projekty/));

    // Po przełączeniu jest odwrotnie — aktywne wychodzą z DOM.
    expect(await screen.findByText("DevOps Engineer")).toBeInTheDocument();
    expect(screen.queryByText("Senior Python Developer")).not.toBeInTheDocument();
    expect(screen.queryByText("React Engineer szkic")).not.toBeInTheDocument();
  });

  it("pyta serwer osobno o aktywne (open_only) i zamknięte (status=closed)", async () => {
    renderTab();
    await screen.findByText("Senior Python Developer");

    expect(mocks.apiGet).toHaveBeenCalledWith(
      "/api/jobs",
      expect.objectContaining({
        params: expect.objectContaining({ client_id: 42, open_only: true }),
      }),
    );
    expect(mocks.apiGet).toHaveBeenCalledWith(
      "/api/jobs",
      expect.objectContaining({
        params: expect.objectContaining({ client_id: 42, status: "closed" }),
      }),
    );
  });

  it("pokazuje licznik przy OBU opcjach, także niewybranej", async () => {
    renderTab();
    await screen.findByText("Senior Python Developer");

    // Aktywne = 2, Zamknięte = 1. Licznik niewybranej opcji jest tym, co
    // zastąpiło auto-rozwijanie drugiej sekcji przy wyszukiwaniu — gdyby
    // zniknął (np. przez `enabled:` na drugim useQuery), użytkownik nie
    // wiedziałby, że trafienia są w drugim kubełku.
    expect(tab(/Aktywne projekty/)).toHaveTextContent("2");
    expect(tab(/Zamknięte projekty/)).toHaveTextContent("1");
  });

  it("domyślnie wybrane są Aktywne projekty", async () => {
    renderTab();
    await screen.findByText("Senior Python Developer");

    expect(tab(/Aktywne projekty/)).toHaveAttribute("aria-selected", "true");
    expect(tab(/Zamknięte projekty/)).toHaveAttribute("aria-selected", "false");
  });

  it("wyszukiwarka odpytuje serwer z parametrem q (debounced)", async () => {
    renderTab();
    await screen.findByText("Senior Python Developer");

    fireEvent.change(screen.getByLabelText("Szukaj projektów"), {
      target: { value: "Python" },
    });

    // timeout > debounce (300 ms) z zapasem — deterministyczne nawet gdyby
    // ktoś kiedyś podniósł useDebouncedValue i na wolnym runnerze CI.
    await waitFor(
      () =>
        expect(mocks.apiGet).toHaveBeenCalledWith(
          "/api/jobs",
          expect.objectContaining({
            params: expect.objectContaining({ q: "Python" }),
          }),
        ),
      { timeout: 2500 },
    );
  });

  it("wyszukiwarka filtruje AKTUALNIE wybraną listę, nie obie naraz", async () => {
    // Zastępuje test „aktywne wyszukiwanie rozwija także sekcję Zamknięte" —
    // T4 usuwa akordeon, więc ta przesłanka przestała istnieć. Trafienie
    // w drugim kubełku jest teraz widoczne przez jego licznik.
    renderTab();
    await screen.findByText("Senior Python Developer");

    fireEvent.change(screen.getByLabelText("Szukaj projektów"), {
      target: { value: "DevOps" },
    });

    await waitFor(
      () => expect(tab(/Zamknięte projekty/)).toHaveTextContent("1"),
      { timeout: 2500 },
    );
    // Wybrany kubełek nadal aktywny — wyszukiwanie nie przełącza widoku.
    expect(tab(/Aktywne projekty/)).toHaveAttribute("aria-selected", "true");
    expect(screen.queryByText("DevOps Engineer")).not.toBeInTheDocument();
  });

  it("rozróżnia pustkę po wyszukaniu od braku projektów", async () => {
    renderTab();
    await screen.findByText("Senior Python Developer");

    fireEvent.change(screen.getByLabelText("Szukaj projektów"), {
      target: { value: "zzz-nic-nie-pasuje" },
    });

    // Wybrany kubełek: komunikat "pasujących do wyszukiwania", nie
    // "Brak aktywnych projektów" — pustka po filtrze ≠ brak danych.
    await waitFor(
      () =>
        expect(
          screen.getAllByText("Brak projektów pasujących do wyszukiwania.")
            .length,
        ).toBeGreaterThanOrEqual(1),
      { timeout: 2500 },
    );
    expect(screen.queryByText("Brak aktywnych projektów.")).not.toBeInTheDocument();
  });
});
