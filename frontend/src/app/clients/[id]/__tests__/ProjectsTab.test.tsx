import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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

function detailsFor(sectionTitle: string): HTMLDetailsElement {
  const details = screen.getByText(sectionTitle).closest("details");
  if (!details) throw new Error(`No <details> for section: ${sectionTitle}`);
  return details as HTMLDetailsElement;
}

beforeEach(() => {
  mocks.apiGet.mockReset();
  mocks.apiGet.mockImplementation(fakeServer);
});

describe("ProjectsTab — podział aktywne/zamknięte + wyszukiwarka", () => {
  it("segreguje projekty po statusie do właściwych sekcji", async () => {
    renderTab();

    const activeSection = detailsFor("Aktywne projekty");
    const closedSection = detailsFor("Zamknięte projekty");

    // Aktywne (published + draft) w sekcji Aktywne, zamknięte poza nią.
    expect(
      await within(activeSection).findByText("Senior Python Developer"),
    ).toBeInTheDocument();
    expect(within(activeSection).getByText("React Engineer szkic")).toBeInTheDocument();
    expect(within(activeSection).queryByText("DevOps Engineer")).not.toBeInTheDocument();

    // Zamknięte w sekcji Zamknięte.
    expect(await within(closedSection).findByText("DevOps Engineer")).toBeInTheDocument();
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

  it("pokazuje liczbę projektów per sekcja w nagłówku", async () => {
    renderTab();
    await screen.findByText("Senior Python Developer");

    // Nagłówek Aktywne = 2, Zamknięte = 1 (widoczne bez rozwijania).
    expect(screen.getByText("Aktywne projekty").closest("summary")).toHaveTextContent("2");
    expect(screen.getByText("Zamknięte projekty").closest("summary")).toHaveTextContent("1");
  });

  it("domyślnie rozwija Aktywne, zwija Zamknięte", async () => {
    renderTab();
    await screen.findByText("Senior Python Developer");

    expect(detailsFor("Aktywne projekty").open).toBe(true);
    expect(detailsFor("Zamknięte projekty").open).toBe(false);
  });

  it("wyszukiwarka odpytuje serwer z parametrem q (debounced)", async () => {
    renderTab();
    await screen.findByText("Senior Python Developer");

    fireEvent.change(screen.getByLabelText("Szukaj projektów"), {
      target: { value: "Python" },
    });

    await waitFor(() =>
      expect(mocks.apiGet).toHaveBeenCalledWith(
        "/api/jobs",
        expect.objectContaining({
          params: expect.objectContaining({ q: "Python" }),
        }),
      ),
    );
  });

  it("aktywne wyszukiwanie rozwija także sekcję Zamknięte", async () => {
    renderTab();
    await screen.findByText("Senior Python Developer");
    expect(detailsFor("Zamknięte projekty").open).toBe(false);

    fireEvent.change(screen.getByLabelText("Szukaj projektów"), {
      target: { value: "DevOps" },
    });

    await waitFor(() => expect(detailsFor("Zamknięte projekty").open).toBe(true));
  });

  it("rozróżnia pustkę po wyszukaniu od braku projektów", async () => {
    renderTab();
    await screen.findByText("Senior Python Developer");

    fireEvent.change(screen.getByLabelText("Szukaj projektów"), {
      target: { value: "zzz-nic-nie-pasuje" },
    });

    // Obie sekcje: komunikat "pasujących do wyszukiwania", nie "Brak aktywnych".
    await waitFor(() =>
      expect(
        screen.getAllByText("Brak projektów pasujących do wyszukiwania.").length,
      ).toBeGreaterThanOrEqual(1),
    );
    expect(screen.queryByText("Brak aktywnych projektów.")).not.toBeInTheDocument();
  });
});
